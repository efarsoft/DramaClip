"""LLM 编剧：读取带时间戳的台词转写，产出结构化推广解说剧本。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from dramaclip.engines.llm_trace import dump_trace
from dramaclip.engines.narration.numerals import to_chinese_numerals
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable

logger = logging.getLogger(__name__)

_CHARS_PER_SECOND = 4.2  # 中文 TTS 语速估算（约 250 字/分钟）
_MIN_SEGMENTS = 2
# 清洗后正文段数硬门：system 写了 12-28 是软要求，模型偷懒给 8 段照样过——
# 低于此门触发强化重掷，三次仍不达标整条方案失败（宁掷勿滥，时长让位质量的姊妹裁决）。
_MIN_BODY_SEGMENTS = 12
_EPISODE_LINE_CAP = 80
_TOTAL_LINE_CAP = 500
_MIN_LINES_PER_EPISODE = 3  # 集数再多，每集也至少露面的保底线
_MAX_ATTEMPTS = 3  # 首次 + 最多 2 次重试：网关抖动与模型手滑都不该一次判死
# 网络类失败（LlmUnavailable）的退避：端点停顿窗口常在分钟级，背靠背重试只会
# 再撞一次（2026-10-06 真机：内心独白变体连续两次读超时整条报废）。格式类失败不退避。
_RETRY_BACKOFF_S = (15.0, 30.0)

# 重试注入的格式强化：原样重问等于期待模型原样再犯一遍。
_FORMAT_REINFORCEMENT = (
    "\n\n【格式强化】上一次输出不是合法 JSON 或结构不符合要求。"
    "请严格按要求只输出 JSON：不要 markdown 围栏、不要任何多余文字；"
    "每个片段必须含 episode/start/end/text，且 0 <= start < end，不得超过该集时间上界。"
)

# 基本功层（永远注入，不交给模型发挥）：平台验证过的解说手艺底线。
# 拆成「通用底座 + 全稿版 / 逐槽版」三张，按调用上下文拼——避免「全稿」规则被注入到
# 「逐槽」场景（模型一次只见一个槽，满足不了全稿级规则，反而变成噪声）。
# 设计纪律：硬禁令只留真正跨上下文成立的；手艺方向标「稀疏用」，禁止每段齐备——
# 真人是有偏科的，每条规则都用满本身就是新的机器特征。

# —— 通用底座（剧本与填词共用，只放真正跨上下文成立的铁律）——
_FUND_BASE = (
    """
【解说基本功——逐条强制遵守】
交付目标：这是导看全集的推广片，不是剧情摘要、不是观后感；看完必须还想点进去看原片，最大反转扣在全集里，本片只给一半答案。
视角与语言：全程口语化说书人视角，短句为主；禁止书面腔、总结腔（如「本剧讲述了…」），禁止空洞形容词堆砌；人称二选一并全篇统一，禁止中途切换。
禁元叙述（零容忍）：解说员在讲故事不在讲文件——「第X集」「画面里」「镜头」「素材」这类字眼一个不许有，观众不该意识到这是被剪出来的视频。
数字一律写中文（两千斤/八年/四十七块）：「2,000斤」是报表写法，配音念出来全毁。
内容纪律：所有情节、细节、台词必须来自给定转写，禁止编造转写外的事件或设定；优先引用最有画面感的具体细节（动作/冲突/原话），拒绝抽象概括。真实锚点（年份/金额/物件/称呼）只能原样摘自转写，转写里没有就少写，禁止为凑数发明——编出来的「具体」比抽象更假，观众一听就出戏。
低可信度兜底：若转写含明显错字、方言听不懂或断句不清，只讲画面里能确定的事，拿不准用「画面中看来/像是」，绝不补情节、补人物关系、补数量；转写没点名的人用「那人/她/对方」代称，不许安插转写外身份（如「九千岁」「嫡姐」）与数量（如「八千两」）；宁可少说，不许编圆。
全篇禁揭晓腔：禁「竟是/竟然/居然/原来/没想到」式事后揭秘——解说在讲正在发生的事，不是抖包袱；身份与真相要在画面里自然带出，不靠「竟是」硬揭。
文画咬合（台词锚定）：钩子必须从取材区间的台词里长出来——凭空写一个区间里没有的场面，观众看到的是文不对题。
称谓即立场：反派用标签化定性词（渣男/恶婆婆/赵家恶少），正面角色用中性称呼配同情式定语（被逼替嫁的女孩）；全稿有名有姓的人物不超三个，其余一律代称；同一人物全稿只用一个写法。
"""
)

# —— 全稿版（仅剧本链路：模型一次看到整条故事线时才成立）——
_FUND_FULL_ONLY = (
    """
【全稿手艺（仅剧本生效）】
吸引力定律（成稿唯一评分标准；人味与去AI味是及格线不是目标）：
· 观众想知道「接下来会怎样」——每段结尾埋的问题必须是「接下来呢」，写完每段问自己：这句话让人不得不往下看吗？不会就重写收尾。
· 悬念切在情绪最高点：未完成的比完成的记得牢，在心跳最快处切才是钩子。
· 好奇缺口要具体（她为什么笑/钱去哪了），禁止「后续更精彩」式空缺口。
· 反差写进同一句：「全城最怂的会计，却是黑帮最怕的杀手」——一句内对撞狠十倍。
· 信息差是最大武器：每稿至少两处「观众知道角色不知道」或反之，这是看家本领。
人味纪律（去AI味是及格线）：AI味本质是话说太满太齐——禁书面连接词（然而/随即/顿时/缓缓/宛如），口语替代（结果/转头/当场/哪成想）；禁工整对仗与排比，句长必须长短交错；禁套话与先否后肯（不是…而是…/既…又…），转折只用「结果/谁知/哪成想」；允许没说完的半句、允许省略主语，禁止每段都收束总结；连续两段不得同一主语或同一句式起手。
架构纪律：禁解释主题与动机（让事件自己说话）；因果接缝必须能连读，禁止「怎么突然跳到这」；情绪用行动与选择呈现（「她把婚书扔进火里」胜过「她愤怒至极」）；真实锚点每稿至少三个具体名词（年份/金额/物件），且必须原样出自转写，转写没有就减，绝不为凑数编造——宁可少锚点也不许发明。
结构与节奏：前 3 秒抛出全片最大反差（具体事实，禁「他竟然」式空钩）；每段只讲一个信息点，段间递进靠内容本身；善用半句钩把揭晓切在段边界；正文必须连续故事线（起因→升级→反转→高潮），禁止跳跃拼凑；最后一段停在最高潮的半拍上（剑落一半/身份将出口），禁把事件讲圆再接 CTA；主轴诉求是全稿唯一路标，每次跳集/换冲突第一句挂回它；跳时间线给路标（八年前/与此同时）。
悬念管理：最大反转不得提前剧透，关键信息延后到结尾前；结尾留「想知道结局」的缺口，CTA 只准引导看全集（可带剧名），禁空喊关注/点赞/收藏/二维码。
"""
)

# —— 逐槽版（仅填词链路：模型一次只见一个槽位，只放单槽能执行的）——
_FUND_SLOT_ONLY = (
    """
【逐槽手艺（仅填词生效）】
你这一个槽位只干一件事：完成它的「要做的事」（契约），别跑题。
写法要像人在饭桌上讲八卦：短句为主、长短交错、口语词优先（结果/当场/直接），禁书面连接词（然而/随即/顿时/缓缓/宛如），转折只用「结果/谁知/哪成想」；允许没说完的半句，禁止每段都收束总结。
相邻槽位要能连读成一条故事线，条尾可留半句钩勾住下一条——但稀疏用，别每条都齐备所有手法，真人有偏科。
开场槽 3 秒内抛具体反差事实（可引区间内最冲突原话），禁「他竟然…」；收尾/CTA 槽留缺口引导看全集，禁关注/点赞/二维码，禁剧透最大反转。
原话引用每段至多一处，念着拗口就重写——这段要被配音念出来，不是给人看的文章。
"""
)

FUNDAMENTALS = _FUND_BASE + _FUND_FULL_ONLY  # 向后兼容：剧本链路拿全量
FUNDAMENTALS_SLOT = _FUND_BASE + _FUND_SLOT_ONLY  # 逐槽填词链路

_STRUCTURE_PROMPT = (
    """
你是这部剧的专属解说编剧：全集看了三遍，角色底细如数家珍，现在在饭桌上给朋友讲它——讲完他要连夜去刷原剧。事实只来自下面给出的台词。
根据带时间戳的台词转写，输出推广解说剧本 JSON：{"hook": "开场钩子(1-2句)", "segments": [{"episode": 集号整数, "start": 数字秒, "end": 数字秒, "text": "该片段解说文案"}], "cta": "结尾引导语(1句)"}。
结构硬约束（违反即不合格）：每个片段都必须带 episode，一个都不能漏；start/end 取自转写台词的时间区间，不得超过该集上界；同集内按时间递增且互不重叠；换集优先取相邻集，大跨度跳集只许跳往确有关键爆点的集，且前集段尾必须把跨集因果说破，禁止无因果跳切；hook 必须含一个具体反差事实（身份/生死/数字），禁「他竟然…」式空泛悬念；cta 必须是三段式转化引导（悬念半句+「点击左下角」+「免费/立即观看全集」，可带剧名），禁剧透最大反转、禁空喊关注/点赞/收藏/二维码；只输出 JSON，不要多余文字。
台词前的[角色X]是声纹聚类标签，同一标签即同一个人：写文案时换成你从称呼与剧情推断出的真名，推断不出再保留原标签；关键台词可原样引用（加引号）增强真实感。
    """
)




def fundamentals_layer(
    prompts: dict[str, str] | None = None, scope: str = "full"
) -> str:
    """基本功层文本：剧本链路用全稿版，逐槽填词用逐槽版（模型一次只见一个槽，
    注入全稿规则只是噪声）。scope=full→FUNDAMENTALS，slot→FUNDAMENTALS_SLOT。"""
    if prompts and (text := prompts.get("prompt.scriptwriter_fundamentals")):
        return text
    return FUNDAMENTALS if scope == "full" else FUNDAMENTALS_SLOT



def system_prompt(prompts: dict[str, str] | None = None) -> str:
    """真正发出去的 system = 结构指令 + 基本功层，两层各自可覆盖、各自不吞对方。"""
    overrides = prompts or {}
    structure = overrides.get("prompt.scriptwriter_system") or _STRUCTURE_PROMPT
    return structure + fundamentals_layer(overrides)


class ScriptSegment(BaseModel):
    """剧本片段：源视频区间 + 对应解说文案（跨集时 episode 为集号）。"""

    episode: int = 1
    start: float
    end: float
    text: str


class Script(BaseModel):
    """解说剧本：钩子 + 正文片段 + 结尾引导。"""

    hook: str = Field(min_length=1)
    segments: list[ScriptSegment] = Field(min_length=_MIN_SEGMENTS)
    cta: str = ""

    @field_validator("hook", "cta")
    @classmethod
    def _cn_numeral_fields(cls, value: str) -> str:
        # 出口单一收口：hook/正文/cta 三个字段的数字中文化在这里一次做完，
        # 不靠提示词遵从率（真机 2,000 斤事故）
        return to_chinese_numerals(value)

    @field_validator("segments")
    @classmethod
    def _cn_numeral_segments(
        cls, segments: list[ScriptSegment]
    ) -> list[ScriptSegment]:
        for segment in segments:
            segment.text = to_chinese_numerals(segment.text)
        return segments
    # 清洗层吃掉的段数（未知集号/越界/重叠/空文案）：随剧本一路带到方案卡，
    # 界面据此说"剧本丢弃 N 段"，不再让方案看起来天生就这么长。
    dropped_segments: int = 0


def estimate_duration(text: str) -> float:
    """按文案字数估算 TTS 时长（合成后以实际音频时长回填）。"""
    return max(1.0, round(len(text) / _CHARS_PER_SECOND, 2))


def _require_explicit_episode(raw: Any, durations: dict[int, float]) -> None:
    """多集输入下缺 episode 等于把别的集的段落悄悄塞回第 1 集：宁可重试也不猜。"""
    if len(durations) < 2:
        return
    segments = raw.get("segments") if isinstance(raw, dict) else None
    if not isinstance(segments, list):
        return
    for segment in segments:
        if isinstance(segment, dict) and "episode" not in segment:
            raise ValueError(
                f"剧本片段缺 episode 集号（{segment.get('start', '?')}s 起那段）："
                "多集输入下无法安全归位"
            )


def _sanitize_episodes(raw: Any, durations: dict[int, float]) -> tuple[Script | None, int]:
    """跨集剧本清洗：未知集号丢弃、逐集去重叠、集内时间越界裁剪、最少段数。

    返回 (剧本, 钳制段数)：钳制是悄悄改数（负起点抬到 0、超长尾裁到集时长、
    重叠段起点后移），段数进留痕才能对上「剧本为什么变短了」这笔账。
    集时长缺失（<=0）等于没有上界可钳：只去重叠不裁尾，宁可放过也不整批丢光。
    """
    script = Script.model_validate(raw)
    kept: list[ScriptSegment] = []
    cursors: dict[int, float] = {}
    clamped = 0
    for segment in sorted(script.segments, key=lambda s: (s.episode, s.start)):
        if segment.episode not in durations:
            continue
        duration = durations[segment.episode]
        start = max(segment.start, cursors.get(segment.episode, 0.0))
        end = min(segment.end, duration) if duration > 0 else segment.end
        text = segment.text.strip()
        if end - start < 0.5 or text == "":
            continue
        updated = {"start": round(start, 2), "end": round(end, 2), "text": text}
        if updated["start"] != segment.start or updated["end"] != segment.end:
            clamped += 1
            logger.info(
                "剧本段钳制：第%d集 %s-%ss → %s-%ss",
                segment.episode,
                segment.start,
                segment.end,
                updated["start"],
                updated["end"],
            )
        kept.append(segment.model_copy(update=updated))
        cursors[segment.episode] = end
    if len(kept) < _MIN_SEGMENTS:
        return None, clamped
    dropped = len(script.segments) - len(kept)
    return (
        script.model_copy(update={"segments": kept, "dropped_segments": dropped}),
        clamped,
    )


def clock(seconds: float) -> str:
    """秒 → MM:SS（转写展示用）：公开给 copywriter 复用，别再各抄一份。"""
    minutes, secs = divmod(max(int(seconds), 0), 60)
    return f"{minutes:02d}:{secs:02d}"


def transcript_sampling_quota(
    episode_count: int,
    *,
    total_cap: int = _TOTAL_LINE_CAP,
    episode_cap: int = _EPISODE_LINE_CAP,
) -> int:
    """跨集转写的每集摘录配额。
    """
    if episode_count <= 0:
        return 0
    return min(max(total_cap // episode_count, _MIN_LINES_PER_EPISODE), episode_cap)


def _pick_across(segments: list[dict[str, Any]], quota: int) -> list[dict[str, Any]]:
    """单集内跨头尾均匀取 quota 段（必含首段与尾段）。
    """
    if quota <= 0 or not segments:
        return []
    last = len(segments) - 1
    if last < quota:  # 配额够整集：一段不丢
        return list(segments)
    if quota == 1:
        return [segments[last]]  # 只能留一段时留集尾（钩子）
    indices = sorted({round(i * last / (quota - 1)) for i in range(quota)})
    return [segments[i] for i in indices]


def _transcript_note(
    *,
    episode_count: int,
    total_segments: int,
    quota: int,
    kept: int,
) -> str:
    """向模型交代看到的是配额摘录还是全量逐字；静默取样等于骗模型。"""
    dropped = max(total_segments - kept, 0)
    if dropped == 0:
        return f"\n（共 {episode_count} 集、{total_segments} 段转写，以下即全量逐字。）"
    return (
        f"\n（共 {episode_count} 集、{total_segments} 段转写；受上下文预算限制，"
        f"以下为每集跨头尾均匀摘录约 {quota} 段、合计 {kept} 段，另有约 {dropped} 段未列出。"
        "每集首尾台词均已保留，中间为等距抽样——"
        "请据此判断全剧故事线、以及各集在高潮曲线上的位置。）"
    )


def _episode_bound_note(segments: list[dict[str, Any]], duration: float) -> str:
    """把清洗层真正执行的时间上界告诉模型：藏住上界等于让模型盲写、再整段丢弃。"""
    ceiling = max(float(seg.get("end", 0)) for seg in segments)
    note = f"（本集台词截至 {clock(ceiling)}"
    if duration > 0:
        note += f"，全长 {clock(duration)}"
    return note + "）"


def format_transcript_episodes(
    episode_inputs: list[dict[str, Any]],
    *,
    total_cap: int = _TOTAL_LINE_CAP,
    episode_cap: int = _EPISODE_LINE_CAP,
) -> str:
    """把多集转写拼成带集号与时间戳的输入块：预算内每集都有代表，绝不按集号头部截断。
    """
    usable = [ep for ep in episode_inputs if ep.get("segments")]
    if not usable:
        return ""
    quota = transcript_sampling_quota(len(usable), total_cap=total_cap, episode_cap=episode_cap)
    lines: list[str] = []
    kept = 0
    for episode in usable:
        all_segments = list(episode["segments"])
        rendered: list[str] = []
        for seg in _pick_across(all_segments, quota):
            text = str(seg.get("text", "")).strip()
            if text == "":
                continue
            span = f"{clock(float(seg.get('start', 0)))}-{clock(float(seg.get('end', 0)))}"
            # 声纹聚类标签（说话人分离开启时才有）：编剧看到的是「谁在说」，
            # 真名化是它的活——业主不看素材，角色名只能由读台词的人（LLM）推断。
            speaker = str(seg.get("speaker") or "").strip()
            prefix = f"[{speaker}] " if speaker else ""
            rendered.append(f"{span} {prefix}{text}")
        if not rendered:  # 一行没进就不留孤立集标题
            continue
        lines.append(f"【第{int(episode['number'])}集】")
        lines.append(_episode_bound_note(all_segments, float(episode.get("duration") or 0.0)))
        lines.extend(rendered)
        kept += len(rendered)
    total_segments = sum(len(ep["segments"]) for ep in usable)
    lines.append(
        _transcript_note(
            episode_count=len(usable),
            total_segments=total_segments,
            quota=quota,
            kept=kept,
        )
    )
    return "\n".join(lines)


def format_visual_tracks(episode_inputs: list[dict[str, Any]]) -> str:
    """有画面轨的集各拼一段紧凑画面实据；无画面的集不出现（分档语义，P2c）。

    输出行形如「2.1s 中景 宫殿内厅：帝王坐龙椅，红袍官员侍立（庄重）」——
    帧时间是该集相对秒，与台词转写的「开始-结束」同一时间轴，编剧可对位取用。
    """
    blocks: list[str] = []
    for episode in episode_inputs:
        frames = episode.get("visual_track") or []
        if not frames:
            continue
        lines: list[str] = []
        for frame in frames:
            t_label = f"{float(frame.get('t') or 0.0):.1f}s"
            body = " ".join(
                str(frame.get(key, "")).strip() for key in ("shot", "scene")
                if str(frame.get(key, "")).strip()
            )
            people = str(frame.get("people", "")).strip()
            if people:
                body += ("：" if body else "") + people
            action = str(frame.get("action", "")).strip()
            if action:
                body += "，" + action
            mood = str(frame.get("mood", "")).strip()
            if mood:
                body += f"（{mood}）"
            lines.append(f"{t_label} {body}".strip())
        if lines:
            blocks.append(f"【第{int(episode['number'])}集·画面轨】\n" + "\n".join(lines))
    if not blocks:
        return ""
    return (
        "画面轨（每集按时间均采的画面实据，时间=该集相对秒，与台词时间轴同源）：\n"
        + "\n".join(blocks)
        + "\n画面轨用法：写某段的画面描写必须与该段取材区间内的画面轨条目一致——"
        "台词说到的画面在画面轨里有实据；无画面轨的集维持纯台词锚定；"
        "画面轨里出现的任何文字（人名字条/题字）是视频叠加物，不得当台词或人名引用。"
    )


def build_script_request(
    episode_inputs: list[dict[str, Any]],
    *,
    project_name: str,
    angle_block: str,
    style_directives: str = "",
    prompts: dict[str, str] | None = None,
) -> tuple[str, str]:
    """纯函数：组装剧本链路的 (system, user) 提示词，不调用 LLM。

    抽出来供审计/回放工具复用，确保「实际发出去的提示词」与生成函数同源——
    改了提示词，这里与 write_script_episodes 拿到的一定是同一份。
    """
    transcript_block = format_transcript_episodes(episode_inputs)
    if not transcript_block:
        raise ValueError("编剧无米下锅：所有集都没有台词转写")
    cross_block = (
        "跨集叙事要求：转写按集分组（每组以「【第N集】」单独一行开头，"
        "下一行给出该集的时间上界），其后每行一条台词，格式为「开始-结束 台词」，"
        "时间为该集内的相对时间。"
        "受上下文预算限制，每组是该集跨头尾的均匀摘录（集首与集尾台词必定保留），"
        "不是该集全量逐字。"
        "1) 片段结构按 system 要求 1)：episode 逐段必填，start/end 用各集自己的相对秒，"
        "禁止把多集拼成一条连续时间轴；"
        "2) 按剧情逻辑排序：铺垫在前、冲突升级居中、反转/高潮在后，可在不同集之间选取；"
        "3) 同一片段的画面必须取自同一集，同一集内按时间顺序。"
    )
    style_block = f"\n解说风格要求：{style_directives}" if style_directives != "" else ""
    visual_block = format_visual_tracks(episode_inputs)
    visual_suffix = f"\n\n{visual_block}" if visual_block else ""
    user_prompt = (
        f"项目：{project_name}\n"
        f"按 system 给定的段数区间给够段数，把冲突讲透、反转给足戏份。\n"
        f"铺垫果断压缩，绝不为赶时长删掉关键冲突或草草收尾。\n"
        f"{cross_block}\n"
        f"{angle_block}\n"
        f"台词转写：\n" + transcript_block
        + visual_suffix
        + f"{style_block}"
    )
    system = system_prompt(prompts)
    return system, user_prompt


def write_script_episodes(
    llm: LlmClient,
    episode_inputs: list[dict[str, Any]],
    *,
    project_name: str,
    angle_block: str,
    style_directives: str = "",
    trace_path: Path | None = None,
    prompts: dict[str, str] | None = None,
    min_segments: int | None = None,
) -> Script:
    """跨集剧本：读多集转写（每集一个「【第N集】」分组），产出带集号的跨集故事剧本。
    """
    durations = {
        int(episode["number"]): float(episode.get("duration") or 0.0)
        for episode in episode_inputs
    }
    system, user_prompt = build_script_request(
        episode_inputs,
        project_name=project_name,
        angle_block=angle_block,
        style_directives=style_directives,
        prompts=prompts,
    )
    # 薄稿硬门按集数推导：2 段/集（10 集→20 段，单集→2 段），LLM 偷懒给薄稿
    # 会触发强化重掷；下限跟着输入规模走，单集项目不被跨集的尺子误杀。
    floor = max(2, 2 * len(episode_inputs)) if min_segments is None else min_segments
    attempts: list[dict[str, Any]] = []
    script: Script | None = None
    for attempt in range(_MAX_ATTEMPTS):
        # 重试注入格式强化：原样重问等于期待模型原样再犯
        ask = user_prompt + _FORMAT_REINFORCEMENT if attempt > 0 else user_prompt
        if attempts and attempts[-1].get("rejected"):
            tail_note = (
                f"上一次你只写了 {attempts[-1]['rejected']}。"
                "每集的冲突都要铺开成段，段数不够能力就是不及格——这次必须给满段数。"
            )
            ask += "\n\n" + tail_note
        raw: Any = None
        try:
            raw = llm.chat_json(system, ask, temperature=0.75)
            _require_explicit_episode(raw, durations)
            script, clamped = _sanitize_episodes(raw, durations)
        except (LlmUnavailable, ValidationError, ValueError, TypeError, KeyError) as exc:
            # 留痕必须带上异常类型：网关挂了与 schema 不合规是两件完全不同的事；
            # 坏响应原文一并留下——只记异常文案，排查时分不清模型到底写了什么。
            attempt_trace: dict[str, Any] = {"error": f"{type(exc).__name__}: {exc}"}
            if raw is not None:
                attempt_trace["raw"] = raw
            attempts.append(attempt_trace)
            if isinstance(exc, LlmUnavailable) and attempt < _MAX_ATTEMPTS - 1:
                # 端点停顿窗口常在分钟级：退避等窗口过去，背靠背重试只会再撞一次
                delay = _RETRY_BACKOFF_S[min(attempt, len(_RETRY_BACKOFF_S) - 1)]
                logger.warning(
                    "LLM 网络类失败，%.0fs 后重试 (%d/%d)", delay, attempt + 1, _MAX_ATTEMPTS
                )
                time.sleep(delay)
            continue
        attempts.append(
            {
                "raw": raw,
                "accepted": script is not None,
                "segments_kept": len(script.segments) if script is not None else 0,
                "segments_dropped": script.dropped_segments if script is not None else 0,
                "segments_clamped": clamped,
            }
        )
        if script is not None and len(script.segments) < floor:
            kept = len(script.segments)
            attempts[-1]["rejected"] = f"正文仅 {kept} 段（要求至少 {floor} 段）"
            script = None
        if script is not None:
            break
    dump_trace(
        trace_path,
        {"system": system, "user": user_prompt, "attempts": attempts},
    )
    if script is None:
        detail = "；".join(str(item.get("error", "清洗后片段不足")) for item in attempts)
        raise ValueError(
            f"编剧未产出合法剧本（{len(attempts)} 次尝试）：{detail}"
            + (f"；完整往返见 {trace_path}" if trace_path else "")
        )
    return script


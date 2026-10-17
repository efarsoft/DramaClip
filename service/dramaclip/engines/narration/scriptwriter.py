"""LLM 编剧：读取带时间戳的台词转写，产出结构化推广解说剧本。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

from dramaclip.engines.llm_trace import dump_trace
from dramaclip.engines.narration import audit as A
from dramaclip.engines.narration.numerals import to_chinese_numerals
from dramaclip.engines.semantic.llm_client import LlmClient, LlmUnavailable

logger = logging.getLogger(__name__)

_CHARS_PER_SECOND = 4.2  # 中文 TTS 语速估算（约 250 字/分钟）
_MIN_SEGMENTS = 2  # Pydantic schema 层解析下限，仅拦空稿
# 正文段数下限：只作「防退化」兜底——拦住 1~2 段把整条故事一笔带过的空洞稿，
# 而非按时长凑段。业主优先级为「成品质量/完整度 > 时长」，故不设随集数膨胀的硬门
# （原 12 / 2×集数 会逼短故事复述或整条失败）。下限刻意压低，靠提示词与评分器保
# 完整度而非靠段数凑时长。可由 settings.narration_min_segments 覆盖微调（2~30）。
_MIN_BODY_SEGMENTS = 4
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

# —— 文风标杆（单一真相源：解说底座与 tools 文案改写共用这一份）——
STYLE_CARD = """
【文风标杆——写完对照这段的语感，手法就藏在示范里】
妻子把丈夫的药倒进了老鼠洞。没多会儿，老鼠四脚一蹬，没了动静。她这才明白，丈夫的病总不见好，不是命不好——是药里有人动了手脚。下毒的会是谁？她把这句话咽回肚子里，照常烧水做饭，等着那人露出第二回马脚。
手法标签：第一句就砸具体动作或处境，禁从背景设定讲起；人物先身份后名字（「这个煎蛋的男人叫杰夫，退役特种兵」式）；短句动作链推进，却/可/竟/直到做转折；用具体数字不用空洞形容；反派给标签化定性词（渣男/恶婆婆），正面人物给同情式定语（被逼替嫁的女孩）；代称要好记（账房先生/那毒妇式）但绝不编造转写外的真名；关键台词可加引号直给。人物数量由故事决断，但每个出场的人都要让观众认得出来（身份或关系随出场带一句）；同一人物全稿只用一个写法。
"""

# —— 通用底座（剧本与填词共用，只放真正跨上下文成立的铁律）——
# 2026-10-13 整体重构：微观句法禁令清单（禁排比/句长交错/连续主语/先否后肯/转折词表等）
# 由「文风标杆示范 + 手法标签」替代——示范对齐语感比禁令清单更接近真实爆款文风；
# 审查器（audit）仍是兜底网。被 audit 引用的规则句子保持原文不动。
_FUND_BASE = (
    """
【解说基本功——逐条强制遵守】
交付目标：这是导看全集的推广片，不是剧情摘要、不是观后感。反转的「发生」可以放开头——预告式开场把最高冲突画面放开头正是设计；但反转的谜底与人物结局必须扣在全集里，「为什么/后来呢」不给答案，本片只给一半答案。
内容纪律：所有情节、细节、台词必须来自给定转写，禁止编造转写外的事件或设定；真实锚点（年份/金额/物件/称呼）只能原样摘自转写，转写里没有就少写，禁止为凑数发明——编出来的「具体」比抽象更假，观众一听就出戏。专有名词照转写里的写法，转写没给的宁写「那座山」「京城」，不用你记忆里的山名剧名补齐。转写没点名的人用「那人/她/对方」代称，不许安插转写外身份；转写含明显错字、听不清或断句乱时，只讲画面里能确定的事，宁可少说，不许编圆。
禁元叙述（零容忍）：解说员在讲故事不在讲文件——「第X集」「画面里」「镜头」「素材」这类字眼一个不许有，观众不该意识到这是被剪出来的视频。
数字一律写中文（两千斤/八年/四十七块）：「2,000斤」是报表写法，配音念出来全毁。人称二选一并全篇统一，禁止中途切换。
"""
    + STYLE_CARD
)

# —— 全稿版（仅剧本链路：模型一次看到整条故事线时才成立）——
_FUND_FULL_ONLY = (
    """
【全稿手艺（仅剧本生效）】
写作姿势：先把约束放一边，像昨晚看了部特好看的电影、讲给没看过的朋友那样，把故事一口气讲下来——自然的详略、自然的钩子（可谁想到/他不知道的是）；讲完再对照上面那张卡与文风示范归位。你是讲故事的人，不是填格子的人。
吸引力（成稿唯一评分标准；人味与去AI味是及格线不是目标）：开场前 3 秒即全片最大反差（具体事实，禁空钩）；观众想知道「接下来会怎样」——每段结尾埋的问题必须是「接下来呢」；悬念切在情绪最高点，未完成的比完成的记得牢，善用半句钩把揭晓切在段边界；好奇缺口要具体（她为什么笑/钱去哪了），禁「后续更精彩」式空缺口；反差写进同一句（「全城最怂的会计，却是黑帮最怕的杀手」——一句内对撞狠十倍）；信息差是看家本领，每稿至少两处「观众知道角色不知道」或反之。
四种动作别混用：揭示（观众获得已有事实）、反转（让计划或关系位置失效）、回报（承诺的爽/甜/痛真正落到可感知结果）、钩子（新的危险或问题让状态继续运动）——只藏住一句话不是钩子，只亮出秘密而没人改变选择不是反转；有效揭示常由「旧事实的新关系」产生，不是突然抛一个更大的秘密。
架构与节奏：每段都要让信息、关系或风险真的变化，无变化的段删掉或合并；因果接缝必须能连读，禁止「怎么突然跳到这」；情绪用行动与选择呈现（「她把婚书扔进火里」胜过「她愤怒至极」）；同一事实全稿只讲一遍，后文再提必须带新的后果或升级（「一万三变成了五十一万」）；需要更多段就往下深挖没讲过的东西（对方什么反应/动作先后/数字怎么变/旁观者怎么说），把已讲过的换个说法再讲一遍就是水时长——真机复盘里这条是扣分最勤的一条。正文必须连续故事线（起因→升级→反转→高潮），禁跳跃拼凑；跳时间线给路标（八年前/与此同时）；主轴诉求是全稿唯一路标，每次跳集/换冲突第一句挂回它；最后一段停在最高潮的半拍上（剑落一半/身份将出口），禁把事件讲圆再接 CTA。交稿前默读一遍：删掉不承载动作或冲突的句子，检查有没有长出转写里没有的精确数字或记录链。
"""
)

# —— 逐槽版（仅填词链路：模型一次只见一个槽位，只放单槽能执行的）——
_FUND_SLOT_ONLY = (
    """
【逐槽手艺（仅填词生效）】
这一个槽位只干一件事：完成它的「要做的事」（契约），不得答非所问、别跑题。先像在饭桌上讲八卦那样把这句话说顺——短句、具体、有画面——再对齐槽位区间；念着拗口就重写，这段要被配音念出来，不是给人看的文章。相邻槽位要能连读成一条故事线，条尾可留半句钩勾住下一条（稀疏用，真人有偏科）；同一事实只在一个槽位讲完，别的槽位再提必须带新的后果或升级。
开场槽 3 秒内砸主角最反常的具体动作或处境概括（画面即此幕），禁从背景设定讲起、禁「他竟然…」式空钩；收尾/CTA 槽留缺口引导看全集，禁关注/点赞/二维码，谜底不给。
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


# 题材→表达重点（按短剧八题材归纳的表达侧重）：
# 引导而非限制——告诉模型这个题材该把镜头对准什么，不规定怎么写。
GENRE_EMPHASIS: dict[str, str] = {
    "复仇": "压抑与爆发的落差、证据与代价的升级、打脸的节奏",
    "甜宠": "心动细节、需求不对称与边界变化、暧昧升温的节拍",
    "悬疑": "谁能看见什么、证据可否解释、动机与误导",
    "逆袭": "处境落差、每一步翻盘的筹码、爽点的累积",
    "家庭伦理": "照护债、记忆版本之争、物件归属与关系裂痕",
    "都市": "现实处境、身份与阶层的碰撞、选择的代价",
    "古装": "礼法与身份的束缚、宅门/宫廷的权力关系、时代感细节",
}


def genre_emphasis_block(genre: str) -> str:
    """题材侧重行：已知题材给一行表达重点，未知题材给空串。"""
    text = GENRE_EMPHASIS.get(genre.strip(), "")
    return f"\n本题材表达重点：{text}" if text else ""



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
    genre: str = "",
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
        f"段数随剧情需要而定：每段只承载一个信息点，把关键冲突讲透、反转给足戏份。\n"
        f"绝不为了凑段数复述或编造，也绝不草草收尾；故事短就少写几段，把现有情节讲全即可。\n"
        f"{cross_block}\n"
        f"{angle_block}\n"
        f"台词转写：\n" + transcript_block
        + visual_suffix
        + genre_emphasis_block(genre)
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
    genre: str = "",
    trace_path: Path | None = None,
    prompts: dict[str, str] | None = None,
    min_segments: int | None = None,
    audit_hard: bool = False,
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
        genre=genre,
        prompts=prompts,
    )
    # 下限只兜底防退化，不按时长凑段（业主优先级：质量/完整度 > 时长）。
    # 调用方通常显式传入 min_segments；未传时退化为常量下限。
    floor = min_segments if min_segments is not None else _MIN_BODY_SEGMENTS
    attempts: list[dict[str, Any]] = []
    script: Script | None = None
    # 审查用转写（时间上界/互不重叠/编造专名的可验证基准）：直接取自输入摘录
    transcript = [
        {
            "episode": int(episode["number"]),
            "start": float(seg["start"]),
            "end": float(seg["end"]),
            "text": str(seg.get("text") or ""),
        }
        for episode in episode_inputs
        for seg in episode.get("segments") or []
    ]
    for attempt in range(_MAX_ATTEMPTS):
        # 重试注入格式强化：原样重问等于期待模型原样再犯
        ask = user_prompt + _FORMAT_REINFORCEMENT if attempt > 0 else user_prompt
        if attempts and attempts[-1].get("audit_quotes"):
            ask += (
                "\n\n上一稿违反了这些硬规则，重写时逐条避免：\n"
                + "\n".join(f"- {q}" for q in attempts[-1]["audit_quotes"])
            )
        elif attempts and attempts[-1].get("rejected"):
            tail_note = (
                f"上一次你只写了 {attempts[-1]['rejected']}。"
                "每段只讲一个信息点：宁可段数少，也不要复述或编造凑数；"
                "把关键冲突与反转讲全即可，故事短就按实际情节给段。"
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
        if script is not None and audit_hard:
            report = A.audit_script(script, transcript)
            hard_fails = [f for f in report.findings if f.severity == "hard" and not f.passed]
            soft_ids = [f.rule_id for f in report.findings if f.severity == "soft" and not f.passed]
            attempts[-1]["audit"] = {
                "hard": [f.rule_id for f in hard_fails],
                "soft": soft_ids,
            }
            if hard_fails:
                # 规则锚定重掷：把 prompt 原句喂回去，而不是让模型猜哪条没过
                attempts[-1]["audit_quotes"] = [f.prompt_quote for f in hard_fails if f.prompt_quote]
                script = None
        if script is not None:
            break
    dump_trace(
        trace_path,
        {"system": system, "user": user_prompt, "attempts": attempts},
    )
    if script is None:
        detail = "；".join(
            str(
                item.get("error")
                or (
                    f"硬规则未过：{'、'.join(item['audit']['hard'])}"
                    if item.get("audit", {}).get("hard")
                    else "清洗后片段不足"
                )
            )
            for item in attempts
        )
        raise ValueError(
            f"编剧未产出合法剧本（{len(attempts)} 次尝试）：{detail}"
            + (f"；完整往返见 {trace_path}" if trace_path else "")
        )
    return script


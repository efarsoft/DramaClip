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
# 题材口味由口味层（风格 directives）差异化，与此处不重叠。
FUNDAMENTALS = (
    "\n\n【解说基本功——逐条强制遵守】\n"
    "交付目标：这是导看全集的推广片，不是剧情摘要、不是观后感。"
    "看完的人必须还想点进去看原片；最大反转扣在全集里，本片只给一半答案。\n"
    "视角与语言：全程口语化说书人视角；短句为主，单句不超过 15 字；"
    "禁止书面腔、总结腔（如「本剧讲述了…」），禁止空洞形容词堆砌。"
    "人称二选一并全篇统一：第三人称说书人（默认），或主角第一人称"
    "（重生/穿越类代入感更强）；禁止中途切换视角。\n"
    "吸引力定律（成稿的唯一评分标准；人味与去AI味是及格线，不是目标）：\n"
    "· 观众点开解说不是想知道「发生了什么」，是想知道「接下来会怎样」——"
    "每段结尾埋的问题必须是「接下来呢」。写完每段问自己："
    "这句话让人不得不往下看吗？不会，就重写这一段的收尾。\n"
    "· 悬念切在情绪最高点：未完成的比完成的记得牢（蔡格尼克效应），"
    "答案在逻辑完结点给是白送，在心跳最快处切才是钩子。\n"
    "· 好奇缺口要具体：点名一个具体疑问（她为什么笑/钱去哪了/谁在装睡），"
    "禁止「后续更精彩」式空缺口——空缺口与没有缺口一样劝退。\n"
    "· 敢在低谷多待：受辱/压抑铺垫越长，打脸越爽——压缩铺垫等于自废爽点，"
    "爽点释放前的每一段都要把压抑叠厚一层再叠一层。\n"
    "· 反差写进同一句：「全城最怂的会计，却是黑帮最怕的杀手」——"
    "一句内对撞，比分两句各自陈述狠十倍。\n"
    "· 文画咬合（头部达人的刺激反射）：开场第一句必须点破开场画面里最炸的"
    "那个瞬间——画面在打脸，文案就点打脸；画面在爆身份，文案就点身份。"
    "文案与画面各说各话，再狠的钩子也只剩一半力道。\n"
    "· 信息差是解说员最大的武器：把「观众知道、角色不知道」说出来，"
    "观众就会替角色着急（她不知道，眼前这个送外卖的，就是救过她父亲的人）；"
    "或反过来「角色知道、观众不知道」吊着观众（他没说当年为什么走）。"
    "每稿至少两处信息差，这是电影解说的看家本领。\n"
    "人味纪律（去AI味是及格线不是加分项——人味丢了，钩子再狠也像机器营销）："
    "AI 味的本质是把话说得太满太齐——信息尽数调用、"
    "每段都总结收束、句式工整对称；真人讲八卦会偷懒、会跳、会有没说完的半句。"
    "写完默念一遍，凡是饭桌上讲八卦不会那么说的句子，重写。六条——"
    "① 禁书面连接词：然而/随即/顿时/缓缓/宛如/此刻，一个都不许出现；"
    "口语替代：结果/转头/当场/直接/好家伙/哪成想/怎料/殊不知/原来"
    "（后三个是反转专用信号词，每稿各至多一次）；"
    "② 禁工整对仗与排比：真人讲话没有对联，句长必须长短交错，连续两句等长即返工；"
    "唯一豁免：全稿收尾允许一句对偶（电影解说的对偶收尾），其余位置照禁；"
    "③ 每两三段拉一次观众：「你敢信？」「换你你咋办？」「注意，是亲儿子」——"
    "第二人称拉扯是完播钩子，一段至多一次，多了就油；"
    "④ 禁套话与先否后肯：不仅…而且…、不是…而是…、既…又…、从…到…、"
    "值得注意的是、不得不说、毫无疑问、堪称、就在这时——零容忍，"
    "转折只用「结果/谁知/哪成想」这种真人口癖；"
    "⑤ 禁把话说满：允许没说完的半句、允许省略主语，禁止每段结尾都收束总结；"
    "段落长短必须参差——高潮段放开写，过渡段一句话就够，"
    "全稿念下来该有喘息和突兀，不许四平八稳；"
    "⑥ 起手去重、动作优先：连续两段不得同一主语或同一句式起手"
    "（「他…」「她…」「这个男人…」必须轮换）；"
    "写具体动作不写概括——「她把婚书扔进火里」，不是「她做出了疯狂举动」，"
    "禁止「此举/该行为/这一幕背后」式名词化指代。\n"
    "架构纪律（词汇层只是下限：研究实测人把词句全改一遍，AI 破绽仍剩九成——"
    "真正的破绽在结构层）。五条——"
    "① 禁解释主题与动机：让事件自己说话，「原来善良才是她最大的武器」这类"
    "点题句一句不留；角色为什么这么做，观众自己品，你只给行为与后果；"
    "② 因果允许留白，但留的只是「动机」——事件与场景之间的接缝必须能连读："
    "上一段的果就是下一段的因，读者不该冒出「怎么突然跳到这」；"
    "真人说书甩结果不铺动机说明，那是 AI 最重的结构破绽；"
    "③ 情绪用行动与选择呈现：手抖/心碎/头皮发麻这类身体感觉模板全稿至多一处，"
    "「她把离婚协议拍在他脸上」胜过十句「她愤怒到了极点」；"
    "④ 真实锚点：每稿至少三个具体名词——年份/金额/物件/地点"
    "（账上只剩 47 块、2003 年的老楼、一枚假钻戒），具体名词比任何形容词可信；"
    "⑤ 预判观众：接住他们心里正在说的话（「你以为她认输了？先别急」）——"
    "观众意识是真人解说最硬的标志；"
    "⑥ 禁元叙述：解说员在讲故事，不在讲文件——「第X集」「画面里」「镜头」"
    "「素材」这类字眼零容忍，观众不该意识到这是一段被剪出来的视频；"
    "⑦ 数字一律写中文：两千斤、八年、四十七块——「2,000斤」是报表写法，"
    "配音念出来全毁。\n"
    "校准原则（比上面任何一条都重要）：禁令全员永远生效；"
    "动作类要求（情绪词/拉扯/锚点/预判）全稿稀疏轮换，一稿只挑 3~5 处下重手——"
    "每条规则都用满、每段都齐备，本身就是新的机器特征。真人是有偏科的。\n"
    "称谓即立场（行内铁律：称谓定了，观众立刻知道该恨谁该心疼谁）："
    "反派用标签化定性词（渣男/恶婆婆/赵家恶少），正面角色用中性称呼配同情式"
    "定语（被逼替嫁的女孩/隐忍八年的厨子）；关系一旦清楚就固定用通用代称"
    "（她哥/大舅哥/老爷子/那口锅），真名只留给「身份揭露」的高光时刻；"
    "全稿有名有姓的人物不超过三个，其余一律代称。"
    "同一人物全稿只用一个写法（师父/师傅二选一，写定就不换）；"
    "主轴与人物（观众是第一次听这个故事，一脸懵逼就是失职）："
    "开篇前两段必须钉死三件事——主角是谁（身份+名字绑定一次：萧焱，一个"
    "背着铁锅的厨子）、核心反常设定是什么（锅封着他的修为，卸锅即解封）、"
    "他要面对什么；此后每个名字**第一次出现必须挂身份标签**"
    "（赵狂——赵家少爷，垂陆知意美色；陆行简——她哥），"
    "且出场即速写：一句话钉死性格与立场（「她，为了妹妹可以豁出命」）；"
    "主角的核心诉求（复仇/守护/兑现承诺）是全稿唯一的路标——"
    "每次跳集、每换一个新冲突，第一句都挂回这个诉求，观众就不会跟丢；"
    "跳时间线必须给路标（「八年前」「与此同时」），插叙可以、裸跳不行。\n"
    "结构与节奏：第一段解说必须在前 3 秒抛出全片最大的悬念或反差——"
    "必须是具体事实（身份/生死/数字/当众打脸），禁止「他竟然…」式空钩。"
    "每段只讲一个信息点；段间递进靠内容本身（结果反转/行动升级），"
    "不要依赖固定衔接词——「更狠的是」这类起手全片至多一次。"
    "给 TTS 留表演空间：句子长短交错，关键揭晓前用短句或省略号制造停顿，"
    "配音的悬念感一半来自标点。"
    "正文必须是一条连续故事线：背景起因→冲突升级→高潮反转，后一段承接前一段，"
    "禁止跳跃拼凑不相关片段。善用「半句钩」：把关键揭晓切在段落边界，答案留在下一段开头。"
    "每段结尾做两件事——**收口 + 埋线**：把这段的冲突交代干净，再用一句决绝态度"
    "或悬念勾住下一段（「我们之间没完」「她意识到汤不对劲」）；"
    "爆款降热度句式参考：『下一秒，全场都安静了』『这里他还没意识到事情的严重性』"
    "（句式供参考，禁止照抄原句）；"
    "跨集、跨场景的段尾尤其如此——观众带着预期进下一段，选集再跳也不觉得跳。\n"
    "句式必须混排：「谁+动作：台词」的段落**连续不许超过两段**——"
    "叙述句、引语句、解说员自己的点评（「注意，锅还在他背上」）要轮着来；"
    "三十格连环画没有旁白，观众一脸懵逼。"
    "紧凑是指不灌水，不是砍完整度：冲突链条没铺开就收尾才是失败，"
    "片长服从故事——宁可有血有肉地写到十几分钟，不要干瘪压缩，也不要为空时长注水。"
    "正文最后一段必须停在**最高潮的半拍上**（剑落到一半/身份即将出口的瞬间），"
    "禁止把事件讲圆了再接 CTA——高潮处戛然而止，才是转化率最高的切点。\n"
    "选段纪律：相邻解说尽量压在同集、时间相接或因果相接的画面上；"
    "禁止无因果跳切拼盘。换场可以，跳切堆砌不行。\n"
    "内容纪律：所有情节、细节、台词必须来自转写内容，禁止编造转写外的事件或设定；"
    "优先引用最有画面感的具体细节（动作/冲突/原话），拒绝抽象概括。"
    "引用是盐不是主菜：每段至多一处原话引用，全稿带引用的段不超过四成——"
    "挑最疼的那一句，其余台词一律**转述立场**不引原声"
    "（「他当众质问她为什么背叛」，而不是背出他骂的原话），"
    "禁止把台词一句句罗列成报菜名"
    "（「他先回X，转头喊Y，再补一句Z」这种转述串，是把分镜脚本当解说）。\n"
    "悬念管理：全片最大的反转不得提前剧透——关键信息延后到结尾前揭晓。"
    "观众想知道答案，但你每次只给一半：给足情绪，扣住关键信息。"
    "三幕收尾允许一句解说员自己的立场或感慨（一句封顶，放在 CTA 前）——"
    "收尾观点是电影解说的第三幕，有它片子才立得住。"
    "结尾必须留「想知道结局」的缺口，CTA 只准引导去看全集（可带剧名），"
    "禁止空喊关注、点赞、收藏、二维码。"
)

_STRUCTURE_PROMPT = (
    "你是短剧推广解说编剧。根据给定的带时间戳台词转写，"
    "输出一条推广解说视频的剧本 JSON，格式："
    '{"hook": "开场钩子(1-2句)", "segments": [{"episode": 集号整数, "start": 数字秒,'
    ' "end": 数字秒, "text": "该片段解说文案"}], "cta": "结尾引导语(1句)"}。'
    "要求：1) 每个片段都必须带 episode，一个都不能漏；start/end 是该集内的相对秒，"
    "取自转写台词的时间区间，不得超过该集「本集台词截至」给出的上界；"
    "同一集内按时间递增且互不重叠：下一段的 start 不得早于前一段的 end；"
    "相邻片段优先同集连续时段；换集优先取相邻集（第1集接第2集），大跨度跳集只许跳往确有关键爆点的一集，且前集段尾必须把跨集因果说破（前集埋线→后集爆发），禁止无因果跳切；"
    "1.5) hook 必须含一个具体反差事实（身份/生死/数字），禁止「他竟然…」式空泛悬念；"
    "1.6) 开场禁选性暗示/胁迫/粗俗胁迫类台词做第一印象（平台审核红线）——"
    "爆点选冲突最烈的那句，不是最脏的那句；"
    "台词前的[角色X]是声纹聚类标签，同一标签就是同一个人：写文案时把它换成你从"
    "称呼与剧情推断出的真名（如 小明/姐姐/总栽），推断不出再保留原标签；"
    "关键台词可原样引用（加引号）增强真实感；善用具体数字（年份/金额/集数）制造冲击；"
            "cta 必须是三段式转化引导：剧情悬念半句（承接正文最后的缺口，不剧透最大反转）"
            "+ 行动指令「点击左下角」+ 观看引导（「免费观看全集」或「立即观看全集」，可带剧名）。"
            "悬念半句可升级为「代价式」：暗示现在退出的损失（不看完，你今晚都会惦记她那句话）"
            "——诱惑力来自损失感，但禁止编造不存在的情节来夸大。"
            "例：『吊了八年的婚约，竟是她复仇的第一步——点击左下角，免费观看全集。』"
            "例：『她想低调，可龙魂不许——点击左下角，立即观看《剧名》全集。』"
            "例：『她接下来那句话，会让全场的酒都醒——点击左下角，免费观看全集。』"
    "禁止空喊关注/点赞/收藏，禁止只写「去看全集」这类没有悬念钩子的光秃引导，"
    "禁止剧透最大反转。"
    "2) 正文 12-28 段：把冲突链条完整铺开（起因→多轮升级→连环反转→高潮），"
    "段数不够就是没讲透；冲突没讲完写到上限，禁止为赶时长砍高潮；"
    "每段文案不超过 60 字；"
            "文案要像真人解说员开口说话：相邻两段禁止同一提示语起手"
            "（「更狠的是/万万没想到/谁能想到」这类起手式全稿至多出现一次），"
            "六成上下段落带情绪词（怒/恨/慌/疼/疯）或人物原话引用，"
            "其余冷静叙述——密度均匀反而假；每段原话引用至多一处；数字一律写中文；"
            "多用短句和具体动作，拒绝概括性陈述与排比复读；"
            "交稿前自查：全稿「不是…而是…」出现次数必须是零，"
            "相邻两段起手不得同主语，段落长短必须参差；"
    "3) 覆盖剧情完整钩子-冲突-反转弧线，看完必须还想点进去看原片；"
    "4) 只输出 JSON，不要多余文字。"
)


def fundamentals_layer(prompts: dict[str, str] | None = None) -> str:
    """基本功层文本（编剧与逐槽填词共用这一张卡）。"""
    return (prompts or {}).get("prompt.scriptwriter_fundamentals") or FUNDAMENTALS


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
    user_prompt = (
        f"项目：{project_name}\n"
        f"按 system 给定的段数区间给够段数，把冲突讲透、反转给足戏份。\n"
        f"铺垫果断压缩，绝不为赶时长删掉关键冲突或草草收尾。\n"
        f"{cross_block}\n"
        f"{angle_block}\n"
        f"台词转写：\n" + transcript_block
        + f"{style_block}"
    )
    system = system_prompt(prompts)
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
            raw = llm.chat_json(system, ask)
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


"""BGM 选曲规则：纯函数，零 IO 零 DB——输入是方案 + 曲目清单，输出是决定。

三条规则（C 项 v1「一片一床」口径）：

1. `dominant_emotion(plan)`：全片段情绪标签取众数——不做逐段换曲，3 分钟片
   切 5 首音乐是灾难；情绪床铺满全片，逐段微调留给以后有听感数据再谈。
2. `pick_track(tracks, emotion)`：该情绪曲目里选 bpm 最接近目标档位的；
   无曲回退 default 情绪；再无 → None（**无曲可用是合法态**，渲染层收到
   None 就按现状出片，绝不 raise）。
3. `should_add_bgm(mode)`：raw_clip / dialogue_narration 默认关——源片自带
   BGM 且原声是主体，叠两层音乐=糊；其余七模式解说压掉了源音乐（原声
   10%/8% 衬底），正是「干」的来源，需要补床。
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence

from dramaclip.engines.bgm.library import BgmTrack
from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.subtitle.emotion_matcher import match_emotion

# 平局 severity 序：钩子/悬念主导是转化线口径（信息流前 3 秒靠 suspense 拉停留，
# 短剧爽点靠 anger/triumph），default 垫底——平局时宁可要情绪也不铺「没情绪」。
_SEVERITY_ORDER: tuple[str, ...] = ("suspense", "anger", "triumph", "sadness", "default")

# 情绪 → 目标 bpm 档位（v1 粗档，依据：影视配乐惯例——悬疑/紧张用快拍推进心跳感，
# 悲情用慢拍留白，热血居中偏快；default 是中性叙事床，取中速）。
# v2 若做 BGM 拍点对齐 B9 节拍吸附，这些档位会细化，届时以听感实测为准。
_TARGET_BPM: dict[str, float] = {
    "suspense": 110.0,
    "anger": 120.0,
    "triumph": 100.0,
    "sadness": 70.0,
    "default": 90.0,
}

# 源片自带 BGM 且原声为主体的模式：不叠第二层音乐（产品口径，见模块 docstring 3）
_BGM_OFF_MODES = frozenset({"raw_clip", "dialogue_narration"})


def should_add_bgm(mode: str) -> bool:
    """该模式的成片要不要铺 BGM 床（v1 产品口径，settings 全局开关是接线层的事）。"""
    return mode not in _BGM_OFF_MODES


def dominant_emotion(plan: PlanData) -> str:
    """全片主导情绪：段情绪标签的众数；平局按 severity 序取先；空时间轴 → default。

    emotion_label 为空的段按 `match_emotion(subtitle_text)` 归一——与
    transitions._stamp_emotions 同口径（直接调用，不复制它的逻辑）：标签缺失
    时字幕文本就是最后的情绪信号，两条路径必须给出同一个键。
    """
    if not plan.timeline:
        return "default"
    counter = Counter(
        match_emotion(segment.subtitle_text or "", segment.emotion_label)
        for segment in plan.timeline
    )
    top = max(counter.values())
    tied = {emotion for emotion, count in counter.items() if count == top}
    for emotion in _SEVERITY_ORDER:
        if emotion in tied:
            return emotion
    return "default"  # 理论不可达（counter 的键都出自 match_emotion ⊂ _SEVERITY_ORDER）


def pick_track(
    tracks: Sequence[BgmTrack], emotion: str
) -> BgmTrack | None:
    """选曲：该情绪里 bpm 最接近目标档位的；无 bpm 沉底；无曲回退 default；再无 → None。

    确定性：bpm 距离平局按文件名排序（曲库扫描本身按目录序，这里再排一次
    保证同输入同输出——测试与真机必须可复现）。
    """
    by_emotion = [track for track in tracks if track.emotion == emotion]
    if not by_emotion and emotion != "default":
        by_emotion = [track for track in tracks if track.emotion == "default"]
    if not by_emotion:
        return None
    target = _TARGET_BPM.get(emotion, _TARGET_BPM["default"])
    measured = [track for track in by_emotion if track.bpm is not None]
    if measured:
        return min(
            measured, key=lambda t: (abs(float(t.bpm) - target), t.file.name)  # type: ignore[arg-type]
        )
    # 全都测不出 bpm（librosa 缺失的机器）：按文件名确定性取第一首，不炸不空
    return min(by_emotion, key=lambda t: t.file.name)


def select_bgm(plan: PlanData, tracks: Iterable[BgmTrack]) -> BgmTrack | None:
    """端到端选曲（接线层唯一入口）：模式门禁 → 主导情绪 → 选曲。

    返回 None 的所有情形都是合法态（模式不该铺 / 库空 / 情绪无曲且 default 也无），
    渲染层收到 None 必须走现状路径——「无曲可用 = 现状逐字节一致」是硬验收。
    """
    if not should_add_bgm(plan.mode):
        return None
    return pick_track(list(tracks), dominant_emotion(plan))

"""全片解说模式（原案 6.5）：全程旁白覆盖（"X 分钟看完"），原声压低至背景。

编排只产出画面结构与旁白槽位，文案一律由 narration.copywriter 生成（无模板兜底）；
旁白时长在 TTS 合成后回填（机制同 intro/cross），段长随旁白实际时长伸缩。
"""

from __future__ import annotations

from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.semantic.models import ConflictScore

_MAX_SCENES = 8           # 旁白段数上限（TTS 次数约束）
_FULL_SCENE_S = 10.0      # 单场景基准时长（TTS 回填前）


def _slot_role(index: int, count: int, score: int) -> str:
    """按场景在叙事弧中的位置给编剧下达职责指令（位置是真信息，模板把它丢掉了）。"""
    if index == 0:
        return "开篇：一句话把人推到冲突跟前，交代处境但不解释设定"
    if index == count - 1:
        return "收尾：留结局缺口 + 一句点击引导"
    if score >= 85:
        return "高潮：只讲这一幕最狠的那个信息点"
    return "推进：承接上一幕，说清冲突又升级了什么"


def build_full(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
) -> PlanData:
    """全片解说编排：场景按时间线全程覆盖，全部原声压低（ducked）。"""
    ranked = sorted(scenes, key=lambda s: -s.score)[:_MAX_SCENES]
    picked = sorted(ranked, key=lambda s: s.start)
    if not picked:
        return PlanData(mode="full_narration", strategy=strategy)

    count = len(picked)
    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, scene in enumerate(picked):
        slot_id = f"full-{index + 1}"
        window = (scene.start, round(min(scene.start + _FULL_SCENE_S, scene.end), 3))
        timeline.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(scene.start, 3),
                end=window[1],
                audio="ducked",
                narration_id=slot_id,
            )
        )
        texts.append(
            NarrationText(id=slot_id, slot=_slot_role(index, count, scene.score), window=window)
        )
    return PlanData(
        mode="full_narration", timeline=timeline, narration_texts=texts, strategy=strategy
    )

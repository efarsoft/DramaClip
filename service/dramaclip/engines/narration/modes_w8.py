"""全片解说模式（原案 6.5）：全程旁白覆盖（"X 分钟看完"），原声压低至背景。

每个入选场景配一段旁白（模板降级，LLM 精修后替换）；
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


def narration_texts_for(
    scenes: list[ConflictScore],
    project_name: str,
    genre: str | None,
) -> list[NarrationText]:
    """按场景位置生成模板旁白（开头/推进/高潮/收尾）。"""
    genre_part = f"一个关于{genre}的故事" if genre else "一个让人上头的故事"
    texts: list[str] = []
    count = len(scenes)
    for index, scene in enumerate(scenes):
        if index == 0:
            texts.append(f"{project_name}，{genre_part}。女主一出场就被逼到了绝境。")
        elif index == count - 1:
            texts.append("这一刻，所有的委屈都有了答案。想看全集，点下方。")
        elif scene.score >= 85:
            texts.append("冲突直接拉满，谁都拦不住。")
        elif index % 2 == 1:
            texts.append("可她没有退路，只能硬着头皮往前走。")
        else:
            texts.append("然而更大的麻烦，还在后面。")
    return [NarrationText(id=f"full-{i + 1}", text=text) for i, text in enumerate(texts)]


def build_full(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
    project_name: str,
    genre: str | None = None,
) -> PlanData:
    """全片解说编排：场景按时间线全程覆盖，全部原声压低（ducked）。"""
    ranked = sorted(scenes, key=lambda s: -s.score)[:_MAX_SCENES]
    picked = sorted(ranked, key=lambda s: s.start)
    if not picked:
        return PlanData(mode="full_narration", strategy=strategy)

    texts = narration_texts_for(picked, project_name, genre)
    timeline = [
        TimelineSegment(
            episode_id=episode_id,
            start=round(scene.start, 3),
            end=round(min(scene.start + _FULL_SCENE_S, scene.end), 3),
            audio="ducked",
        )
        for scene in picked
    ]
    return PlanData(
        mode="full_narration",
        timeline=timeline,
        narration_texts=texts,
        strategy=strategy,
    )

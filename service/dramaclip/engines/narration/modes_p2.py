"""P2 模式编排（原案 6.10/6.11）：双人对谈式与角色内心独白式。

两模式都基于「全程 TTS 旁白」骨架（同 full），差异在音色与文案视角：
- dual_host_chat：双音色 A/B 交替对谈（主持人 x 嘉宾），原声压低；
- inner_monologue：单一角色第一人称内心 OS，情绪更内收。
配音用 edge 多音色（zh-CN-YunxiNeural 男 / zh-CN-XiaoyiNeural 女）；
kokoro/IndexTTS-2 本地引擎接入后仅需替换 voice 参数与引擎工厂。
"""

from __future__ import annotations

from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.semantic.models import ConflictScore

_VOICE_A = "zh-CN-YunxiNeural"  # 主持人（男）
_VOICE_B = "zh-CN-XiaoyiNeural"  # 嘉宾（女）
_SCENE_S = 10.0
_MAX_SCENES = 8


def _pick(scenes: list[ConflictScore]) -> list[ConflictScore]:
    ranked = sorted(scenes, key=lambda s: -s.score)[:_MAX_SCENES]
    return sorted(ranked, key=lambda s: s.start)


def build_dual_host(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
    project_name: str,
) -> PlanData:
    """双人对谈（原案 6.10）：A 抛话题、B 推剧情，交替对谈 + 原声压低。"""
    picked = _pick(scenes)
    if not picked:
        return PlanData(mode="dual_host_chat", strategy=strategy)

    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    for index, scene in enumerate(picked):
        speaker_voice = _VOICE_A if index % 2 == 0 else _VOICE_B
        if index == 0:
            line = f"你们看过最爽的复仇剧吗？{project_name}直接杀疯了。"
        elif index == len(picked) - 1:
            line = f"所以我说，{project_name}的结局才是真正的王炸。想看全集点下方。"
        elif index % 2 == 1:
            line = "我跟你说，这段看得我血压都上来了。"
        else:
            line = "更狠的还在后面，接着看。"
        timeline.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(scene.start, 3),
                end=round(min(scene.start + _SCENE_S, scene.end), 3),
                audio="narration",
            )
        )
        texts.append(
            NarrationText(id=f"dual-{index + 1}", text=line, voice=speaker_voice)
        )
    return PlanData(
        mode="dual_host_chat", timeline=timeline, narration_texts=texts, strategy=strategy
    )


def build_monologue(
    episode_id: str,
    scenes: list[ConflictScore],
    strategy: StrategySpec,
    project_name: str,
) -> PlanData:
    """角色内心独白（原案 6.11）：第一人称 OS 贯穿，情绪内收。"""
    picked = _pick(scenes)
    if not picked:
        return PlanData(mode="inner_monologue", strategy=strategy)

    timeline: list[TimelineSegment] = []
    texts: list[NarrationText] = []
    count = len(picked)
    for index, scene in enumerate(picked):
        if index == 0:
            line = f"嫁进{project_name}的这个家三年，我以为忍让就会被接纳。"
        elif index == count - 1:
            line = "该还的，一分都不能少。想看我怎么讨回来，点下方。"
        elif scene.score >= 85:
            line = "那一刻我明白了，退让换不来尊重。"
        else:
            line = "我以为只要再忍一忍，一切都会过去。"
        timeline.append(
            TimelineSegment(
                episode_id=episode_id,
                start=round(scene.start, 3),
                end=round(min(scene.start + _SCENE_S, scene.end), 3),
                audio="narration",
            )
        )
        texts.append(NarrationText(id=f"mono-{index + 1}", text=line, voice=_VOICE_A))
    return PlanData(
        mode="inner_monologue", timeline=timeline, narration_texts=texts, strategy=strategy
    )

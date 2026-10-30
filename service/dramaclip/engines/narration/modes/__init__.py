"""九种解说模式的编排器（原案第六章）。W4：raw_clip + intro_narration。
"""

from __future__ import annotations

import re

from dramaclip.engines.narration.casting import (
    EpisodeScene,
    MaterialByEpisode,
    episode_order,
    has_dialogue,
    scene_visual_score,
    score_order,
)
from dramaclip.engines.narration.models import (
    NarrationText,
    PlanData,
    StrategySpec,
    TimelineSegment,
)
from dramaclip.engines.semantic.models import HighlightSegment

# raw_clip 筛选（原案 6.7）：冲突≥70、单场景 3-25s
RAW_CLIP_MIN_SCORE = 70
_RAW_CLIP_MIN_S = 3.0
_RAW_CLIP_MAX_S = 25.0
_RAW_CLIP_FALLBACK_COUNT = 6  # 门槛放宽兜底的条数上限（不再借 len(highlights) 张冠李戴）
_INTRO_MAX_S = 30.0  # 片头段保守时长（TTS 实际时长在导出时回填）
_INTRO_SLOT_ID = "intro-1"
_CTA_SLOT_ID = "cta-1"
_CTA_FALLBACK_S = 2.0


_HIGHLIGHT_CLIP_S = 5.0   # 高光混剪的单条时长（真机参考：13×5s ≈ 65s 预告）
_HIGHLIGHT_MAX_CLIPS = 15  # 条数上限：时长让位≠无限堆料，预告形态 75s 内最猛
_ADJACENT_GAP_S = 1.5  # 邻接合并阈值：同集间隙 ≤1.5s（基本贴合）才合并；间隙大的各自成段保留节奏
# 对拍依据（2026-10-23，dev 活库 8 条 ready 方案 43 处同集相邻间隙）：
# 1.0-1.5s「三线不一致区」仅 1 处（2.3%）——邻接合并先吃掉 ≤1.5s 的间隙，
# 三线（1.5/1.0/1.0）不齐无实际危害，维持不统一。


def _merge_adjacent(ordered: list[EpisodeScene]) -> list[EpisodeScene]:
    """邻接合并：同集且首尾间隙 ≤`_ADJACENT_GAP_S` 的选中场景合成一个连续块。

    纯冲突分排序会让时间轴在高分场景之间反复横跳（真机 raw_clip 20 段 11 跳场、
    高光混剪 6 处）——相邻的高分场景本就是连续剧情，合并成块播放，块内不再
    跳场，叙事完整度优先于碎片化快切。
    """
    if not ordered:
        return ordered
    merged: list[EpisodeScene] = [ordered[0]]
    for scene in ordered[1:]:
        last = merged[-1]
        if (
            scene.episode_id == last.episode_id
            and 0.0 <= scene.start - last.end <= _ADJACENT_GAP_S
        ):
            merged[-1] = EpisodeScene(
                episode_id=last.episode_id,
                number=last.number,
                scene_index=last.scene_index,
                start=last.start,
                end=scene.end,
                score=max(last.score, scene.score),
            )
        else:
            merged.append(scene)
    return merged


def build_highlight_cut(
    scenes: list[EpisodeScene],
    strategy: StrategySpec,
    material: MaterialByEpisode | None = None,
) -> PlanData:
    """高光混剪（预告形态）：全剧最高冲突场景 × 5 秒快切 + 配乐床，零解说。

    参考真机混剪流程：选段=冲突分头部、时长=统一 5 秒快切、顺序=时间序
    （预告叙事），冲突分最高的场景前置做开场；零 TTS 零字幕加工，
    「配乐床」目前是占位描述：engines/bgm/selector.py 尚未接线（生产零调用），
    接线前成片没有 BGM——W7 落地时替换此句。
    邻接合并不适用于此模式：快切本身就是节奏，碎片化是设计意图而非缺陷。
    `material` 可选：给到时过滤哑段（原声快切里混 5 秒无声动作戏=白剪）、
    窗口边界吸附台词句边界（与 raw_clip 同款纪律，2026-10-27 审计立案）。
    """
    if not scenes:
        return PlanData(mode="highlight_cut", strategy=strategy)
    ranked = sorted(scenes, key=score_order)[:_HIGHLIGHT_MAX_CLIPS]
    if material is not None:
        voiced = [scene for scene in ranked if has_dialogue(material, scene)]
        if len(voiced) >= 3:
            ranked = voiced
    ordered = sorted(ranked, key=episode_order)
    best = max(ordered, key=lambda s: s.score)
    if ordered[0] is not best:
        ordered.remove(best)
        ordered.insert(0, best)
    timeline: list[TimelineSegment] = []
    for scene in ordered:
        span = scene.end - scene.start
        if span <= 0:
            continue
        if span <= _HIGHLIGHT_CLIP_S:
            start, end = scene.start, scene.end
        else:
            mid = (scene.start + scene.end) / 2
            start, end = mid - _HIGHLIGHT_CLIP_S / 2, mid + _HIGHLIGHT_CLIP_S / 2
        timeline.append(
            TimelineSegment(
                episode_id=scene.episode_id,
                start=round(start, 3),
                end=round(end, 3),
                audio="original",
            )
        )
    timeline = _snap_windows_to_dialogue(timeline, material)
    timeline = extend_openings_over_connectives(timeline, material)
    return PlanData(mode="highlight_cut", timeline=timeline, strategy=strategy)


def build_raw_clip(
    scenes: list[EpisodeScene],
    highlights: list[HighlightSegment],
    strategy: StrategySpec,
    material: MaterialByEpisode | None = None,
) -> PlanData:
    """纯原片剪辑编排：有台词在场的高冲突场景，纯时间序连播。零加工（不遮罩）。

    预告式开场（最高冲突前置）曾是设计，真机 2026-10-20 被业主否掉：无解说模式
    里一段 3.6 秒的异集无台词动作孤插当开场，观众只会莫名其妙——预告式开场
    需要旁白兜底（片头解说有），本模式的卖点是「原声台词高光合集」，要的是连贯。
    因此：①不前置；②候选必须有台词在场（material 可注入时过滤哑段，过滤后
    不足三条或缺该集原料时回退，可用性优先）。
    """
    if not scenes:
        return PlanData(mode="raw_clip", strategy=strategy)
    candidates = [
        scene
        for scene in scenes
        if scene.score >= RAW_CLIP_MIN_SCORE
        and _RAW_CLIP_MIN_S <= scene.end - scene.start <= _RAW_CLIP_MAX_S
    ]
    if material is not None:
        voiced = [scene for scene in candidates if has_dialogue(material, scene)]
        if len(voiced) >= 3:
            candidates = voiced
    # 分数不足时放宽到全部场景（按冲突分取头部，保证可用性）；**台词过滤不放宽**：
    # 「原声台词高光合集」混进哑段比少一段更伤（真机 2026-10-20 教训）。条数用
    # 常量不借 len(highlights)——那是另一个模式的输入量，张冠李戴（2026-10-27 审计）。
    if len(candidates) < 3:
        ranked = sorted(scenes, key=score_order)
        if material is not None:
            ranked = [scene for scene in ranked if has_dialogue(material, scene)]
        candidates = ranked[:_RAW_CLIP_FALLBACK_COUNT] or ranked

    ordered = sorted(candidates, key=episode_order)
    # 邻接合并：相邻高分场景合成连续块播放，减少时间轴反复横跳
    ordered = _merge_adjacent(ordered)
    timeline = _fit_duration(ordered, strategy)
    timeline = _snap_windows_to_dialogue(timeline, material)
    timeline = extend_openings_over_connectives(timeline, material)
    timeline = extend_endings_over_dialogue_chains(timeline, material)
    timeline = _retract_unanswered_questions(timeline, material)
    return PlanData(mode="raw_clip", timeline=timeline, strategy=strategy)


_DIALOGUE_SNAP_EPS_S = 0.35  # 边界离句边界比这近就不算切句（字级时间戳的正常抖动）
_DIALOGUE_SNAP_MIN_KEEP_S = 2.0  # 让位吸附后窗口至少保住的时长（防 1 秒碎窗）


def _snap_windows_to_dialogue(
    timeline: list[TimelineSegment],
    material: MaterialByEpisode | None,
) -> list[TimelineSegment]:
    """原声窗边界吸附台词句边界：剪口不落在句子中间（业主 2026-10-27 实测立案）。

    raw_clip 的卖点是「原声台词高光合集」，窗口止在句中=话说到一半跳场（真机
    2026-10-27 成品 3a83fc98：14 窗 7 窗切句，开头 3.2s 窗拦腰切断一句台词）。
    止点切在句中：优先收进整句（延到句尾），会撞下一窗起点就退到句前；起点切在
    句中：优先退到句首，会撞上一窗止点就进到句后。两侧都让不动时保持原值——
    吸附是增强不是义务；无原料（material 缺该集）原样通过。
    """
    if material is None or not timeline:
        return timeline
    # 邻窗索引只收**原声窗**：旁白占位窗渲染期整体重铺，不构成原声窗的让位边界
    # （cross 桥段占位在空隙里，会假栅栏挡住「收进整句」——真机对拍抓回）
    by_episode: dict[str, list[int]] = {}
    for index, segment in enumerate(timeline):
        if (
            segment.audio == "original"
            and str(segment.narration_id or "") != "cta-1"
        ):
            by_episode.setdefault(segment.episode_id, []).append(index)
    updated = list(timeline)
    eps = _DIALOGUE_SNAP_EPS_S
    keep = _DIALOGUE_SNAP_MIN_KEEP_S

    def _to_silence(boundary: float, silences: tuple[tuple[float, float], ...]) -> float:
        """句界精修：±0.35s 内有声学静音区间就吸到区间中点（剪口落在真实停顿上）。
        无静音图/无命中原值返回——声学精修是增强不是义务。"""
        for g0, g1 in silences:
            if g0 - eps <= boundary <= g1 + eps:
                return (g0 + g1) / 2
        return boundary

    for indices in by_episode.values():
        for position, index in enumerate(indices):
            segment = updated[index]
            if segment.audio != "original" or str(segment.narration_id or "") == "cta-1":
                continue  # 旁白占位窗（渲染期实测重排）与金句流重播卡（设计性重叠）不吸
            entry = material.get(segment.episode_id)
            if entry is None:
                continue
            # 吸附循环取「首个满足条件」的句子，隐含台词升序前提：库内 JSON 无
            # 排序契约（手工改库/上游变化都可能乱序），这里排序一次保住前提
            spans = sorted(
                ((seg.start, seg.end) for seg in entry.asr), key=lambda pair: pair[0]
            )
            prev_end = (
                updated[indices[position - 1]].end if position > 0 else None
            )
            next_start = (
                updated[indices[position + 1]].start
                if position + 1 < len(indices)
                else None
            )
            start, end = segment.start, segment.end
            for s0, s1 in spans:
                if s0 + eps < end < s1 - eps:  # 止点切在句中
                    if next_start is None or s1 <= next_start:
                        end = s1  # 收进整句：把话说完再跳
                    elif s0 >= start + keep:
                        end = s0  # 撞下一窗：退到句前
                    break
            for s0, s1 in spans:
                if s0 + eps < start < s1 - eps:  # 起点切在句中
                    if (prev_end is None or s0 >= prev_end) and s0 <= end - keep:
                        start = s0  # 退到句首：从话头听起
                    elif s1 <= end - keep:
                        start = s1  # 撞上一窗：进到句后
                    break
            # 声学精修（T1 质批）：句界 ±0.35s 内有真实静音区间就吸到区间中点，
            # 精修不得越邻窗栅栏；相向挤压夹没窗则整体弃精修保窗。
            refined_start = _to_silence(start, entry.silences)
            refined_end = _to_silence(end, entry.silences)
            if prev_end is not None and refined_start < prev_end:
                refined_start = start
            if next_start is not None and refined_end > next_start:
                refined_end = end
            if refined_start >= refined_end - eps:
                refined_start, refined_end = segment.start, segment.end
            start, end = refined_start, refined_end
            if (start, end) != (segment.start, segment.end):
                updated[index] = segment.model_copy(
                    update={"start": round(start, 3), "end": round(end, 3)}
                )
    return updated


def build_intro(
    body_scenes: list[EpisodeScene],
    strategy: StrategySpec,
    material: MaterialByEpisode | None = None,
) -> PlanData:
    """片头解说编排（原案 6.4）：引子旁白段（画面为**最高冲突镜**）+ 正片高光（原声）。

    首帧选镜：信息流里用户先看到画面，片头旁白讲「最大冲突」而画面却是时间序的
    平淡开场就是音画各说各话（B 项）。故把冲突最高镜前置做首帧，其余按
    `episode_order` 时间序——这是「预告式开场」（先闪高潮、再回叙事），旁白兜底
    使其成立（raw_clip 无解说已取消前置，2026-10-20）。前置用 `is` 身份比较不用
    `scene_index`：scene_index 只在一集内唯一，跨集时按 index 判会误认「开场已是
    最高冲突」而不前置。
    全等分（max 取首个）时不前置，保持原时间序。
    `material` 可选：给到时正片哑段过滤（片头 3 秒后的第一段正片是观感最贵的位置，
    混进无声动作戏代价最高）+ 原声窗台词句边界吸附（与 raw_clip 同款纪律）。
    """
    ordered = sorted(body_scenes, key=episode_order)
    if material is not None:
        voiced = [scene for scene in ordered if has_dialogue(material, scene)]
        if len(voiced) >= 2:
            ordered = voiced
    if ordered:
        # 开场选段双因子（2026-10-28 VL 主线）：台词冲突 × 视觉冲击力——
        # 「画面平淡但台词猛」的场景不再霸占片头黄金 3 秒。无画面数据时
        # scene_visual_score 归 5.0（中性），退化为纯冲突分排序。
        best = max(
            ordered, key=lambda s: s.score * scene_visual_score(material, s)
        )
        if ordered[0] is not best:
            ordered.remove(best)
            ordered.insert(0, best)
    timeline = _fit_duration(ordered, strategy, intro_first=True)
    if not timeline:
        return PlanData(mode="intro_narration", timeline=timeline, strategy=strategy)
    timeline = _snap_windows_to_dialogue(timeline, material)
    timeline = extend_openings_over_connectives(timeline, material)
    timeline[0] = timeline[0].model_copy(update={"narration_id": _INTRO_SLOT_ID})
    last = timeline[-1]
    # CTA 非重叠接在末场景之后（2026-10-27 审计 C8）：旧占位「重叠末场景尾部 2s」
    # 会被渲染期游标修补顶到场景后（floor=末段 end），「压尾帧」语义必然落空——
    # 不如编排期就按非重叠写，渲染期旁白消化链（头部扩展/尾部收口/弃段留痕）全适配。
    timeline.append(
        TimelineSegment(
            episode_id=last.episode_id,
            start=round(last.end, 3),
            end=round(last.end + _CTA_FALLBACK_S, 3),
            audio="narration",
            narration_id=_CTA_SLOT_ID,
        )
    )
    return PlanData(
        mode="intro_narration",
        timeline=timeline,
        narration_texts=[
            NarrationText(
                id=_INTRO_SLOT_ID,
                # 行为指令句式来自平台高赞实证：预设观看反应比复述剧情更留人
                brief="片头钩子：两三句把最大冲突抛出来，不要复述剧情梗概；"
                "可用行为指令句式预设观看反应（「看这集的时候小点声笑，容易梦醒」式）",
            ),
            NarrationText(
                id=_CTA_SLOT_ID,
                brief="收尾引导：一句，留缺口并指向看全集，不超过 15 字，禁止关注/点赞",
            ),
        ],
        strategy=strategy,
    )


def _fit_duration(
    ordered: list[EpisodeScene],
    strategy: StrategySpec,
    *,
    intro_first: bool = False,
) -> list[TimelineSegment]:
    """保留编排器已选出的场景；片长服从故事，不再按 max_duration 截断。

    片头解说仍把首段画面钳到 `_INTRO_MAX_S`（TTS 槽位估计，不是成片门禁）。
    """
    del strategy  # 软参考，编排器挑选场景时可读；这里不再用来砍轴
    segments = [
        TimelineSegment(
            episode_id=scene.episode_id,
            start=round(scene.start, 3),
            end=round(scene.end, 3),
            audio="narration" if intro_first and index == 0 else "original",
        )
        for index, scene in enumerate(ordered)
    ]
    if intro_first and segments:
        first = segments[0]
        segments[0] = first.model_copy(
            update={"end": round(min(first.end, first.start + _INTRO_MAX_S), 3)}
        )
    return segments


# 公开别名：pipeline.build_plan 全模式收口用（原声窗台词句边界吸附）
snap_windows_to_dialogue = _snap_windows_to_dialogue


# 话语连接词：窗首句以此开头说明它的前因在被跳过的对白里（业主 2026-10-28 实锤：
# 「没有原因，就到所以了么」——句子完整性之外还有因果连贯性）
_DISCOURSE_CONNECTIVE_RE = re.compile(
    r"^(所以|因此|为此|但是|但|可是|不过|然而|原来|结果|于是|然后|难怪|就这样|这下)"
)
_OPENING_EXTEND_CAP_S = 12.0  # 前因回溯的单窗扩幅上限（防一路连到集头）


def extend_openings_over_connectives(
    timeline: list[TimelineSegment],
    material: MaterialByEpisode | None,
) -> list[TimelineSegment]:
    """窗首句以话语连接词开头时，向前扩窗把前因句包进来（因果接缝的剪辑版）。

    句子完整性（不切半）之外的第二层：两个被选窗之间跳过的对白若正好是下一窗
    首句的语义前提（「所以…」「原来…」），观众听得没头没脑。回溯沿台词链逐句
    前扩，遇到非连接词开头的句子即停；受前一窗止点与扩幅上限双重约束——
    无原料/无连接词/扩不动都安静保持原值（增强不是义务）。
    """
    if material is None or not timeline:
        return timeline
    by_episode: dict[str, list[int]] = {}
    for index, segment in enumerate(timeline):
        if segment.audio == "original" and str(segment.narration_id or "") != "cta-1":
            by_episode.setdefault(segment.episode_id, []).append(index)
    updated = list(timeline)
    for indices in by_episode.values():
        for position, index in enumerate(indices):
            segment = updated[index]
            entry = material.get(segment.episode_id)
            if entry is None or not entry.asr:
                continue
            prev_end = updated[indices[position - 1]].end if position > 0 else None
            lines = sorted(entry.asr, key=lambda seg: seg.start)
            inside = [
                line
                for line in lines
                if line.start >= segment.start - 1e-6 and line.end <= segment.end + 1e-6
            ]
            if not inside or not _DISCOURSE_CONNECTIVE_RE.match(inside[0].text.strip()):
                continue
            new_start = segment.start
            for line in reversed(lines):
                if line.end > segment.start - 1e-6:
                    continue  # 只回溯窗前的句子
                if prev_end is not None and line.end <= prev_end + 1e-6:
                    break  # 撞上一窗止点：让位保边界
                if segment.start - line.start > _OPENING_EXTEND_CAP_S:
                    break  # 扩幅上限
                if new_start - line.end > 2.0:
                    break  # 台词链断了（间隔超 2s）：不是同一番对话
                new_start = line.start
                if not _DISCOURSE_CONNECTIVE_RE.match(line.text.strip()):
                    break  # 非连接词开头的句子=前因本体：包进来即停
            if new_start < segment.start - 1e-6:
                updated[index] = segment.model_copy(
                    update={"start": round(new_start, 3)}
                )
    return updated


def _retract_unanswered_questions(
    timeline: list[TimelineSegment],
    material: MaterialByEpisode | None,
) -> list[TimelineSegment]:
    """去尾问（T1 质批）：窗尾切在悬念问句上、而答案在窗外=许诺不兑现，观众体感
    是「吊胃口吊得莫名其妙」。回答完整在窗内不处理；回答被切则退到问句前剪——
    宁可不问，不可问而不答。受最小窗长与前一窗止点约束，退不动保持原值。"""
    if material is None or not timeline:
        return timeline
    updated = list(timeline)
    min_len = _RAW_CLIP_MIN_S
    for indices in by_episode_originals(timeline).values():
        for position, index in enumerate(indices):
            segment = updated[index]
            entry = material.get(segment.episode_id)
            if entry is None or not entry.asr:
                continue
            lines = sorted(entry.asr, key=lambda seg: seg.start)
            inside = [
                line
                for line in lines
                if line.start >= segment.start - 1e-6 and line.end <= segment.end + 1e-6
            ]
            if not inside:
                continue
            last = inside[-1]
            if not last.text.strip().endswith(("？", "?")):
                continue  # 窗尾不是问句
            answer = next((line for line in lines if line.start >= last.end - 1e-6), None)
            if answer is None or answer.end <= segment.end + 1e-6:
                continue  # 答案完整在窗内（或没有答案）：问而不吊
            prev_end = updated[indices[position - 1]].end if position > 0 else None
            new_end = last.start
            if prev_end is not None and new_end - prev_end < min_len:
                continue  # 退到问前会把窗剪没：保持原值（连接词扩展已尽力）
            updated[index] = segment.model_copy(update={"end": round(new_end, 3)})
    return updated


def by_episode_originals(timeline: list[TimelineSegment]) -> dict[str, list[int]]:
    """原声窗（剔除金句流重播卡）按集分组的序号表——吸附/扩展/去尾问共用的骨架。"""
    grouped: dict[str, list[int]] = {}
    for index, segment in enumerate(timeline):
        if (
            segment.audio == "original"
            and str(segment.narration_id or "") != "cta-1"
        ):
            grouped.setdefault(segment.episode_id, []).append(index)
    return grouped


_DIALOGUE_CHAIN_GAP_S = 0.6  # 句间隙 ≤ 此值=同一番对话还在继续（去尾问同源口径）
_ENDING_CHAIN_CAP_S = 12.0  # 对话链延尾的单窗扩幅上限（与开头前因回溯对称）


def extend_endings_over_dialogue_chains(
    timeline: list[TimelineSegment],
    material: MaterialByEpisode | None,
) -> list[TimelineSegment]:
    """对话链完整（T1 字幕批同源纪律的窗尾版）：窗尾之后台词链还在继续
    （下一句 ≤0.6s 接上），成片在此切=话说一半换画面。沿台词链向后逐句
    延窗，直到某句之后出现 >0.6s 的真停顿（话说完了）为止；受下一窗止点
    与扩幅上限双重约束，延不动保持原值。首句进入窗内的 Chain 才延——
    窗尾本来就在停顿上的不处理。"""
    if material is None or not timeline:
        return timeline
    updated = list(timeline)
    for indices in by_episode_originals(timeline).values():
        for position, index in enumerate(indices):
            segment = updated[index]
            entry = material.get(segment.episode_id)
            if entry is None or not entry.asr:
                continue
            lines = sorted(entry.asr, key=lambda seg: seg.start)
            inside = [
                line
                for line in lines
                if line.start >= segment.start - 1e-6 and line.end <= segment.end + 1e-6
            ]
            if not inside:
                continue
            next_start = (
                updated[indices[position + 1]].start
                if position + 1 < len(indices)
                else None
            )
            fence = (
                min(next_start, segment.start + _ENDING_CHAIN_CAP_S)
                if next_start is not None
                else segment.start + _ENDING_CHAIN_CAP_S
            )
            new_end = segment.end
            last_end = inside[-1].end
            cursor_line = inside[-1]
            while True:
                following = [
                    line
                    for line in lines
                    if line.start > cursor_line.end + 1e-6
                    and line.end <= fence + 1e-6
                ]
                if not following:
                    break
                nxt = following[0]  # 窗外紧接着的下一句
                if nxt.start - last_end > _DIALOGUE_CHAIN_GAP_S:
                    break  # 台词链断了：话说完了
                if nxt.end > fence + 1e-6:
                    break  # 这句会越过栅栏/上限
                new_end = nxt.end
                last_end = nxt.end
                cursor_line = nxt
                nxt_after = [
                    line
                    for line in lines
                    if line.start > cursor_line.end + 1e-6 and line.end <= fence + 1e-6
                ]
                if not nxt_after or nxt_after[0].start - cursor_line.end > _DIALOGUE_CHAIN_GAP_S:
                    break  # 这句之后是真停顿：话说完了
            if new_end > segment.end + 1e-6:
                updated[index] = segment.model_copy(
                    update={"end": round(new_end, 3)}
                )
    return updated

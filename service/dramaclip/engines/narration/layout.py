"""配音后时间轴布局：按实测时长把旁白段落位到源素材上。

自 pipeline.py 拆出（拆分专项）：三个布局模式（超短三拍重铺 / 交叉解说
桥段空隙装填 / 游标修补）+ 两个吸附工具（视觉切点 / 台词句界）+ 越界
守卫。调用方是 pipeline.synthesize_narration_texts——配音实测时长到手后，
布局层按模式规则整体重铺或游标修补时间轴，放不下的段交上层定向重写。
"""

from __future__ import annotations

import re
from typing import Any

from dramaclip.engines.narration.models import PlanData
from dramaclip.engines.narration.synthesis import _HOOK_SLOT_ID, LogFn, _emit

# 越界判定放的余量。两端数字都不精确：`end` 与源长都按 3 位小数入库（源长由扫描时
# ffprobe 量得，见 api/project.py），而素材自己的帧栅格更粗——实测 6.00s 的窗口落出
# 6.0667s 的流时长。所以「段尾正好等于源长」必须是绿的，判红线得抬到百分位以上。
# 真越界是秒级的：库存量实测 +4.88s / +6.03s，2026-09-19 真机 dialogue_narration +5.23s。
_SOURCE_FIT_TOL_S = 0.05

_BRIDGE_ID_RE = re.compile(r"^cross-\d+$")

# 结构层音画同步：实测重排把段界挪离编排位后，起点吸附回最近的视觉切点——
# 剪口落在换镜头处=画面不撕裂。只吸附起点（终点本来就锚在场景边界或集尾）。
_SCENE_SNAP_TOL_S = 0.5


def _snap_start(
    start: float,
    duration: float,
    floor: float,
    ceil: float,
    cuts: list[float],
) -> float:
    """把旁白窗口起点吸附到 ±0.5s 内最近的视觉切点；不破坏空隙约束才生效。

    `floor`/`ceil` 是该段实际可用的窗口边界（共享空隙的剩余右沿也算 ceil）：
    吸附后仍须 `floor <= start` 且 `start + duration <= ceil`，否则原值返回。
    无切点、区间内没有候选、吸附会撞界——三种情况都安静回退，吸附是增强不是义务。
    """
    if not cuts:
        return start
    near = [cut for cut in cuts if abs(cut - start) <= _SCENE_SNAP_TOL_S]
    if not near:
        return start
    snapped = min(near, key=lambda cut: (abs(cut - start), cut))
    if snapped >= floor - 1e-6 and snapped + duration <= ceil + _SOURCE_FIT_TOL_S:
        return snapped
    return start


def _fit_start_to_dialogue(
    start: float,
    length: float,
    floor: float,
    ceil: float,
    spans: list[tuple[float, float]],
) -> float:
    """渲染期让位把起点挪进台词句中时回吸句界（业主 2026-10-27 策略全链延伸：
    对话必须自然说完再转场，渲染期挪窗不得把窗沿挪回句中）。退到句首优先
    （窗仍 ≤ ceil），否则进到句尾之后；两头都不容才保持原值。"""
    for s0, s1 in sorted(spans):
        if s0 + 0.2 < start < s1 - 0.2:
            if s0 >= floor - 1e-6 and s0 + length <= ceil + _SOURCE_FIT_TOL_S:
                return s0
            if s1 >= floor - 1e-6 and s1 + length <= ceil + _SOURCE_FIT_TOL_S:
                return s1
            return start
    return start


def _bridge_entry(
    episode_id: str, slot: str, text: str, duration: float, start: float
) -> dict[str, Any]:
    """旁白时间轴条目（纯函数：`_layout_cross` 循环内不定义闭包绑循环变量）。"""
    return {
        "episode_id": episode_id,
        "start": round(start, 3),
        "end": round(start + duration, 3),
        "audio": "narration",
        "narration_id": slot,
        "subtitle_text": text,
    }


def _layout_ultra_short(
    plan: PlanData,
    voiced: dict[str, tuple[str, str, float]],
    source_durations: dict[str, float],
    log: LogFn | None,
) -> list[dict[str, Any]]:
    """超短三拍整体重铺：候选池按实测时长选景，三拍精确落位、互不重叠。

    候选窗按分值序找第一个「场景前放得下钩子实测、集尾放得下 CTA 实测」的；
    全都放不下 → 如实报错并给出各候选差多少秒，不静默、不裁剪（业主裁决）。
    钩子尾锚冲突窗开头（讲完正好进正片）、原声拍原样、CTA 接在窗后。
    """
    missing = [slot for slot in ("hook-1", "cta-1") if slot not in voiced]
    if missing:
        raise RuntimeError(f"超短方案缺 {'、'.join(missing)} 槽位的实测音频，无法布局")
    conflict = next(
        (segment for segment in plan.timeline if segment.audio == "original"), None
    )
    if conflict is None:
        raise RuntimeError("超短方案时间轴里没有冲突原声拍，无法布局")
    hook_dur = voiced["hook-1"][2]
    cta_dur = voiced["cta-1"][2]

    def _placed(episode_id: str, win_start: float, win_end: float) -> list[dict[str, Any]]:
        return [
            {
                "episode_id": episode_id,
                "start": round(win_start - hook_dur, 3),
                "end": round(win_start, 3),
                "audio": "narration",
                "narration_id": "hook-1",
                "subtitle_text": voiced["hook-1"][1],
            },
            {
                "episode_id": episode_id,
                "start": round(win_start, 3),
                "end": round(win_end, 3),
                "audio": "original",
            },
            {
                "episode_id": episode_id,
                "start": round(win_end, 3),
                "end": round(win_end + cta_dur, 3),
                "audio": "narration",
                "narration_id": "cta-1",
                "subtitle_text": voiced["cta-1"][1],
            },
        ]

    shortfalls: list[str] = []
    for candidate in plan.scene_pool:
        limit = source_durations.get(candidate.episode_id, 0.0)
        if limit <= 0:
            shortfalls.append(
                f"{candidate.episode_id}@{candidate.start:.0f}s 查不到集时长"
            )
            continue  # 与守卫同口径：查不了 = 放不下，换下一个
        if candidate.start < hook_dur:
            shortfalls.append(
                f"{candidate.episode_id}@{candidate.start:.0f}s "
                f"场景前素材 {candidate.start:.1f}s < 钩子 {hook_dur:.1f}s"
            )
            continue
        if candidate.end + cta_dur > limit + _SOURCE_FIT_TOL_S:
            shortfalls.append(
                f"{candidate.episode_id}@{candidate.start:.0f}s "
                f"集尾差 {candidate.end + cta_dur - limit:.1f}s"
            )
            continue
        _emit(
            log,
            f"超短布局按实测时长选中冲突窗 {candidate.episode_id} "
            f"{candidate.start:.2f}-{candidate.end:.2f}s"
            f"（钩子 {hook_dur:.1f}s + CTA {cta_dur:.1f}s）",
        )
        return _placed(candidate.episode_id, candidate.start, candidate.end)
    raise RuntimeError(
        "候选池里没有放得下实测时长的冲突窗（"
        + "；".join(shortfalls)
        + "）——重新生成方案即可换一批候选，文案与音频一秒不裁"
    )


def _layout_cross(
    plan: PlanData,
    voiced: dict[str, tuple[str, str, float]],
    source_durations: dict[str, float],
    log: LogFn | None,
    scene_cuts: dict[str, list[float]] | None = None,
    dialogue_spans: dict[str, list[tuple[float, float]]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """交叉解说桥段落位：场景原声窗原封不动，旁白按实测时长装进场景间空隙。

    旧布局把桥段叠在下个场景开头（与场景窗设计性重叠），IndexTTS 实测一超长
    就把场景顶出集尾（真机 2026-10-06：cross-3 差 0.16s 整条判死）。场景窗吸附
    过最强台词 span，挪了就不是那句台词——所以旁白改为收尾锚在下个场景开头、
    向前伸进空隙。

    空隙放不下**不再判死**（业主裁决 2026-10-26：素材不 fit 应重新选取而不是失败）：
    每集建空隙模型（原声窗钉死，多个空隙可从右往左共享装填），首选空隙装不下时
    桥段（cross-N）依次尝试同集后续更大的空隙；全都放不下的段进 `unplaced` 交
    上层定向重写（收短→重合成→重回排），两轮后仍放不下才弃段留痕。

    桥段落位后 **re-stamp 成锚点集号**：build_cross 给桥段盖的是当前场景的集
    （旁白压刚看过画面的延续帧），但空隙锚位算的是**下一场景**的集内时钟——
    跨集方案里两件事不同集：保留旧集号会让 start=下一集时钟−时长 落进本集的
    错误位置（本集场景起点普遍 ≈0，直接负起点误报判死），encoder 还会按旧集号
    从错误集取画面。布局语义＝桥段属于下一集时间轴，落位即改章。

    返回 `(timeline, unplaced)`；`unplaced` 元素含 slot/text/duration/episode_id/gap_s。
    """
    segments = plan.timeline
    anchors: dict[str, list[tuple[float, float]]] = {}
    for segment in segments:
        if segment.audio != "narration":
            anchors.setdefault(segment.episode_id, []).append(
                (float(segment.start), float(segment.end))
            )
    for window_list in anchors.values():
        window_list.sort()

    def _gap_floor(episode_id: str, before: float) -> float:
        """空隙下限：该集里右沿之前的最近原声窗的 end（没有则 0）。"""
        floor = 0.0
        for a_start, a_end in anchors.get(episode_id, []):
            if a_start < before - 1e-6:
                floor = max(floor, a_end)
        return floor

    # 同一空隙（集, 右沿）可能被多段共享：从右往左装填，记录剩余右沿。
    gap_ceil: dict[tuple[str, float], float] = {}
    # 尾隙（末段桥）沿用旧游标语义：左对齐接在最后一个原声窗之后。
    tail_cursor: dict[str, float] = {}
    timeline: list[dict[str, Any]] = []
    # 旁白条目不即时追加：挂到锚点原声段的序号上，装配到原声窗前按时序插入——
    # 时间轴列表序＝播放序，桥段改锚后若留在迭代位置会让画面倒放。
    entries_by_anchor: dict[int, list[dict[str, Any]]] = {}
    unplaced: list[dict[str, Any]] = []
    moved_bridges = 0
    for index, segment in enumerate(segments):
        if segment.audio != "narration":
            for entry in sorted(
                entries_by_anchor.pop(index, []), key=lambda item: item["start"]
            ):
                timeline.append(entry)
            timeline.append(segment.model_dump())
            continue
        slot = str(segment.narration_id or "")
        voiced_entry = voiced.get(slot)
        if voiced_entry is None:
            raise RuntimeError(f"交叉桥段 {slot} 没有实测音频，无法布局")
        _audio_path, text, duration = voiced_entry
        next_index = next(
            (
                j
                for j in range(index + 1, len(segments))
                if segments[j].audio != "narration"
            ),
            None,
        )
        next_original = segments[next_index] if next_index is not None else None
        anchor_episode = (
            next_original.episode_id if next_original is not None else segment.episode_id
        )
        limit = source_durations.get(anchor_episode, 0.0)
        if limit <= 0:
            # 与 `_assert_within_source` 同口径：拿不到源长＝无法证明不越界，判失败。
            raise RuntimeError(
                f"无法核对画面窗口是否越过源集末尾：桥段 {slot} 锚定的集 "
                f"{anchor_episode} 没有源集时长（未入库或为 0）"
            )

        placed = False
        if next_original is None:
            # 末段桥：接在本集最后一个原声窗之后（左对齐，沿用旧游标语义）。
            start = max(
                _gap_floor(anchor_episode, float("inf")),
                tail_cursor.get(anchor_episode, 0.0),
            )
            start = _snap_start(
                start,
                duration,
                _gap_floor(anchor_episode, float("inf")),
                limit,
                (scene_cuts or {}).get(anchor_episode, []),
            )
            start = _fit_start_to_dialogue(
                start,
                duration,
                _gap_floor(anchor_episode, float("inf")),
                limit,
                (dialogue_spans or {}).get(anchor_episode, []),
            )
            if start + duration <= limit + _SOURCE_FIT_TOL_S:
                entries_by_anchor.setdefault(len(segments), []).append(
                    _bridge_entry(anchor_episode, slot, text, duration, start)
                )
                tail_cursor[anchor_episode] = start + duration
                placed = True
        else:
            # 候选空隙：首选位（下一场景前的空隙，右对齐收尾锚在场景开头），
            # 桥段再补同集后续场景空隙（依次尝试更大空隙）。
            candidates: list[tuple[str, float, int]] = [
                (anchor_episode, float(next_original.start), int(next_index or 0))
            ]
            if _BRIDGE_ID_RE.match(slot):
                assert next_index is not None  # next_original 非 None 蕴含
                for j in range(next_index + 1, len(segments)):
                    later = segments[j]
                    if (
                        later.audio != "narration"
                        and later.episode_id == anchor_episode
                        and float(later.start) > float(next_original.start) + 1e-6
                    ):
                        candidates.append((anchor_episode, float(later.start), j))
            for gap_episode, gap_right, anchor_index in candidates:
                floor = _gap_floor(gap_episode, gap_right)
                ceil_remaining = gap_ceil.get((gap_episode, gap_right), gap_right)
                if duration <= ceil_remaining - floor + _SOURCE_FIT_TOL_S:
                    start = _snap_start(
                        ceil_remaining - duration,
                        duration,
                        floor,
                        ceil_remaining,
                        (scene_cuts or {}).get(gap_episode, []),
                    )
                    start = _fit_start_to_dialogue(
                        start,
                        duration,
                        floor,
                        ceil_remaining,
                        (dialogue_spans or {}).get(gap_episode, []),
                    )
                    entries_by_anchor.setdefault(anchor_index, []).append(
                        _bridge_entry(gap_episode, slot, text, duration, start)
                    )
                    gap_ceil[(gap_episode, gap_right)] = ceil_remaining - duration
                    placed = True
                    if (gap_episode, gap_right) != candidates[0][:2]:
                        moved_bridges += 1
                        _emit(
                            log,
                            f"桥段 {slot} 实测 {duration:.2f}s 超出场景 "
                            f"{candidates[0][1]:.2f}s 前的空隙，改锚到场景 "
                            f"{gap_right:.2f}s 前的更大空隙",
                        )
                    break
        if not placed:
            gap_right = (
                limit
                if next_original is None
                else float(next_original.start)
            )
            first_floor = _gap_floor(anchor_episode, gap_right)
            unplaced.append(
                {
                    "slot": slot,
                    "text": text,
                    "duration": duration,
                    "episode_id": anchor_episode,
                    "gap_s": max(gap_right - first_floor, 0.0),
                }
            )
    for entry in sorted(
        entries_by_anchor.pop(len(segments), []), key=lambda item: item["start"]
    ):
        timeline.append(entry)
    _emit(
        log,
        f"交叉布局按实测时长把 {sum(1 for s in timeline if s['audio'] == 'narration')}"
        f"段旁白放进场景间空隙（{moved_bridges} 段改锚更大空隙），场景原声窗原样保留",
    )
    return timeline, unplaced


def _patch_timeline(
    plan: PlanData,
    voiced: dict[str, tuple[str, str, float]],
    source_durations: dict[str, float],
    scene_cuts: dict[str, list[float]] | None = None,
    dialogue_spans: dict[str, list[tuple[float, float]]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """游标修补（既有回填语义）：旁白段长=实测音频，头部扩展→尾部收口。

    两处都放不下的段不再原样交给 `_assert_within_source` 判死（业主裁决
    2026-10-26：素材不 fit 应重新选取而不是失败）：进 `unplaced` 交上层定向
    重写（收短→重合成→重回排），两轮后仍放不下弃段留痕。返回 `(timeline, unplaced)`。
    """
    timeline = [segment.model_dump() for segment in plan.timeline]
    # 实测音频时长 ≠ 编排期的估计时长：把 end 直接改成 start + 实测，前一段就会
    # 盖住后一段的源素材区间，成片演到第 6 秒又倒回第 1 秒重播同一段画面（业主
    # 立案③）。这里按集重走一遍编排层同款游标（`build_from_script_episodes` 的
    # `start = max(candidate, cursor)`）：只保证源时间单调不回退，旁白段长度
    # 仍等于实测音频，原声段只平移不压缩。
    #
    # 例外（B 项·片头闪前预告）：`build_intro` 把最高冲突镜前置做首帧，片头旁白
    # 讲最大冲突、画面是后段的高潮镜，正文再从头讲——片头对同集后续段是**有意**的
    # 源时间倒回（与 raw_clip 的预告式开场同构），不是立案③那种回填抖动导致的意外
    # 重播。若让片头照常推进游标，游标会把正文挤到预告之后、甚至冲出源集末尾
    # （真机探针：前置 94-100s 的片尾镜 + 8s 钩子 TTS，正文 0-6s 被顶到 106 > 源长
    # 100，整条方案响亮失败）。故闪前预告段不推进游标，正文从自己的计划起点重新起算。
    # 判据：片头段（intro-1 槽位）的计划源起点晚于其后任一**同集**段的计划源起点 ⇒
    # 闪前预告；最高冲突镜本就是时序第一镜（未前置）时片头是普通时序段，游标照常推进，
    # 立案③的重播保护不受影响。
    _planned_starts = [float(segment["start"]) for segment in timeline]
    _intro_teaser = False
    if timeline and timeline[0].get("narration_id") == _HOOK_SLOT_ID:
        _head_episode = str(timeline[0]["episode_id"])
        _intro_teaser = any(
            str(segment["episode_id"]) == _head_episode
            and _planned_starts[index] < _planned_starts[0]
            for index, segment in enumerate(timeline[1:], start=1)
        )
    cursor: dict[str, float] = {}
    unplaced: list[dict[str, Any]] = []
    for index, segment in enumerate(timeline):
        # CTA 重播白名单（w9 金句流收尾卡，audio=original + narration_id=cta-1）：
        # 设计语义=复用末场景尾帧压 CTA 字幕，占位重叠窗按原样保留——游标 clamp 会
        # 把它顶到场景后的未取材画面，末场景贴集尾时甚至原样越界判死（2026-10-27
        # 审计 C8）。场景末≤源长 ⇒ 窗口恒在源内；恒为末段，不推进游标。
        if (
            segment["audio"] == "original"
            and str(segment.get("narration_id") or "") == "cta-1"
        ):
            continue
        episode_id = str(segment["episode_id"])
        floor = cursor.get(episode_id, 0.0)
        planned_start = float(segment["start"])
        planned_end = float(segment["end"])
        start = max(planned_start, floor)
        if segment["audio"] in ("narration", "ducked"):
            # ducked（全片解说全程压底旁白）与 narration 同权：两者都要回填时长与解说字幕
            _audio_path, text, duration = voiced[str(segment["narration_id"])]
            segment["subtitle_text"] = text
            length = duration
        else:
            length = planned_end - planned_start
        limit = source_durations.get(episode_id, 0.0)
        # 头部扩展（2026-10-06 业主裁决「保障素材时长，不裁」）：实测旁白比计划窗口
        # 长时，先保住计划尾——配哪几秒画面是编排选好的——把起点往前伸。吃的是
        # 上一段与本段之间的空闲素材：不偷后段的画面（立案③），不把已计划素材
        # 推出集尾。伸不动（计划尾本身出界、或前面被上一段占满）再退回收口，
        # 还不行由 `_assert_within_source` 如实判死。
        if (
            segment["audio"] in ("narration", "ducked")
            and length > planned_end - planned_start
            and limit > 0
            and planned_end <= limit + _SOURCE_FIT_TOL_S
            and planned_end - length >= floor
        ):
            start = planned_end - length
            start = _snap_start(
                start,
                length,
                floor,
                planned_end,
                (scene_cuts or {}).get(episode_id, []),
            )
            start = _fit_start_to_dialogue(
                start,
                length,
                floor,
                planned_end,
                (dialogue_spans or {}).get(episode_id, []),
            )
        # 尾部收口：实测比剩余素材长时，整段往前挪到贴着集尾——这段的文案与长度都不动，
        # 换的只是压在它下面的画面。挪不动（再往前就和上一段重叠=画面重播）就照原样
        # 交给 `_assert_within_source` 判死，不截音也不截画面。
        # 为什么"段尾正好等于源末尾"是安全的：真机实测（bundled ffmpeg 8.1.1，源
        # `1.mp4` 现量 192.200s，真 TTS 干音 6.350s，命令由 `cut_segment_args` 生成）
        # 窗口 185.85→192.20 出片视频 6.367s / 音频 6.371s，与同一干音在素材中段
        # 20.00→26.35 的产物逐毫秒一致；而起点即 EOF 的越界窗口退码仍 0、262 字节无流。
        # 收口损失的只有"这一段配哪几秒画面"，没有一帧声音被丢掉。
        elif 0 < limit < start + length and limit - length >= floor:
            start = limit - length
            start = _snap_start(
                start,
                length,
                floor,
                limit,
                (scene_cuts or {}).get(episode_id, []),
            )
            start = _fit_start_to_dialogue(
                start,
                length,
                floor,
                limit,
                (dialogue_spans or {}).get(episode_id, []),
            )
        elif (
            segment["audio"] in ("narration", "ducked")
            and limit > 0
            and start + length > limit + _SOURCE_FIT_TOL_S
        ):
            # 头部扩展与尾部收口都伸不动：不原样留给守卫判死，转 unplaced 让上层
            # 先定向重写、两轮后仍放不下再弃段。该段不入时间轴，后续段的游标floor
            # 停在前一段——它的窗口自然让位。
            unplaced.append(
                {
                    "slot": str(segment["narration_id"]),
                    "text": voiced[str(segment["narration_id"])][1],
                    "duration": length,
                    "episode_id": episode_id,
                    "gap_s": max(limit - floor, 0.0),
                }
            )
            continue
        end = start + length
        segment["start"] = round(start, 3)
        segment["end"] = round(end, 3)
        if index == 0 and _intro_teaser:
            continue  # 闪前预告不推进游标：正文从自己的计划起点起算（见上方判据注释）
        cursor[episode_id] = end
    # 弃段不在时间轴里留影子：timeline 是预构建的原地改写列表，unplaced 的段
    # 没经过落位改写，必须摘掉，否则成片按编排期估计窗渲染一段没有配音的旁白。
    dropped_slots = {str(entry["slot"]) for entry in unplaced}
    if dropped_slots:
        timeline = [
            segment
            for segment in timeline
            if str(segment.get("narration_id") or "") not in dropped_slots
        ]
    return timeline, unplaced


def _assert_within_source(
    timeline: list[dict[str, Any]],
    source_durations: dict[str, float],
) -> None:
    """回填后的画面窗口必须仍落在源集里，越界就是这条方案失败。

    查出问题的动作是回填：它把段尾改成 `start + 实测音频时长`。编排层自己也可能把窗
    口摆到源末尾之外——`build_from_script_episodes` 的预算写的是「源长 + 5s」，真机
    2026-09-19 那条 dialogue_narration 就是 192.20s 的集配 197.43s 的段（超 5.23s）。
    两处谁犯的错都在这里一并兜住：判据看的是最终要播的窗口，不是谁写的。

    源时长缺失或不大于 0 同样判失败：拿不到源长就等于「无法证明不越界」，把它当成
    「没有越界」是这套判据最省事的静默失效方式。

    真机实测（bundled ffmpeg 8.1.1，源 `6.mp4` = 76.86s，9s 旁白干音）：
    窗口 70.86→79.86 退码 **0**、产物视频 6.07s / 音频 6.03s，旁白被从中间掐掉；
    窗口 76.86→82.86（起点即 EOF）退码仍 0、产物 262 字节无流。渲染层既不报错也不
    警告，所以这里不拦就是静默出坏片（业主裁决：改所见所闻的一律失败，不做截断）。

    走到这里说明回填的尾部收口（`synthesize_narration_texts` 里那句「整段往前挪到贴着
    集尾」）已经让过位了：再往前就撞上同集的上一段。所以文案与长度都不动，判失败。
    """
    prev_end: dict[str, float] = {}
    for index, segment in enumerate(timeline):
        episode_id = str(segment["episode_id"])
        limit = source_durations.get(episode_id, 0.0)
        if limit <= 0:
            raise RuntimeError(
                f"无法核对画面窗口是否越过源集末尾：时间轴引用的集 {episode_id}"
                " 没有源集时长（未入库或为 0）——宁可不出这条方案，"
                "也不能拿「查不了」当「没问题」"
            )
        end = float(segment["end"])
        floor = prev_end.get(episode_id)
        prev_end[episode_id] = end
        if end <= limit + _SOURCE_FIT_TOL_S:
            continue
        slot = segment.get("narration_id")
        label = f"旁白段 {slot}" if slot else f"原声段 #{index}"
        # 为什么不挪了：往前贴集尾会撞上同集的上一段（画面重播=业主立案③），
        # 而这一集的第一段已经没有"上一段"可撞，说明旁白比整集素材还长。
        stuck = (
            f"往前挪到贴着集尾就会和上一段（止于 {floor:.2f}s）重叠，等于重播画面"
            if floor is not None and floor > 0
            else "这一段比整集素材还长，挪到集头也放不下"
        )
        raise RuntimeError(
            f"配音回填后画面窗口越过源集末尾：{episode_id} 的{label} 要播到 "
            f"{end:.2f}s，源集时长只有 {limit:.2f}s（超出 {end - limit:.2f}s）"
            f" —— {stuck}，这条方案判失败而不是把旁白截掉"
        )

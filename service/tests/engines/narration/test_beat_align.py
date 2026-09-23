"""engines.narration.beat_align：B9 节拍吸附纯函数。

为什么每条分支都值得单独钉：吸附是「意图层」的微调——挪过头（叙事窗口被改短）
与该挪不挪（成片不卡点）都是听感问题，而 tolerance / min_len 是两者之间仅有的
两道闸门；空 beats 的降级分支则守着旧库分析记录（B9 之前落库的 JSON 没有
beats 字段）不被误伤。
"""

from __future__ import annotations

from dramaclip.engines.narration.beat_align import snap_cut, snap_window_end


class TestSnapCut:
    def test_snaps_to_nearest_beat_within_tolerance(self) -> None:
        assert snap_cut(10.08, [5.0, 10.0, 15.0]) == 10.0

    def test_leaves_cut_alone_when_nearest_beat_is_out_of_tolerance(self) -> None:
        # 最近 beat 差 0.3s，超出默认容差 0.25s：宁可不卡也不硬挪——
        # 挪出容差等于把切点绑到错误的拍上，比不卡点更难受
        assert snap_cut(10.3, [5.0, 10.0, 15.0]) == 10.3

    def test_empty_beats_degrades_to_the_original_cut(self) -> None:
        # 旧库分析记录没有 beats 字段（或分析时无 librosa）：吸附层必须静默让路
        assert snap_cut(10.08, []) == 10.08

    def test_beat_exactly_at_tolerance_edge_still_snaps(self) -> None:
        assert snap_cut(10.25, [10.0], tolerance=0.25) == 10.0

    def test_tie_between_two_equidistant_beats_is_deterministic(self) -> None:
        # 10.15 与 9.9/10.4 等距（0.25s）：确定性取**靠前**的拍——方案要落库复查，
        # 同输入必须同输出
        assert snap_cut(10.15, [9.9, 10.4]) == 9.9

    def test_custom_tolerance_is_respected(self) -> None:
        assert snap_cut(10.4, [10.0], tolerance=0.5) == 10.0

    def test_cut_before_first_and_after_last_beat(self) -> None:
        # 越出 beat 表两端的切点只能吸附到端点拍，同样受容差管
        assert snap_cut(4.9, [5.0, 10.0]) == 5.0
        assert snap_cut(10.2, [5.0, 10.0]) == 10.0
        # 末拍之外且超容差：不吸附（吸附层不 extrapolate 拍栅格）
        assert snap_cut(10.4, [5.0, 10.0]) == 10.4


class TestSnapWindowEnd:
    def test_snaps_end_to_beat_within_tolerance(self) -> None:
        assert snap_window_end(2.0, 10.1, [10.0], min_len=2.0) == 10.0

    def test_gives_up_when_snap_would_shorten_below_min_len(self) -> None:
        # 段长 2.1s，吸附到 1.9s 会把段压到 min_len=2.0 之下：
        # 画面太短比不卡点更伤（观感上是「闪了一下」），放弃吸附
        assert snap_window_end(0.0, 2.1, [1.9], min_len=2.0) == 2.1

    def test_snapped_length_exactly_at_min_len_is_allowed(self) -> None:
        # 规则是「< min_len 才放弃」，正好等于下限的吸附有效
        assert snap_window_end(0.0, 2.1, [2.0], min_len=2.0) == 2.0

    def test_never_extends_past_original_end_plus_tolerance(self) -> None:
        # beat 在 end+0.2s（容差内）：只微调，允许
        assert snap_window_end(0.0, 10.0, [10.2], min_len=2.0) == 10.2
        # beat 在 end+0.4s（容差外）：不动——节拍吸附不得延长叙事窗口
        assert snap_window_end(0.0, 10.0, [10.4], min_len=2.0) == 10.0

    def test_empty_beats_returns_original_end(self) -> None:
        assert snap_window_end(0.0, 8.0, [], min_len=2.0) == 8.0

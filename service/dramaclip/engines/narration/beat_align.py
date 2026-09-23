"""B9 节拍吸附：把「任意秒」的规划切点微调到最近的音乐拍点上（纯函数，无 IO）。

为什么只有这两个函数、以及它们各自的护栏：

- `snap_cut`：最近拍在容差（默认 0.25s）内才吸附，否则原值不动。容差外硬挪
  等于把切点绑到错误的拍上——听感比不卡点更糟。beats 为空（旧库分析记录没有
  beats 字段，或分析时没装 librosa）时原值返回，优雅降级。
- `snap_window_end`：吸附段尾，但有两道额外的闸：吸附后段长 < min_len 就放弃
  （画面太短比不卡点更伤，观感是「闪了一下」）；吸附只微调，不把窗口延长到
  原 end + tolerance 之外（节拍不得改变叙事时长预算）。

**不做「同源素材节拍推进取窗」**：调研里那条讲的是混剪重复从同一条素材取窗、
按拍推进避免撞车的问题。DramaClip 的金句流/交叉解说取的是**不同场景**的窗口
（每个窗口都从各自的 scene.start 起算），天然不复用，不存在这个问题。

**与导出层的关系**：这里的吸附是规划层的**意图点**。导出层
`engines/dedup/jitter.safe_times` 为避开台词保护区还会把切点再挪 ±0.3s——
台词保护 > 节拍，这是既有的钉死纪律；被 jitter 挪走后节拍意图损失是可接受
代价（挪走说明那个拍点会切进台词，听感上台词优先）。
"""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_TOLERANCE_S = 0.25


def snap_cut(
    cut_s: float,
    beats: Sequence[float],
    *,
    tolerance: float = DEFAULT_TOLERANCE_S,
) -> float:
    """把切点吸附到最近的拍；最近拍超出容差（或 beats 为空）时原值返回。

    等距取**靠前**的拍（min 对 (距离, 拍值) 排序，同距离拍值小者胜）：
    方案要落库复查，同输入必须同输出。
    """
    if not beats:
        return cut_s
    nearest = min(beats, key=lambda beat: (abs(beat - cut_s), beat))
    if abs(nearest - cut_s) <= tolerance:
        return float(nearest)
    return cut_s


def snap_window_end(
    start: float,
    end: float,
    beats: Sequence[float],
    *,
    min_len: float,
    tolerance: float = DEFAULT_TOLERANCE_S,
) -> float:
    """吸附窗口终点；两道护栏见模块 docstring（min_len 放弃 / 不延长超容差）。"""
    snapped = snap_cut(end, beats, tolerance=tolerance)
    if snapped == end:
        return end
    if snapped - start < min_len:
        return end  # 吸附会把段压得太短：画面太短比不卡点更伤
    if snapped > end + tolerance:
        return end  # 只微调不延长：snap_cut 已挡了容差外的拍，这里挡容差内的延长
    return snapped

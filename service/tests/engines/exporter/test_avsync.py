"""avsync 互相关自检（T1 质批）：采样点选择、相关偏移恢复、阈值判定。"""

import numpy as np

from dramaclip.engines.exporter.selfcheck import (
    _AVSYNC_SAMPLE_RATE as _avsync_sample_rate,
)
from dramaclip.engines.exporter.selfcheck import (
    _correlation_lag_s,
    avsync_sample_points,
    check_avsync,
)


class _Seg:
    """最小时间轴段形状（避免拉全量模型）。"""

    def __init__(self, episode_id: str, start: float, end: float, audio: str) -> None:
        self.episode_id = episode_id
        self.start = start
        self.end = end
        self.audio = audio


def test_sample_points_pick_original_segments_only() -> None:
    timeline = [
        _Seg("ep1", 30.0, 40.0, "original"),
        _Seg("ep1", 40.0, 48.0, "narration"),  # TTS 段：不可采样
        _Seg("ep2", 10.0, 30.0, "original"),
    ]
    points = avsync_sample_points(timeline, (0.15, 0.5, 0.85))
    # 全轴 68s：0.15→10.2s（原声段）、0.5→34s（落在旁白段→跳过）、0.85→57.8s（ep2）
    assert all(p[1] in {"ep1", "ep2"} for p in points)
    assert not any(40.0 <= p[0] <= 48.0 for p in points), "旁白段不得采样"


def test_correlation_lag_recovers_known_shift() -> None:
    rng = np.random.default_rng(7)
    source = rng.standard_normal(_avsync_sample_rate * 3) * 1000
    true_lag_s = 1.55  # film 窗对应源 1.55s 起的内容（源抽取起点 0 + 窗半 1.5 + 偏移 0.05）
    start = int(_avsync_sample_rate * true_lag_s)
    length = int(_avsync_sample_rate * 2.0)
    film = source[start : start + length]
    lag = _correlation_lag_s(film, source)
    assert lag is not None and abs(lag - true_lag_s) < 0.005


def test_check_avsync_thresholds() -> None:
    assert check_avsync([10.0, 12.0, 14.0])["pass"] is True
    check = check_avsync([10.0, 90.0])  # 离散度 80ms 超阈
    assert check["pass"] is False
    assert check_avsync([5.0])["pass"] is None  # 单点归灰
    assert check_avsync(None)["pass"] is None

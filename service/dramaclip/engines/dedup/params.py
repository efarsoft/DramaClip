"""逐片段处理参数生成（每片段独立随机，docs/06-经验参数表 §1）。"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class DedupParams:
    speed_factor: float      # 微变速 0.996~1.004（atempo 变速不变调）
    contrast: float          # eq 对比度 0.99~1.01
    brightness: float        # eq 亮度 ±0.01
    scale_factor: float      # 微缩放 0.982~0.988（缩小后等比拉回标准尺寸，无黑边）

    @property
    def changed(self) -> bool:
        return (
            self.speed_factor != 1.0
            or self.contrast != 1.0
            or self.brightness != 0.0
            or self.scale_factor != 1.0
        )


def generate(rng: random.Random | None = None) -> DedupParams:
    generator = rng or random
    return DedupParams(
        speed_factor=round(generator.uniform(0.996, 1.004), 4),
        contrast=round(generator.uniform(0.99, 1.01), 4),
        brightness=round(generator.uniform(-0.01, 0.01), 4),
        scale_factor=round(generator.uniform(0.982, 0.988), 4),
    )

"""逐片段处理参数生成（每片段独立随机，docs/06-经验参数表 §1）。

默认关（2026-11-18 业主裁决）：设置 ``export.dedup_jitter`` 默认 "0"——微扰动
对「素材包同内容多达人出片」有真实场景，但全域低幅扰动本身是平台判重算法
公开打击的规避模式，可能反而成为限流诱因。默认值是产品立场：不替用户做
规避动作；确有需要的用户看完风险提示后显式打开（encoder 侧 neutral() 恒等
参数走原滤镜链，行为可预期），开启与否如实记进自检成绩单（成片可自证）。
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass(frozen=True)
class DedupParams:
    speed_factor: float      # 微变速 0.996~1.004（atempo 变速不变调）
    contrast: float          # eq 对比度 0.99~1.01
    brightness: float        # eq 亮度 ±0.01
    scale_factor: float      # 微缩放 0.982~0.988（只缩小不拉回：等比适配进画布并补黑，ADR-010）

    @property
    def changed(self) -> bool:
        return (
            self.speed_factor != 1.0
            or self.contrast != 1.0
            or self.brightness != 0.0
            or self.scale_factor != 1.0
        )


def neutral() -> DedupParams:
    """恒等参数：走原滤镜链但零效果（eq 1.0/0.0、setpts=/1.0、scale=画布尺寸）。"""
    return DedupParams(
        speed_factor=1.0,
        contrast=1.0,
        brightness=0.0,
        scale_factor=1.0,
    )


def generate(rng: random.Random | None = None) -> DedupParams:
    generator = rng or random
    return DedupParams(
        speed_factor=round(generator.uniform(0.996, 1.004), 4),
        contrast=round(generator.uniform(0.99, 1.01), 4),
        brightness=round(generator.uniform(-0.01, 0.01), 4),
        scale_factor=round(generator.uniform(0.982, 0.988), 4),
    )

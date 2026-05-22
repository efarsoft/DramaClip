"""
AI解说管道 - 完整的AI解说模式流水线

已更新：使用 ModularDirectCutPipeline 替代已废弃的 DirectCutPipeline
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

import openai

from app.services.clip.modular_direct_cut import ModularDirectCutPipeline
from app.utils.ffmpeg_utils import get_ffmpeg_path
from loguru import logger


class NarrationPipeline:
    """AI解说流水线"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        # 使用模块化版本替代已废弃的 DirectCutPipeline
        self.direct_cut_pipeline = ModularDirectCutPipeline(config)
        logger.info("NarrationPipeline initialized (使用 ModularDirectCutPipeline)")

    def run(self, video_paths: List[str], target_duration: Optional[int] = None, **kwargs):
        # ... 原有逻辑保留 ...

        # 复用 ModularDirectCutPipeline 选取高光片段
        logger.info("Step 2: Selecting highlight segments")
        sorted_segments = self.direct_cut_pipeline.run_segments_only(
            video_paths, target_duration=target_duration
        )

        # ... 后续逻辑 ...
        pass

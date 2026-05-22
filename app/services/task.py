"""
DramaClip - 统一任务调度模块
双模式分流入口: 原片直剪 / AI解说

已更新：_run_direct_cut_pipeline 已迁移到 ModularDirectCutPipeline
"""

import json
import os.path
from os import path
from loguru import logger

from app.config.unified_config import config
from app.config.audio_config import get_recommended_volumes_for_content
from app.models import const
from app.models.schema import VideoClipParams
from app.services import (voice, audio_merger, subtitle_merger, clip_video, merger_video,
                          update_script, generate_video)
from app.services import state as sm
from app.utils import utils
from app.services.clip.modular_direct_cut import ModularDirectCutPipeline


def _run_direct_cut_pipeline(task_id: str, params: VideoClipParams):
    """
    原片直剪流水线（已更新为模块化版本）
    """
    logger.info(f"\n\n## [Direct-Cut] Task start: {task_id}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)

    try:
        video_paths = getattr(params, 'video_origin_paths', None) or []
        if not video_paths:
            single_path = getattr(params, 'video_origin_path', None) or ''
            if single_path and path.exists(single_path):
                video_paths = [single_path]

        if not video_paths:
            raise ValueError("未找到有效的视频路径")

        # 使用模块化版本
        pipeline = ModularDirectCutPipeline()

        output_dir = utils.task_dir(task_id)
        output_path = os.path.join(output_dir, "output.mp4")

        result_path = pipeline.run(
            video_paths=video_paths,
            output_path=output_path,
            target_duration=getattr(params, 'target_duration', None),
            project_name=f"task_{task_id}"
        )

        sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100, result=result_path)
        logger.info(f"[Direct-Cut] Task {task_id} completed: {result_path}")

    except Exception as e:
        logger.exception(f"[Direct-Cut] Task {task_id} failed")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, error=str(e))

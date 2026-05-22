"""
智能一键剪辑流水线
P1 核心功能：整合推荐 + 剪辑 + 标题生成，一键完成全流程

用户操作流程：
1. 选择视频
2. 点击"一键生成"
3. 等待处理（获得实时进度）
4. 直接获得：剪辑视频 + AI标题 + 简介 + 标签
"""

import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum
from loguru import logger

from app.services.clip.modular_direct_cut import ModularDirectCutPipeline
from app.services.mode_recommender import (
    get_smart_recommender,
    ClipMode,
    ModeRecommendation,
)
from app.services.title_generator import (
    get_title_generator,
    TitleGenerationResult,
)
from app.utils.path_manager import get_path_manager
from app.utils.ffmpeg import smart_crop
from app.exceptions import ErrorFactory


class OneClickStatus(str, Enum):
    """一键处理状态"""
    INITIALIZING = "initializing"
    ANALYZING = "analyzing"
    RECOMMENDING = "recommending"
    CLIPPING = "clipping"
    GENERATING_TITLES = "generating_titles"
    CROPPING = "cropping"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class OneClickProgress:
    """一键处理进度"""
    status: OneClickStatus
    progress: int          # 0-100
    phase: str              # 当前阶段描述
    message: str           # 详细信息
    clip_output_path: Optional[str] = None
    title_result: Optional[TitleGenerationResult] = None
    error: Optional[str] = None


@dataclass
class OneClickResult:
    """一键处理结果"""
    success: bool
    recommendation: ModeRecommendation
    clip_output_path: str
    clip_output_ratio: str
    title_result: TitleGenerationResult
    total_duration: float
    processing_time: float
    error: Optional[str] = None


class OneClickPipeline:
    """
    智能一键剪辑流水线

    整合以下步骤：
    1. 智能推荐模式
    2. 执行剪辑
    3. 生成标题和简介
    4. 智能裁剪
    """

    def __init__(
        self,
        enable_title_generation: bool = True,
        default_ratio: str = "9:16",
    ):
        self._recommender = get_smart_recommender()
        self._title_generator = get_title_generator()
        self._enable_title = enable_title_generation
        self._default_ratio = default_ratio
        self._path_mgr = get_path_manager()

    def run(
        self,
        video_paths: List[str],
        project_name: str,
        target_ratio: Optional[str] = None,
        enable_titles: bool = True,
        progress_callback: Optional[Callable[[OneClickProgress], None]] = None,
    ) -> OneClickResult:
        """
        执行一键剪辑

        Args:
            video_paths: 视频路径列表
            project_name: 项目名称
            target_ratio: 目标比例（可选，自动推荐）
            enable_titles: 是否生成标题
            progress_callback: 进度回调

        Returns:
            OneClickResult: 处理结果
        """
        import time
        start_time = time.time()

        try:
            progress = OneClickProgress(
                status=OneClickStatus.INITIALIZING,
                progress=0,
                phase="初始化",
                message="准备处理...",
            )
            self._report_progress(progress_callback, progress)

            recommendation = self._do_recommend(
                video_paths, progress_callback
            )

            progress = OneClickProgress(
                status=OneClickStatus.CLIPPING,
                progress=35,
                phase="执行剪辑",
                message=f"使用 {recommendation.recommended_mode.value} 模式...",
            )
            self._report_progress(progress_callback, progress)

            clip_output = self._do_clip(
                video_paths=video_paths,
                project_name=project_name,
                mode=recommendation.recommended_mode,
                target_duration=recommendation.target_duration,
                progress_callback=progress_callback,
            )

            progress = OneClickProgress(
                status=OneClickStatus.GENERATING_TITLES,
                progress=65,
                phase="生成标题",
                message="正在生成爆款标题...",
            )
            self._report_progress(progress_callback, progress)

            title_result = None
            if enable_titles and recommendation.auto_title_enabled:
                title_result = self._do_generate_titles(
                    clip_output, recommendation, progress_callback
                )
            else:
                progress = OneClickProgress(
                    status=OneClickStatus.GENERATING_TITLES,
                    progress=75,
                    phase="跳过标题",
                    message="标题生成已禁用",
                )
                self._report_progress(progress_callback, progress)

            ratio = target_ratio or recommendation.suggested_ratio

            progress = OneClickProgress(
                status=OneClickStatus.CROPPING,
                progress=85,
                phase="智能裁剪",
                message=f"裁剪为 {ratio}...",
            )
            self._report_progress(progress_callback, progress)

            final_output = self._do_crop(
                clip_output, project_name, ratio, progress_callback
            )

            processing_time = time.time() - start_time

            progress = OneClickProgress(
                status=OneClickStatus.COMPLETED,
                progress=100,
                phase="完成",
                message=f"处理完成，耗时 {processing_time:.1f}秒",
                clip_output_path=final_output,
                title_result=title_result,
            )
            self._report_progress(progress_callback, progress)

            logger.info(
                f"[OneClick] 完成！耗时 {processing_time:.1f}s, "
                f"输出: {final_output}"
            )

            return OneClickResult(
                success=True,
                recommendation=recommendation,
                clip_output_path=final_output,
                clip_output_ratio=ratio,
                title_result=title_result,
                total_duration=recommendation.target_duration or 60,
                processing_time=processing_time,
            )

        except Exception as e:
            logger.error(f"[OneClick] 处理失败: {e}")
            progress = OneClickProgress(
                status=OneClickStatus.FAILED,
                progress=0,
                phase="失败",
                message=str(e),
                error=str(e),
            )
            self._report_progress(progress_callback, progress)
            raise

    def _do_recommend(
        self,
        video_paths: List[str],
        progress_callback: Optional[Callable],
    ) -> ModeRecommendation:
        """执行推荐"""
        progress = OneClickProgress(
            status=OneClickStatus.RECOMMENDING,
            progress=10,
            phase="智能分析",
            message="分析视频内容...",
        )
        self._report_progress(progress_callback, progress)

        recommendation = self._recommender.analyze_and_recommend(
            video_paths=video_paths,
            progress_callback=lambda p, m: logger.debug(f"[Recommend] {p}% - {m}"),
        )

        progress = OneClickProgress(
            status=OneClickStatus.RECOMMENDING,
            progress=25,
            phase="推荐完成",
            message=f"推荐模式: {recommendation.recommended_mode.value}",
        )
        self._report_progress(progress_callback, progress)

        return recommendation

    def _do_clip(
        self,
        video_paths: List[str],
        project_name: str,
        mode: ClipMode,
        target_duration: Optional[int],
        progress_callback: Optional[Callable],
    ) -> str:
        """执行剪辑"""
        output_path = str(
            self._path_mgr.get_output_path(
                project_name=project_name,
                filename=f"oneclick_{mode.value}_temp.mp4"
            )
        )

        def clip_progress(stage: str, pct: int, msg: str):
            if progress_callback:
                adjusted_pct = 35 + int(pct * 0.3)
                progress = OneClickProgress(
                    status=OneClickStatus.CLIPPING,
                    progress=adjusted_pct,
                    phase=f"剪辑: {stage}",
                    message=msg,
                )
                self._report_progress(progress_callback, progress)

        pipeline = ModularDirectCutPipeline()
        result_path = pipeline.run(
            video_paths=video_paths,
            output_path=output_path,
            target_duration=target_duration,
            project_name=project_name,
            progress_callback=clip_progress,
        )

        return result_path

    def _do_generate_titles(
        self,
        video_path: str,
        recommendation: ModeRecommendation,
        progress_callback: Optional[Callable],
    ) -> TitleGenerationResult:
        """生成标题"""
        content_analysis = {
            "video_type": recommendation.recommended_mode.value,
            "content_summary": f"经过{recommendation.recommended_mode.value}处理的视频",
            "main_plots": recommendation.reasons,
            "characters": [],
            "highlights": recommendation.reasons[:2] if recommendation.reasons else [],
            "duration": recommendation.target_duration or 60,
        }

        def title_progress(pct: int, msg: str):
            if progress_callback:
                adjusted_pct = 65 + int(pct * 0.2)
                progress = OneClickProgress(
                    status=OneClickStatus.GENERATING_TITLES,
                    progress=adjusted_pct,
                    phase="标题生成",
                    message=msg,
                )
                self._report_progress(progress_callback, progress)

        result = self._title_generator.generate(
            content_analysis=content_analysis,
            title_count=8,
            progress_callback=title_progress,
        )

        return result

    def _do_crop(
        self,
        input_path: str,
        project_name: str,
        target_ratio: str,
        progress_callback: Optional[Callable],
    ) -> str:
        """执行裁剪"""
        output_path = str(
            self._path_mgr.get_output_path(
                project_name=project_name,
                filename=f"oneclick_final_{target_ratio.replace(':', 'x')}.mp4"
            )
        )

        if target_ratio == "9:16":
            ratio_value = 9 / 16
        elif target_ratio == "16:9":
            ratio_value = 16 / 9
        else:
            ratio_value = 1.0

        current_ratio = self._get_video_ratio(input_path)

        if abs(current_ratio - ratio_value) < 0.05:
            import shutil
            shutil.copy2(input_path, output_path)
        else:
            smart_crop(
                input_path,
                output_path,
                target_ratio=target_ratio,
                crop_position="smart",
            )

        return output_path

    def _get_video_ratio(self, video_path: str) -> float:
        """获取视频比例"""
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return 16 / 9
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        return width / height if height > 0 else 16 / 9

    def _report_progress(
        self,
        callback: Optional[Callable],
        progress: OneClickProgress,
    ):
        """报告进度"""
        if callback:
            try:
                callback(progress)
            except Exception as e:
                logger.warning(f"[OneClick] 进度回调失败: {e}")


class OneClickPipelineError(Exception):
    """一键处理错误"""
    pass


_global_oneclick: Optional[OneClickPipeline] = None


def get_oneclick_pipeline() -> OneClickPipeline:
    """获取全局一键流水线"""
    global _global_oneclick
    if _global_oneclick is None:
        _global_oneclick = OneClickPipeline()
    return _global_oneclick

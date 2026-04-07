"""
DramaClip - 统一任务调度模块
双模式分流入口: 原片直剪 / AI解说
"""

import json
import os.path
from os import path
from loguru import logger

from app.config import config
from app.config.audio_config import get_recommended_volumes_for_content
from app.models import const
from app.models.schema import VideoClipParams
from app.services import (voice, audio_merger, subtitle_merger, clip_video, merger_video,
                          update_script, generate_video)
from app.services import state as sm
from app.utils import utils


# ============================================================
# DramaClip: 统一任务入口 — 双模式分流
# ============================================================

def start_subclip_unified(task_id: str, params: VideoClipParams):
    """
    DramaClip 统一视频处理入口 - 双模式分流

    根据 clip_mode 自动选择处理流水线：
      - direct_cut (原片直剪): 高光识别 → 排序 → 裁剪 → 拼接输出
      - ai_narration (AI解说): 原有 NarratoAI 流程（脚本+TTS+合成）

    Args:
        task_id: 任务ID
        params: 视频参数（包含 clip_mode 字段）
    """
    clip_mode = getattr(params, 'clip_mode', 'direct_cut')
    logger.info(f"DramaClip task started | mode={clip_mode} | task={task_id}")

    if clip_mode == 'ai_narration':
        # AI解说模式必须提供脚本文件
        if not getattr(params, 'video_clip_json_path', None):
            raise ValueError("AI解说模式需要指定脚本文件路径 (video_clip_json_path)")
        return _run_narration_pipeline(task_id, params)
    elif clip_mode == 'direct_cut':
        return _run_direct_cut_pipeline(task_id, params)
    else:
        logger.error(f"Unknown clip mode: {clip_mode}")
        raise ValueError(f"Unknown clip mode: {clip_mode}")


def _run_direct_cut_pipeline(task_id: str, params: VideoClipParams):
    """
    原片直剪流水线（DramaClip 核心新增）

    支持单集和多集短剧处理：
      - 多集模式：调用 DirectCutPipeline.run() 完整流水线
      - 单集模式：兼容处理单个视频文件

    完整流程:
      1. 镜头分割 (PySceneDetect / FFmpeg)
      2. 多维高光打分 (音频+情绪+画面+节奏)
      3. Top-N 筛选 + 剧集均衡
      4. 智能排序 (剧集顺序 + 情绪递进)
      5. 视频裁剪 + 拼接 + 竖屏输出

    不需要脚本 JSON，不需要 TTS，保留原片原声。
    """
    from app.services.direct_cut.pipeline import DirectCutPipeline
    from app.utils import utils

    logger.info(f"\n\n## [Direct-Cut] Task start: {task_id}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)

    try:
        # ★ 获取多集视频路径列表
        video_paths = getattr(params, 'video_origin_paths', None) or []
        if not video_paths:
            # 兜底：尝试单文件字段
            single_path = getattr(params, 'video_origin_path', None) or ''
            if single_path and path.exists(single_path):
                video_paths = [single_path]
            else:
                raise ValueError("未提供视频文件，请先上传视频")

        # 验证所有文件存在
        missing = [p for p in video_paths if not path.exists(p)]
        if missing:
            raise ValueError(f"以下视频文件不存在:\n" + "\n".join(missing))

        # Read config
        highlight_cfg = config.highlight or {}
        output_cfg = config.output or {}
        target_duration = getattr(params, 'output_duration', output_cfg.get('default_duration', 30))
        aspect_ratio = output_cfg.get('aspect_ratio', '9:16')

        logger.info(f"[Direct-Cut] Input: {len(video_paths)} episode(s), target={target_duration}s")

        def on_progress(progress_01: float, message: str):
            """进度回调 — 转换为百分比更新任务状态"""
            pct = int(progress_01 * 100)
            sm.state.update_task(task_id, progress=pct)

        # ★ 调用已实现的多集 DirectCutPipeline
        pipeline = DirectCutPipeline(config=highlight_cfg)

        # 使用任务目录作为输出目录
        output_dir = utils.task_dir(task_id)

        result = pipeline.run(
            video_paths=video_paths,
            output_duration=target_duration,
            output_dir=output_dir,
            progress_callback=on_progress,
        )

        # 提取结果
        output_path = result.get('output_path', '')

        logger.info(f"[Direct-Cut] Pipeline complete | output={output_path}")
        logger.info(f"[Direct-Cut] Segments: {result.get('segments_count', 0)}, "
                    f"Episodes covered: {result.get('episodes_covered', 0)}")

        # 更新最终状态
        final_video_paths = [output_path] if output_path else []
        combined_video_paths = final_video_paths[:]

        kwargs = {
            "videos": final_video_paths,
            "combined_videos": combined_video_paths,
            "highlight_count": result.get('segments_count', 0),
            "mode": "direct_cut"
        }
        sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs)
        return kwargs

    except Exception as e:
        logger.exception(f"[Direct-Cut] Task {task_id} failed: {e}")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, message=str(e))
        raise


def _run_narration_pipeline(task_id: str, params: VideoClipParams):
    """
    AI 解说流水线（原有 NarratoAI 流程）

    完整流程:
      1. 加载解说脚本 JSON
      2. TTS 生成语音素材
      3. 基于 OST 类型裁剪视频
      4. 合并音频和字幕
      5. 合并视频片段
      6. 最终合成（字幕/BGM/配音/视频）
    """
    logger.info(f"\n\n## [AI-Narration] Task start: {task_id}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)

    try:
        """
        1. Load script
        """
        logger.info("\n\n## 1. Load script")
        video_script_path = params.video_clip_json_path

        if path.exists(video_script_path):
            try:
                with open(video_script_path, "r", encoding="utf-8") as f:
                    list_script = json.load(f)
                    video_list = [i['narration'] for i in list_script]
                    video_ost = [i['OST'] for i in list_script]
                    time_list = [i['timestamp'] for i in list_script]

                    video_script = " ".join(video_list)
                    logger.debug(f"Full narration script: \n{video_script}")
                    logger.debug(f"OST list: \n{video_ost}")
                    logger.debug(f"Timestamp list: \n{time_list}")
            except Exception as e:
                logger.error(f"Failed to read script JSON: {e}")
                raise ValueError("Failed to read script JSON, check format")
        else:
            logger.error(f"Script file not found: {video_script_path}")
            raise ValueError("Script not found! Save script first.")

        """
        2. Generate TTS audio
        """
        logger.info("\n\n## 2. Generate TTS audio by OST type")
        tts_segments = [
            segment for segment in list_script
            if segment['OST'] in [0, 2]
        ]
        logger.debug(f"TTS segments count: {len(tts_segments)}")

        tts_results = voice.tts_multiple(
            task_id=task_id,
            list_script=tts_segments,
            tts_engine=params.tts_engine,
            voice_name=params.voice_name,
            voice_rate=params.voice_rate,
            voice_pitch=params.voice_pitch,
        )

        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

        """
        3. Unified video clipping by OST type
        """
        logger.info("\n\n## 3. Unified video clipping (by OST type)")

        video_clip_result = clip_video.clip_video_unified(
            video_origin_path=params.video_origin_path,
            script_list=list_script,
            tts_results=tts_results
        )

        tts_clip_result = {tts_result['_id']: tts_result['audio_file'] for tts_result in tts_results}
        subclip_clip_result = {
            tts_result['_id']: tts_result['subtitle_file'] for tts_result in tts_results
        }
        new_script_list = update_script.update_script_timestamps(
            list_script, video_clip_result, tts_clip_result, subclip_clip_result
        )

        logger.info(f"Clipping done, processed {len(video_clip_result)} segments")

        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=60)

        """
        4. Merge audio and subtitles
        """
        logger.info("\n\n## 4. Merge audio and subtitles")
        total_duration = sum([script["duration"] for script in new_script_list])
        if tts_segments:
            try:
                merged_audio_path = audio_merger.merge_audio_files(
                    task_id=task_id,
                    total_duration=total_duration,
                    list_script=new_script_list
                )
                logger.info(f"Audio merge OK -> {merged_audio_path}")

                merged_subtitle_path = subtitle_merger.merge_subtitle_files(new_script_list)
                if merged_subtitle_path:
                    logger.info(f"Subtitle merge OK -> {merged_subtitle_path}")
                else:
                    logger.warning("No valid subtitles, generating without subs")
                    merged_subtitle_path = ""
            except Exception as e:
                logger.error(f"Audio/subtitle merge failed: {str(e)}")
                if 'merged_audio_path' not in locals():
                    merged_audio_path = ""
                if 'merged_subtitle_path' not in locals():
                    merged_subtitle_path = ""
        else:
            logger.warning("No audio/subtitle to merge")
            merged_audio_path = ""
            merged_subtitle_path = ""

        """
        5. Merge videos
        """
        final_video_paths = []
        combined_video_paths = []

        combined_video_path = path.join(utils.task_dir(task_id), f"merger.mp4")
        logger.info(f"\n\n## 5. Merge videos -> {combined_video_path}")

        video_clips = []
        for new_script in new_script_list:
            vpath = new_script.get('video')
            if vpath and os.path.exists(vpath):
                video_clips.append(vpath)
            else:
                logger.error(f"Segment {new_script.get('_id')} video missing: {vpath}")

        logger.info(f"Preparing to merge {len(video_clips)} clips")

        merger_video.combine_clip_videos(
            output_video_path=combined_video_path,
            video_paths=video_clips,
            video_ost_list=video_ost,
            video_aspect=params.video_aspect,
            threads=params.n_threads
        )
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=80)

        """
        6. Final composition (subtitles/BGM/voice/video)
        """
        output_video_path = path.join(utils.task_dir(task_id), f"combined.mp4")
        logger.info(f"\n\n## 6. Final compose -> {output_video_path}")

        bgm_path = utils.get_bgm_file()
        optimized_volumes = get_recommended_volumes_for_content('mixed')

        has_original_audio_segments = any(segment['OST'] == 1 for segment in list_script)

        final_tts_volume = (params.tts_volume
                            if hasattr(params, 'tts_volume') and params.tts_volume != 1.0
                            else optimized_volumes['tts_volume'])

        if has_original_audio_segments:
            final_original_volume = 1.0
            logger.info("Original audio segments detected, volume set to 1.0")
        else:
            final_original_volume = (params.original_volume
                                    if hasattr(params, 'original_volume') and params.original_volume != 0.7
                                    else optimized_volumes['original_volume'])

        final_bgm_volume = (params.bgm_volume
                            if hasattr(params, 'bgm_volume') and params.bgm_volume != 0.3
                            else optimized_volumes['bgm_volume'])

        logger.info(f"Volume config - TTS: {final_tts_volume}, "
                    f"Original: {final_original_volume}, BGM: {final_bgm_volume}")

        options = {
            'voice_volume': final_tts_volume,
            'bgm_volume': final_bgm_volume,
            'original_audio_volume': final_original_volume,
            'keep_original_audio': True,
            'subtitle_enabled': params.subtitle_enabled,
            'subtitle_font': params.font_name,
            'subtitle_font_size': params.font_size,
            'subtitle_color': params.text_fore_color,
            'subtitle_bg_color': None,
            'subtitle_position': params.subtitle_position,
            'custom_position': params.custom_position,
            'threads': params.n_threads
        }
        generate_video.merge_materials(
            video_path=combined_video_path,
            audio_path=merged_audio_path,
            subtitle_path=merged_subtitle_path,
            bgm_path=bgm_path,
            output_path=output_video_path,
            options=options
        )

        final_video_paths.append(output_video_path)
        combined_video_paths.append(combined_video_path)

        logger.success(f"[AI-Narration] Task {task_id} complete, "
                       f"generated {len(final_video_paths)} video(s).")

        kwargs = {
            "videos": final_video_paths,
            "combined_videos": combined_video_paths,
            "mode": "ai_narration"
        }
        sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs)
        return kwargs

    except Exception as e:
        logger.exception(f"[AI-Narration] Task {task_id} failed: {e}")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, message=str(e))
        raise


def validate_params(video_path, audio_path, output_file, params):
    """Validate input parameters."""
    if not video_path:
        raise ValueError("Video path cannot be empty")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video not found: {video_path}")

    if audio_path and not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    if not output_file:
        raise ValueError("Output path cannot be empty")

    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir)

    if not params:
        raise ValueError("Params cannot be empty")


if __name__ == "__main__":
    # Quick test entry point
    print("DramaClip Task Module - use via start_subclip_unified()")

"""
分析流水线 - 子进程工作函数
从 manager.py 中提取的 multiprocessing 工作者逻辑。
在 Windows spawn 模式下，此函数必须是模块级可序列化的。
"""

import os
import sys
from pathlib import Path

from loguru import logger


def run_process_analysis(
    task_id: str,
    project_id: str,
    video_id: str,
    video_path: str,
    asr_engine: str,
    asr_model: str,
    asr_device: str,
    asr_enable_emotion: bool,
    asr_enable_audio_events: bool,
    progress_queue,
):
    """
    子进程入口：执行完整的视频分析流程。

    此函数在独立的 multiprocessing.Process 中运行，
    通过 progress_queue 向父进程汇报进度和结果。
    """
    import asyncio

    # 动态把项目路径加到 sys.path 防止 import 失败
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # 初始化应用环境与核心配置
    # （解决 Windows spawn 子进程丢失全局 os.environ 导致的离线模型加载失败问题）
    try:
        from app.init import init_all
        init_all()
    except Exception:
        pass

    # 配置子进程的日志系统
    try:
        from app.backend_main import setup_logging
        setup_logging()
    except Exception:
        pass

    logger.info(f"[WorkerProcess] Starting analysis for task {task_id} on process {os.getpid()}")

    try:
        from app.services.analyze.manager import AnalysisManager

        # 实例化工作者管理器
        manager = AnalysisManager(is_worker=True)

        # 根据启动参数覆盖配置
        manager._asr_engine = asr_engine
        manager._asr_model = asr_model
        manager._asr_device = asr_device
        manager._asr_enable_emotion = asr_enable_emotion
        manager._asr_enable_audio_events = asr_enable_audio_events

        # 重构 asr_service
        if manager._asr_engine == "sensevoice":
            from app.services.analyze.sensevoice_asr import SenseVoiceService
            manager.asr_service = SenseVoiceService(model=manager._asr_model)
        else:
            from app.services.analyze.asr_service import ASRService
            manager.asr_service = ASRService()

        # 准备进度发送器
        def send_queue_progress(progress: int, phase: str, message: str, detail: dict = None):
            try:
                progress_queue.put({
                    "task_id": task_id,
                    "type": "progress",
                    "progress": progress,
                    "phase": phase,
                    "message": message,
                    "detail": detail or {},
                })
            except Exception as q_err:
                logger.error(f"[WorkerProcess] Failed to send queue progress: {q_err}")

        # 创建任务对象
        task = manager.create_task(project_id, video_path)
        task.task_id = task_id
        task.video_id = video_id

        async def run_worker():
            try:
                # Phase 1: 准备音频
                send_queue_progress(5, "preparing", "准备音频文件...")
                audio_path = await manager._extract_audio(task)

                # Phase 2: ASR 语音识别
                send_queue_progress(15, "asr", "正在进行语音识别...")
                asr_result = manager._run_asr(task, audio_path, send_queue_progress)
                task.asr_result = asr_result

                # Phase 3: 说话人分离
                send_queue_progress(30, "diarization", "正在分离说话人...")
                diarization_result = manager._run_diarization(task, audio_path, send_queue_progress)
                task.diarization_result = diarization_result

                # Phase 4: 情绪分析
                send_queue_progress(45, "emotion", "正在分析情绪...")
                emotion_result = manager._run_emotion_analysis(task, asr_result, send_queue_progress)
                task.emotion_result = emotion_result

                # Phase 5: 视觉分析
                send_queue_progress(60, "visual", "正在分析画面特征...")
                visual_result = manager._run_visual_analysis(task, send_queue_progress)
                task.visual_result = visual_result

                # Phase 6: 节奏分析
                send_queue_progress(75, "rhythm", "正在分析音频节奏...")
                rhythm_result = manager._run_rhythm_analysis(task, audio_path, send_queue_progress)
                task.rhythm_result = rhythm_result

                # Phase 6.5: 整合说话人信息到字幕
                send_queue_progress(80, "merge", "正在整合说话人信息...")
                manager._merge_speaker_to_asr(task, asr_result, diarization_result)

                # Phase 7: 高光识别
                send_queue_progress(85, "highlight", "正在识别高光片段...")
                highlights = manager._run_highlight_detection(
                    task, asr_result, emotion_result, visual_result, rhythm_result, diarization_result,
                )
                task.highlight_segments = highlights

                # Phase 8: 保存结果
                send_queue_progress(95, "saving", "正在保存结果...")
                manager._save_results(task)

                # 完成
                progress_queue.put({
                    "task_id": task_id,
                    "type": "completed",
                    "video_id": video_id,
                    "detail": {
                        "video_id": task.video_id,
                        "segments_count": len(asr_result.segments) if asr_result else 0,
                        "speaker_count": diarization_result.speaker_count if diarization_result else 0,
                        "highlights_count": len(highlights),
                    },
                })
            except Exception as e:
                logger.exception(f"[WorkerProcess] Task {task_id} failed: {e}")
                try:
                    progress_queue.put({
                        "task_id": task_id,
                        "type": "failed",
                        "error": str(e),
                    })
                except Exception as q_err:
                    logger.error(f"[WorkerProcess] Failed to send error status: {q_err}")
            finally:
                manager._cleanup_temp_files(task)

        asyncio.run(run_worker())

    except Exception as init_err:
        logger.exception(f"[WorkerProcess] Failed to initialize worker for task {task_id}: {init_err}")
        try:
            progress_queue.put({
                "task_id": task_id,
                "type": "failed",
                "error": f"初始化子进程失败: {init_err}",
            })
        except Exception as q_err:
            logger.error(f"[WorkerProcess] Failed to send initialization error status: {q_err}")

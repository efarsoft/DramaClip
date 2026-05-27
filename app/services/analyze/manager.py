"""
视频分析服务编排器
协调 ASR、情绪分析、视觉分析、节奏分析、说话人分离、高光识别等模块

ASR 引擎配置通过 UnifiedConfig 读取：
    - 配置源：settings.json（主）/ config.toml（备份）
    - engine: faster_whisper | sensevoice
    - model: large-v3 | SenseVoice-large 等
"""

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from dataclasses import dataclass, field
from loguru import logger

from .asr_service import ASRService, ASRResult
from .sensevoice_asr import SenseVoiceService, SenseVoiceResult
from .emotion_service import EmotionService, EmotionAnalysis
from .visual_service import VisualService, VisualAnalysis
from .rhythm_service import RhythmService, RhythmAnalysis
from .speaker_diarization_service import SpeakerDiarizationService, DiarizationResult
from app.utils.ffmpeg_utils import get_ffmpeg_path

# 统一 ASR 结果类型
ASRResultUnion = Union[ASRResult, SenseVoiceResult]


def _get_asr_config() -> Dict[str, Any]:
    """从 UnifiedConfig 读取 ASR 配置（唯一入口）"""
    from app.config.unified_config import config
    return config.get_asr_config()


@dataclass
class AnalysisTask:
    """分析任务"""
    task_id: str
    project_id: str
    video_id: str
    video_path: str
    status: str = "pending"
    progress: int = 0
    phase: str = ""
    message: str = ""
    asr_result: Optional[ASRResultUnion] = None
    emotion_result: Optional[EmotionAnalysis] = None
    visual_result: Optional[VisualAnalysis] = None
    rhythm_result: Optional[RhythmAnalysis] = None
    diarization_result: Optional[DiarizationResult] = None
    highlight_segments: List[Dict] = field(default_factory=list)
    error: Optional[str] = None
    _temp_audio: Optional[Path] = field(default=None, init=False, repr=False)


class AnalysisManager:
    """视频分析管理器"""

    def __init__(self):
        self.tasks: Dict[str, AnalysisTask] = {}
        
        # 根据配置初始化 ASR 服务
        asr_config = _get_asr_config()
        self._asr_engine = asr_config.get("engine", "sensevoice")
        self._asr_model = asr_config.get("model", "SenseVoice-large")
        self._asr_device = asr_config.get("device", "auto")
        self._asr_enable_emotion = asr_config.get("enable_emotion", True)
        self._asr_enable_audio_events = asr_config.get("enable_audio_events", True)
        
        logger.info(f"[AnalysisManager] ASR engine: {self._asr_engine}, model: {self._asr_model}")
        
        if self._asr_engine == "sensevoice":
            self.asr_service = SenseVoiceService(model=self._asr_model)
        else:
            self.asr_service = ASRService()
        
        self.emotion_service = EmotionService()
        self.visual_service = VisualService()
        self.rhythm_service = RhythmService()
        self.diarization_service = SpeakerDiarizationService()
        self._cancel_flags: Dict[str, bool] = {}

# ---------------------------------------------------------------------------
# 子进程工作函数 (Module-Level for multiprocessing serialization on Windows)
# ---------------------------------------------------------------------------
def _run_process_analysis(
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
    import asyncio
    import sys
    import os
    import json
    import tempfile
    import subprocess
    from pathlib import Path
    from loguru import logger

    # 动态把项目路径加到 sys.path 防止 import 失败
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # 初始化应用环境与核心配置（解决 Windows spawn 子进程丢失全局 os.environ 导致的本地离线模型及 VAD 无法物理直读、加载失败问题）
    try:
        from app.init import init_all
        init_all()
    except Exception as init_err:
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
                highlights = manager._run_highlight_detection(task, asr_result, emotion_result, visual_result, rhythm_result)
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
                    }
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


class AnalysisManager:
    """视频分析管理器"""

    def __init__(self, is_worker: bool = False):
        self.tasks: Dict[str, AnalysisTask] = {}
        
        # 根据配置初始化 ASR 服务
        asr_config = _get_asr_config()
        self._asr_engine = asr_config.get("engine", "sensevoice")
        self._asr_model = asr_config.get("model", "SenseVoice-large")
        self._asr_device = asr_config.get("device", "auto")
        self._asr_enable_emotion = asr_config.get("enable_emotion", True)
        self._asr_enable_audio_events = asr_config.get("enable_audio_events", True)
        
        logger.info(f"[AnalysisManager] ASR engine: {self._asr_engine}, model: {self._asr_model}")
        
        if self._asr_engine == "sensevoice":
            self.asr_service = SenseVoiceService(model=self._asr_model)
        else:
            self.asr_service = ASRService()
        
        self.emotion_service = EmotionService()
        self.visual_service = VisualService()
        self.rhythm_service = RhythmService()
        self.diarization_service = SpeakerDiarizationService()
        self._cancel_flags: Dict[str, bool] = {}
        self._max_concurrent_tasks_override = None

        # 智能并发调度队列配置由 max_concurrent_tasks 属性动态提供，实现热更新
        logger.info(f"[AnalysisManager] Max concurrent analysis tasks (unified from settings max_workers): {self.max_concurrent_tasks}")

        # 多进程隔离与状态同步同步队列
        import multiprocessing
        import threading
        self._progress_queue = multiprocessing.Queue()
        self._active_processes: Dict[str, multiprocessing.Process] = {}
        self._progress_callbacks: Dict[str, Callable] = {}

        if not is_worker:
            # 启动后台队列监听线程
            self._listener_thread = threading.Thread(
                target=self._listen_to_progress_queue,
                daemon=True,
                name="AnalysisProgressListener"
            )
            self._listener_thread.start()
            logger.info("[AnalysisManager] Multiprocessing progress listener thread started")

            # 启动后台进程监控守护线程，彻底解决子进程意外退出、崩溃导致的队列卡死问题
            self._monitor_thread = threading.Thread(
                target=self._monitor_active_processes,
                daemon=True,
                name="AnalysisProcessMonitor"
            )
            self._monitor_thread.start()
            logger.info("[AnalysisManager] Background process monitor thread started")

    @property
    def max_concurrent_tasks(self) -> int:
        """动态读取并发任务数，使系统设置中的并发任务数（max_workers）在排队调度中热更新实时生效"""
        if hasattr(self, '_max_concurrent_tasks_override') and self._max_concurrent_tasks_override is not None:
            return self._max_concurrent_tasks_override
        try:
            from app.config.unified_config import config
            return int(config.get("hardware.max_workers", 2))
        except Exception:
            return 2

    @max_concurrent_tasks.setter
    def max_concurrent_tasks(self, value: int):
        """支持设置并发任务数（主要为了兼容单元测试中的直接赋值修改）"""
        self._max_concurrent_tasks_override = value

    def _update_project_status_if_done(self, project_id: str):
        """当项目的所有分析任务均处于终态（完成/失败/取消）时，更新项目整体状态"""
        try:
            # 获取该项目的所有任务
            project_tasks = [t for t in self.tasks.values() if t.project_id == project_id]
            if not project_tasks:
                return

            all_done = True
            has_success = False
            for t in project_tasks:
                if t.status in ("queued", "running"):
                    all_done = False
                    break
                if t.status == "completed":
                    has_success = True

            if all_done:
                from app.services.project.manager_sqlite import get_manager
                mgr = get_manager()
                new_status = "ready" if has_success else "idle"
                mgr.update_project(project_id, {"status": new_status})
                logger.info(f"[AnalysisManager] All tasks for project {project_id} finished. Project status updated to {new_status}")
        except Exception as e:
            logger.error(f"[AnalysisManager] Failed to update project status: {e}")

    def _monitor_active_processes(self):
        """后台轮询监控子进程是否存活的守护线程"""
        logger.info("[AnalysisManager] Background process monitor loop started")
        import time
        while True:
            try:
                time.sleep(1.0)  # 1秒轮询一次
                dead_tasks = []
                # 复制一份以防迭代时字典被修改
                for task_id, process in list(self._active_processes.items()):
                    if process and not process.is_alive():
                        dead_tasks.append((task_id, process.exitcode))
                
                for task_id, exitcode in dead_tasks:
                    task = self.tasks.get(task_id)
                    if task and task.status in ("running", "queued"):
                        logger.error(f"[AnalysisManager] Monitor detected dead process for task {task_id} with exitcode {exitcode}")
                        task.status = "failed"
                        task.error = f"分析进程异常退出 (Exit code: {exitcode})"
                        task.message = f"分析进程异常退出 (Exit code: {exitcode})"
                        
                        # 触发进度回调通知前端
                        callback = self._progress_callbacks.get(task_id)
                        if callback:
                            try:
                                callback({
                                    "task_id": task_id,
                                    "progress": -1,
                                    "phase": "error",
                                    "message": f"分析进程异常退出 (Exit code: {exitcode})",
                                    "detail": {},
                                })
                            except Exception as e:
                                logger.error(f"[AnalysisManager] Error notifying crash via callback: {e}")
                        
                        # 从 active 中移除并触发下一个任务与项目状态更新
                        self._active_processes.pop(task_id, None)
                        self._trigger_next_tasks()
                        self._update_project_status_if_done(task.project_id)
            except Exception as e:
                logger.error(f"[AnalysisManager] Error in background process monitor: {e}")

    def _listen_to_progress_queue(self):
        """监听子进程发出的进度与结果消息并分发"""
        logger.info("[AnalysisManager] Queue listener loop started")
        while True:
            try:
                msg = self._progress_queue.get()
                if msg is None:  # Sentinel to exit
                    break
                self._handle_queue_message(msg)
            except Exception as e:
                logger.error(f"[AnalysisManager] Error in listener queue thread: {e}")

    def _handle_queue_message(self, msg: dict):
        task_id = msg.get("task_id")
        msg_type = msg.get("type")
        
        task = self.tasks.get(task_id)
        if not task:
            logger.warning(f"[AnalysisManager] Received message for unknown task {task_id}")
            return

        if task.status == "cancelled":
            return

        callback = self._progress_callbacks.get(task_id)

        if msg_type == "progress":
            task.progress = msg["progress"]
            task.phase = msg["phase"]
            task.message = msg["message"]
            task.status = "running"
            
            if callback:
                try:
                    callback({
                        "task_id": task_id,
                        "progress": task.progress,
                        "phase": task.phase,
                        "message": task.message,
                        "detail": msg.get("detail", {}),
                    })
                except Exception as cb_err:
                    logger.error(f"[AnalysisManager] Error in progress callback: {cb_err}")

        elif msg_type == "completed":
            try:
                # 从磁盘加载结果
                self._load_results_from_disk(task)
                task.status = "completed"
                task.progress = 100
                task.phase = "completed"
                task.message = "分析完成！"
                
                if callback:
                    try:
                        callback({
                            "task_id": task_id,
                            "progress": 100,
                            "phase": "completed",
                            "message": "分析完成！",
                            "detail": msg.get("detail", {}),
                        })
                    except Exception as cb_err:
                        logger.error(f"[AnalysisManager] Error in completed callback: {cb_err}")
            except Exception as load_err:
                logger.exception(f"[AnalysisManager] Failed to load results from disk for task {task_id}: {load_err}")
                task.status = "failed"
                task.error = f"加载结果失败: {load_err}"
                if callback:
                    try:
                        callback({
                            "task_id": task_id,
                            "progress": task.progress,
                            "phase": "error",
                            "message": f"加载结果失败: {load_err}",
                            "detail": {},
                        })
                    except Exception as cb_err:
                        logger.error(f"[AnalysisManager] Error in failed callback: {cb_err}")
            finally:
                self._active_processes.pop(task_id, None)
                self._trigger_next_tasks()
                self._update_project_status_if_done(task.project_id)

        elif msg_type == "failed":
            task.status = "failed"
            task.error = msg.get("error", "未知错误")
            task.message = f"分析失败: {task.error}"
            
            if callback:
                try:
                    callback({
                        "task_id": task_id,
                        "progress": task.progress,
                        "phase": "error",
                        "message": f"分析失败: {task.error}",
                        "detail": {},
                    })
                except Exception as cb_err:
                    logger.error(f"[AnalysisManager] Error in failed callback: {cb_err}")
            
            self._active_processes.pop(task_id, None)
            self._trigger_next_tasks()
            self._update_project_status_if_done(task.project_id)

    def _load_results_from_disk(self, task: AnalysisTask):
        """从磁盘反序列化结果回 AnalysisTask"""
        output_dir = Path.home() / ".dramaclip" / "analysis" / task.video_id
        if not output_dir.exists():
            raise FileNotFoundError(f"Analysis directory not found: {output_dir}")

        # ASR
        asr_file = output_dir / "asr.json"
        if asr_file.exists():
            asr_data = json.loads(asr_file.read_text(encoding="utf-8"))
            if self._asr_engine == "sensevoice":
                from .sensevoice_asr import SenseVoiceResult, SenseVoiceSegment
                segments = []
                for s in asr_data.get("segments", []):
                    segments.append(SenseVoiceSegment(
                        id=s.get("id", ""),
                        text=s.get("text", ""),
                        start=s.get("start", 0.0),
                        end=s.get("end", 0.0),
                        speaker=s.get("speaker", ""),
                        emotion=s.get("emotion", ""),
                        audio_events=s.get("audio_events", [])
                    ))
                task.asr_result = SenseVoiceResult(
                    segments=segments,
                    language=asr_data.get("language", "zh"),
                    duration=asr_data.get("duration", 0.0)
                )
            else:
                from .asr_service import ASRResult, ASRSegment
                segments = []
                for s in asr_data.get("segments", []):
                    segments.append(ASRSegment(
                        id=s.get("id", ""),
                        text=s.get("text", ""),
                        start=s.get("start", 0.0),
                        end=s.get("end", 0.0),
                        speaker=s.get("speaker", "")
                    ))
                task.asr_result = ASRResult(
                    segments=segments,
                    language=asr_data.get("language", "zh"),
                    duration=asr_data.get("duration", 0.0)
                )

        # Emotion
        emotion_file = output_dir / "emotion.json"
        if emotion_file.exists():
            emotion_data = json.loads(emotion_file.read_text(encoding="utf-8"))
            from .emotion_service import EmotionAnalysis, EmotionPoint
            curve = []
            for p in emotion_data.get("emotion_curve", []):
                curve.append(EmotionPoint(
                    timestamp=p.get("timestamp", 0.0),
                    emotion=p.get("emotion", ""),
                    sub_emotion=p.get("sub_emotion", ""),
                    intensity=p.get("intensity", 0.0),
                    confidence=p.get("confidence", 0.0),
                    context=p.get("context", "")
                ))
            task.emotion_result = EmotionAnalysis(
                video_id=emotion_data.get("video_id", ""),
                overall_emotion=emotion_data.get("overall_emotion", ""),
                overall_intensity=emotion_data.get("overall_intensity", 0.0),
                emotion_curve=curve,
                emotion_distribution=emotion_data.get("emotion_distribution", {}),
                peak_moments=emotion_data.get("peak_moments", []),
                sentiment_summary=emotion_data.get("sentiment_summary", "")
            )

        # Visual
        visual_file = output_dir / "visual.json"
        if visual_file.exists():
            visual_data = json.loads(visual_file.read_text(encoding="utf-8"))
            from .visual_service import VisualAnalysis
            task.visual_result = VisualAnalysis(
                video_id=visual_data.get("video_id", ""),
                duration=visual_data.get("duration", 0.0),
                avg_brightness=visual_data.get("avg_brightness", 0.0),
                avg_contrast=visual_data.get("avg_contrast", 0.0),
                avg_motion=visual_data.get("avg_motion", 0.0),
                avg_sharpness=visual_data.get("avg_sharpness", 0.0),
                total_faces=visual_data.get("total_faces", 0),
                face_ratio=visual_data.get("face_ratio", 0.0),
                frame_scores=visual_data.get("frame_scores", [])
            )

        # Rhythm
        rhythm_file = output_dir / "rhythm.json"
        if rhythm_file.exists():
            rhythm_data = json.loads(rhythm_file.read_text(encoding="utf-8"))
            from .rhythm_service import RhythmAnalysis
            task.rhythm_result = RhythmAnalysis(
                video_id=rhythm_data.get("video_id", ""),
                duration=rhythm_data.get("duration", 0.0),
                avg_bpm=rhythm_data.get("avg_bpm", 0.0),
                bpm_variance=rhythm_data.get("bpm_variance", 0.0),
                avg_energy=rhythm_data.get("avg_energy", 0.0),
                energy_variance=rhythm_data.get("energy_variance", 0.0),
                silence_ratio=rhythm_data.get("silence_ratio", 0.0),
                beat_count=rhythm_data.get("beat_count", 0),
                tempo_changes=rhythm_data.get("tempo_changes", 0),
                rhythm_curve=rhythm_data.get("rhythm_curve", [])
            )

        # Diarization
        diarization_file = output_dir / "diarization.json"
        if diarization_file.exists():
            diar_data = json.loads(diarization_file.read_text(encoding="utf-8"))
            from .speaker_diarization_service import DiarizationResult, SpeakerProfile, SpeakerSegment
            speakers = []
            for s in diar_data.get("speakers", []):
                speakers.append(SpeakerProfile(
                    speaker_id=s.get("speaker_id", ""),
                    avg_pitch=s.get("avg_pitch", 0.0),
                    avg_energy=s.get("avg_energy", 0.0),
                    mfcc_mean=s.get("mfcc_mean", []),
                    segment_count=s.get("segment_count", 0),
                    total_duration=s.get("total_duration", 0.0)
                ))
            segments = []
            for s in diar_data.get("segments", []):
                segments.append(SpeakerSegment(
                    speaker_id=s.get("speaker_id", ""),
                    start=s.get("start", 0.0),
                    end=s.get("end", 0.0),
                    confidence=s.get("confidence", 0.0)
                ))
            task.diarization_result = DiarizationResult(
                video_id=diar_data.get("video_id", ""),
                duration=diar_data.get("duration", 0.0),
                speaker_count=diar_data.get("speaker_count", 0),
                speakers=speakers,
                segments=segments,
                speaker_timeline=diar_data.get("speaker_timeline", [])
            )

        # Highlights
        highlights_file = output_dir / "highlights.json"
        if highlights_file.exists():
            task.highlight_segments = json.loads(highlights_file.read_text(encoding="utf-8"))

    def start_task_process(self, task_id: str, progress_callback: Callable):
        """将任务加入智能并发队列中，并在空闲时通过 multiprocessing.Process 启动它"""
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        self._progress_callbacks[task_id] = progress_callback
        self._cancel_flags[task_id] = False
        task.status = "queued"
        task.progress = 0
        task.phase = "queued"
        task.message = "排队中..."

        # 立即通过 callback 通知前端该任务已进入排队队列
        if progress_callback:
            try:
                progress_callback({
                    "task_id": task_id,
                    "progress": 0,
                    "phase": "queued",
                    "message": "排队中...",
                    "detail": {},
                })
            except Exception as e:
                logger.error(f"[AnalysisManager] Error calling progress callback for queue status: {e}")

        logger.info(f"[AnalysisManager] Task {task_id} added to the analysis queue.")
        self._trigger_next_tasks()

    def _trigger_next_tasks(self):
        """触发队列中的下一个待执行任务"""
        active_count = len(self._active_processes)
        if active_count >= self.max_concurrent_tasks:
            logger.info(f"[AnalysisManager] Concurrency limit reached ({active_count}/{self.max_concurrent_tasks}). Staying in queue.")
            return

        # 寻找排队中的任务
        for task_id, task in self.tasks.items():
            if task.status == "queued" and task_id not in self._active_processes:
                # 找到了可以执行的任务，启动它！
                logger.info(f"[AnalysisManager] Triggering queued task {task_id} (active: {active_count}/{self.max_concurrent_tasks})")
                task.status = "running"
                task.progress = 0
                task.phase = "init"
                task.message = "正在启动独立分析进程..."

                # 通过 callback 刷新前端为运行状态
                callback = self._progress_callbacks.get(task_id)
                if callback:
                    try:
                        callback({
                            "task_id": task_id,
                            "progress": 0,
                            "phase": "init",
                            "message": "正在启动独立分析进程...",
                            "detail": {},
                        })
                    except Exception as e:
                        logger.error(f"[AnalysisManager] Error notifying task running status: {e}")

                import multiprocessing
                
                args = (
                    task_id,
                    task.project_id,
                    task.video_id,
                    task.video_path,
                    self._asr_engine,
                    self._asr_model,
                    self._asr_device,
                    self._asr_enable_emotion,
                    self._asr_enable_audio_events,
                    self._progress_queue
                )

                p = multiprocessing.Process(
                    target=_run_process_analysis,
                    args=args,
                    name=f"DramaClipWorker-{task_id}"
                )
                self._active_processes[task_id] = p
                p.start()
                logger.info(f"[AnalysisManager] Spawned worker process {p.pid} for task {task_id} from queue")
                
                # 递归尝试启动下一个，直到达到并发上限
                self._trigger_next_tasks()
                break

    def create_task(self, project_id: str, video_path: str, video_id: Optional[str] = None) -> AnalysisTask:
        """创建分析任务"""
        task_id = str(uuid.uuid4())
        task = AnalysisTask(
            task_id=task_id,
            project_id=project_id,
            video_id=video_id or str(uuid.uuid4()),
            video_path=video_path,
        )
        self.tasks[task_id] = task
        logger.info(f"Created analysis task: {task_id} (video_id: {task.video_id})")
        return task

    def get_task(self, task_id: str) -> Optional[AnalysisTask]:
        """获取任务"""
        task = self.tasks.get(task_id)
        if task and task.status == "running":
            # 检查关联的子进程是否依然存活，防止子进程意外崩溃导致任务状态卡死
            process = self._active_processes.get(task_id)
            if process and not process.is_alive():
                exitcode = process.exitcode
                logger.error(f"[AnalysisManager] Process for task {task_id} died unexpectedly with exit code {exitcode}")
                task.status = "failed"
                task.error = f"分析进程异常退出 (Exit code: {exitcode})"
                task.message = f"分析进程异常退出 (Exit code: {exitcode})"
                self._active_processes.pop(task_id, None)
                self._trigger_next_tasks()
                self._update_project_status_if_done(task.project_id)
        return task

    def cancel_task(self, task_id: str) -> bool:
        """取消任务并强制关闭子进程"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            task.status = "cancelled"
            self._cancel_flags[task_id] = True
            
            # 强制杀掉多进程，以完美释放 GPU 和 CPU 核心资源
            process = self._active_processes.get(task_id)
            if process:
                try:
                    logger.info(f"Terminating child process for task {task_id}")
                    process.terminate()
                    process.join(timeout=1.0)
                    if process.is_alive():
                        process.kill()
                except Exception as e:
                    logger.warning(f"Error terminating child process: {e}")
                finally:
                    self._active_processes.pop(task_id, None)

            # 清理临时音频文件
            try:
                temp_dir = Path(tempfile.gettempdir()) / "dramaclip_analysis"
                temp_path = temp_dir / f"{task.video_id}.wav"
                if temp_path.exists():
                    temp_path.unlink()
            except Exception as e:
                logger.warning(f"Error cleaning up temp audio upon cancellation: {e}")

            logger.info(f"Cancelled task: {task_id}")
            self._trigger_next_tasks()
            self._update_project_status_if_done(task.project_id)
            return True
        return False

    async def run_analysis(
        self,
        task_id: str,
        progress_callback: Optional[Callable[[Dict], None]] = None,
    ):
        """执行完整的视频分析流程"""
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task not found: {task_id}")

        self._cancel_flags[task_id] = False
        task.status = "running"

        def send_progress(progress: int, phase: str, message: str, detail: Optional[Dict] = None):
            task.progress = progress
            task.phase = phase
            task.message = message
            if progress_callback:
                progress_callback({
                    "task_id": task_id,
                    "progress": progress,
                    "phase": phase,
                    "message": message,
                    "detail": detail or {},
                })

        try:
            # Phase 1: 准备音频
            send_progress(5, "preparing", "准备音频文件...")
            audio_path = await self._extract_audio(task)
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            # Phase 2: ASR 语音识别
            send_progress(15, "asr", "正在进行语音识别...")
            asr_result = self._run_asr(task, audio_path, send_progress)
            task.asr_result = asr_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            # Phase 3: 说话人分离
            send_progress(30, "diarization", "正在分离说话人...")
            diarization_result = self._run_diarization(task, audio_path, send_progress)
            task.diarization_result = diarization_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            # Phase 4: 情绪分析
            send_progress(45, "emotion", "正在分析情绪...")
            emotion_result = self._run_emotion_analysis(task, asr_result, send_progress)
            task.emotion_result = emotion_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            # Phase 5: 视觉分析
            send_progress(60, "visual", "正在分析画面特征...")
            visual_result = self._run_visual_analysis(task, send_progress)
            task.visual_result = visual_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            # Phase 6: 节奏分析
            send_progress(75, "rhythm", "正在分析音频节奏...")
            rhythm_result = self._run_rhythm_analysis(task, audio_path, send_progress)
            task.rhythm_result = rhythm_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            # Phase 6.5: 整合说话人信息到字幕
            send_progress(80, "merge", "正在整合说话人信息...")
            self._merge_speaker_to_asr(task, asr_result, diarization_result)

            # Phase 7: 高光识别
            send_progress(85, "highlight", "正在识别高光片段...")
            highlights = self._run_highlight_detection(task, asr_result, emotion_result, visual_result, rhythm_result)
            task.highlight_segments = highlights

            # Phase 8: 保存结果
            send_progress(95, "saving", "正在保存结果...")
            self._save_results(task)

            # 完成
            send_progress(100, "completed", "分析完成！", {
                "video_id": task.video_id,
                "segments_count": len(asr_result.segments) if asr_result else 0,
                "speaker_count": diarization_result.speaker_count if diarization_result else 0,
                "highlights_count": len(highlights),
            })
            task.status = "completed"
            logger.info(f"Analysis completed: {task_id}")

        except InterruptedError:
            task.status = "cancelled"
            send_progress(task.progress, "cancelled", "分析已取消")
            logger.info(f"Analysis cancelled: {task_id}")

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            send_progress(task.progress, "error", f"分析失败: {e}")
            logger.exception(f"Analysis failed: {task_id}")

        finally:
            self._cleanup_temp_files(task)

    async def _extract_audio(self, task: AnalysisTask) -> Path:
        """提取音频"""
        video_path = Path(task.video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {task.video_path}")

        temp_dir = Path(tempfile.gettempdir()) / "dramaclip_analysis"
        temp_dir.mkdir(exist_ok=True)
        audio_path = temp_dir / f"{task.video_id}.wav"
        task._temp_audio = audio_path

        ffmpeg = get_ffmpeg_path()
        cmd = [
            ffmpeg,
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            str(audio_path),
        ]

        logger.info(f"Extracting audio: {video_path.name}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")

        return audio_path

    def _run_asr(
        self,
        task: AnalysisTask,
        audio_path: Path,
        send_progress: Callable,
    ) -> ASRResultUnion:
        """运行语音识别（支持 Whisper 和 SenseVoice）"""

        def asr_progress(progress: int, message: str):
            # ASR 进度 0-100 映射到整体进度 15-40
            mapped = 15 + int(progress * 0.25)
            send_progress(mapped, "asr", message)

        # 根据引擎类型调用不同的服务
        if self._asr_engine == "sensevoice":
            result = self.asr_service.recognize(
                str(audio_path),
                video_id=task.video_id,
                progress_callback=asr_progress,
                enable_emotion=self._asr_enable_emotion,
                enable_audio_events=self._asr_enable_audio_events,
            )
        else:
            result = self.asr_service.recognize(
                str(audio_path),
                model=self._asr_model,
                video_id=task.video_id,
                progress_callback=asr_progress,
            )
        
        logger.info(f"ASR completed ({self._asr_engine}): {len(result.segments)} segments")
        return result

    def _run_diarization(
        self,
        task: AnalysisTask,
        audio_path: Path,
        send_progress: Callable,
    ) -> DiarizationResult:
        """运行说话人分离"""

        def diarization_progress(progress: int, message: str):
            send_progress(30 + int(progress * 0.10), "diarization", message)

        result = self.diarization_service.diarize(
            str(audio_path),
            video_id=task.video_id,
            progress_callback=diarization_progress,
        )
        logger.info(f"Diarization completed: {result.speaker_count} speakers")
        return result

    def _run_emotion_analysis(
        self,
        task: AnalysisTask,
        asr_result: ASRResult,
        send_progress: Callable,
    ) -> EmotionAnalysis:
        """运行情绪分析"""

        def emotion_progress(progress: int, message: str):
            send_progress(45 + int(progress * 0.10), "emotion", message)

        text_segments = [
            {"text": seg.text, "start": seg.start, "end": seg.end}
            for seg in asr_result.segments
        ]

        result = self.emotion_service.analyze(
            text_segments,
            video_id=task.video_id,
            progress_callback=emotion_progress,
        )
        logger.info(f"Emotion analysis completed: overall={result.overall_emotion}")
        return result

    def _run_visual_analysis(
        self,
        task: AnalysisTask,
        send_progress: Callable,
    ) -> VisualAnalysis:
        """运行视觉分析"""

        def visual_progress(progress: int, message: str):
            send_progress(60 + int(progress * 0.10), "visual", message)

        result = self.visual_service.analyze(
            task.video_path,
            video_id=task.video_id,
            progress_callback=visual_progress,
        )
        logger.info(f"Visual analysis completed: brightness={result.avg_brightness:.2f}, motion={result.avg_motion:.2f}")
        return result

    def _run_rhythm_analysis(
        self,
        task: AnalysisTask,
        audio_path: Path,
        send_progress: Callable,
    ) -> RhythmAnalysis:
        """运行节奏分析"""

        def rhythm_progress(progress: int, message: str):
            send_progress(75 + int(progress * 0.10), "rhythm", message)

        result = self.rhythm_service.analyze(
            str(audio_path),
            video_id=task.video_id,
            progress_callback=rhythm_progress,
        )
        logger.info(f"Rhythm analysis completed: bpm={result.avg_bpm:.1f}, energy={result.avg_energy:.2f}")
        return result

    def _run_highlight_detection(
        self,
        task: AnalysisTask,
        asr_result: ASRResult,
        emotion_result: EmotionAnalysis,
        visual_result: VisualAnalysis,
        rhythm_result: RhythmAnalysis,
    ) -> List[Dict]:
        """运行高光识别"""
        from app.services.highlight.selector import HighlightSelector

        selector = HighlightSelector()
        scored_segments: List[Dict] = []
        video_paths: List[str] = []
        start_times: List[float] = []
        end_times: List[float] = []
        subtitle_texts: List[Optional[str]] = []

        for i, seg in enumerate(asr_result.segments):
            # 情绪分数
            emotion_score = 0.5
            if emotion_result and i < len(emotion_result.emotion_curve):
                ep = emotion_result.emotion_curve[i]
                intensity = ep.intensity if (ep and ep.intensity is not None) else 0.5
                confidence = ep.confidence if (ep and ep.confidence is not None) else 1.0
                try:
                    emotion_score = float(intensity) * float(confidence)
                except (ValueError, TypeError):
                    emotion_score = 0.5

            # 辅助浮点安全转换函数
            def safe_float(val, default):
                if val is None:
                    return default
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return default

            # 视觉分数
            visual_score = 0.5
            if visual_result:
                frame_data = self.visual_service.get_frame_score_at_time(
                    visual_result, seg.start
                )
                if frame_data:
                    visual_score = self.visual_service.calculate_visual_score(
                        brightness=safe_float(frame_data.get("brightness"), 0.5),
                        contrast=safe_float(frame_data.get("contrast"), 0.5),
                        motion=safe_float(frame_data.get("motion_score"), 0.0),
                        face_score=safe_float(frame_data.get("face_score"), 0.0),
                        sharpness=safe_float(frame_data.get("sharpness"), 0.5),
                    )
                else:
                    visual_score = 0.5

            # 节奏分数
            rhythm_score = 0.5
            if rhythm_result:
                point_data = self.rhythm_service.get_rhythm_score_at_time(
                    rhythm_result, seg.start
                )
                if point_data:
                    rhythm_score = self.rhythm_service.calculate_rhythm_score(
                        energy=safe_float(point_data.get("energy"), 0.5),
                        is_beat=bool(point_data.get("is_beat", False)),
                        is_silence=bool(point_data.get("is_silence", False)),
                        bpm_variance=safe_float(rhythm_result.bpm_variance, 0.0),
                    )
                else:
                    rhythm_score = 0.5

            scored_segments.append({
                "audio_score": 0.5,
                "emotion_score": emotion_score,
                "visual_score": visual_score,
                "rhythm_score": rhythm_score,
            })
            video_paths.append(task.video_path)
            start_times.append(seg.start)
            end_times.append(seg.end)
            subtitle_texts.append(seg.text)

        selected = selector.select_from_scores(
            scored_segments=scored_segments,
            video_paths=video_paths,
            start_times=start_times,
            end_times=end_times,
            subtitle_texts=subtitle_texts,
        )

        result = [h.to_dict() for h in selected]
        logger.info(f"Highlight detection completed: {len(result)} highlights")
        return result

    def _save_results(self, task: AnalysisTask):
        """保存分析结果"""
        output_dir = Path.home() / ".dramaclip" / "analysis" / task.video_id
        output_dir.mkdir(parents=True, exist_ok=True)

        if task.asr_result:
            asr_file = output_dir / "asr.json"
            asr_file.write_text(
                json.dumps(task.asr_result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if task.emotion_result:
            emotion_file = output_dir / "emotion.json"
            emotion_file.write_text(
                json.dumps(task.emotion_result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if task.visual_result:
            visual_file = output_dir / "visual.json"
            visual_file.write_text(
                json.dumps(task.visual_result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if task.rhythm_result:
            rhythm_file = output_dir / "rhythm.json"
            rhythm_file.write_text(
                json.dumps(task.rhythm_result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        if task.diarization_result:
            diarization_file = output_dir / "diarization.json"
            diarization_file.write_text(
                json.dumps(task.diarization_result.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        highlight_file = output_dir / "highlights.json"
        highlight_file.write_text(
            json.dumps(task.highlight_segments, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info(f"Results saved to: {output_dir}")

    def _cleanup_temp_files(self, task: AnalysisTask):
        """清理临时文件"""
        if task._temp_audio is not None:
            try:
                if task._temp_audio.exists():
                    task._temp_audio.unlink()
            except Exception as e:
                logger.warning(f"清理临时文件失败: {e}")

    def _get_video_duration(self, video_path: str) -> float:
        """获取视频时长"""
        from app.utils.ffmpeg_utils import get_ffprobe_path

        ffprobe = get_ffprobe_path()
        cmd = [
            ffprobe,
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            try:
                return float(result.stdout.strip())
            except ValueError:
                pass
        return 0.0

    def _merge_speaker_to_asr(
        self,
        task: AnalysisTask,
        asr_result: Optional[ASRResultUnion],
        diarization_result: Optional[DiarizationResult],
    ):
        """
        将说话人信息整合到 ASR 结果中
        
        基于时间重叠度（Overlap）优先，并以中点距离（Distance）为兜底策略，
        为每个字幕片段精确分配说话人标签。
        支持 ASRResult 和 SenseVoiceResult 两种类型
        """
        if not asr_result or not diarization_result:
            logger.warning("ASR 或说话人分离结果为空，跳过整合")
            return
        
        if not diarization_result.segments:
            logger.warning("说话人分离片段为空，跳过整合")
            return
        
        speaker_segments = diarization_result.segments
        speaker_assigned_count = 0
        
        for seg in asr_result.segments:
            # 1. 优先策略：计算 ASR 段与所有说话人段的重叠时长，分给重叠最多的说话人
            overlap_durations = {}  # speaker_id -> float
            for speaker_seg in speaker_segments:
                overlap_start = max(seg.start, speaker_seg.start)
                overlap_end = min(seg.end, speaker_seg.end)
                if overlap_start < overlap_end:
                    overlap_len = overlap_end - overlap_start
                    sp_id = speaker_seg.speaker_id
                    overlap_durations[sp_id] = overlap_durations.get(sp_id, 0.0) + overlap_len
            
            if overlap_durations:
                best_speaker = max(overlap_durations, key=overlap_durations.get)
                seg.speaker = best_speaker
                speaker_assigned_count += 1
            else:
                # 2. 兜底策略：若完全无重叠（如刚好处于静音或对齐空隙），选择中心点距离最近的说话人段
                seg_midpoint = (seg.start + seg.end) / 2.0
                min_dist = float('inf')
                best_speaker = None
                
                for speaker_seg in speaker_segments:
                    sp_midpoint = (speaker_seg.start + speaker_seg.end) / 2.0
                    dist = abs(seg_midpoint - sp_midpoint)
                    if dist < min_dist:
                        min_dist = dist
                        best_speaker = speaker_seg.speaker_id
                
                if best_speaker:
                    seg.speaker = best_speaker
                    speaker_assigned_count += 1
        
        logger.info(f"说话人整合完成: {speaker_assigned_count}/{len(asr_result.segments)} 片段已分配说话人")


# ---------------------------------------------------------------------------
# 全局实例
# ---------------------------------------------------------------------------

_analysis_manager: Optional[AnalysisManager] = None


def get_analysis_manager() -> AnalysisManager:
    """获取分析管理器单例"""
    global _analysis_manager
    if _analysis_manager is None:
        _analysis_manager = AnalysisManager()
    return _analysis_manager

"""
视频分析服务编排器（重构后）
协调 ASR、情绪分析、视觉分析、节奏分析、说话人分离、高光识别等模块。

原 manager.py (1365行) 拆分后，此文件仅保留 AnalysisManager 核心编排逻辑。
"""

import json
import multiprocessing
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from .types import (
    AnalysisTask,
    ASRResultUnion,
    _get_asr_config,
    _get_diarization_config,
)
from .scoring import run_highlight_detection
from .pipeline import run_process_analysis

from .asr_service import ASRService, ASRResult
from .sensevoice_asr import SenseVoiceService, SenseVoiceResult
from .emotion_service import EmotionService, EmotionAnalysis
from .visual_service import VisualService, VisualAnalysis
from .rhythm_service import RhythmService, RhythmAnalysis
from .speaker_diarization_service import SpeakerDiarizationService, DiarizationResult
from app.utils.ffmpeg_utils import get_ffmpeg_path


class AnalysisManager:
    """视频分析管理器"""

    def __init__(self, is_worker: bool = False):
        self.tasks: Dict[str, AnalysisTask] = {}
        self._lock = threading.RLock()

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
        logger.info(f"[AnalysisManager] Max concurrent analysis tasks: {self.max_concurrent_tasks}")

        # 多进程隔离与状态同步队列
        self._progress_queue = multiprocessing.Queue()
        self._active_processes: Dict[str, multiprocessing.Process] = {}
        self._progress_callbacks: Dict[str, Callable] = {}

        if not is_worker:
            # 启动后台队列监听线程
            self._listener_thread = threading.Thread(
                target=self._listen_to_progress_queue,
                daemon=True,
                name="AnalysisProgressListener",
            )
            self._listener_thread.start()
            logger.info("[AnalysisManager] Multiprocessing progress listener thread started")

            # 启动后台进程监控守护线程
            self._monitor_thread = threading.Thread(
                target=self._monitor_active_processes,
                daemon=True,
                name="AnalysisProcessMonitor",
            )
            self._monitor_thread.start()
            logger.info("[AnalysisManager] Background process monitor thread started")

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def max_concurrent_tasks(self) -> int:
        """动态读取并发任务数，支持热更新"""
        if hasattr(self, "_max_concurrent_tasks_override") and self._max_concurrent_tasks_override is not None:
            return self._max_concurrent_tasks_override
        try:
            from app.config.unified_config import config
            return int(config.get("hardware.max_workers", 2))
        except Exception:
            return 2

    @max_concurrent_tasks.setter
    def max_concurrent_tasks(self, value: int):
        """支持直接赋值（兼容单元测试）"""
        self._max_concurrent_tasks_override = value

    # ------------------------------------------------------------------
    # 项目状态管理
    # ------------------------------------------------------------------

    def _update_project_status_if_done(self, project_id: str):
        """当项目的所有分析任务均处于终态时，更新项目整体状态"""
        try:
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
                logger.info(f"[AnalysisManager] Project {project_id} status → {new_status}")
        except Exception as e:
            logger.error(f"[AnalysisManager] Failed to update project status: {e}")

    # ------------------------------------------------------------------
    # 后台线程：进程监控 + 队列监听
    # ------------------------------------------------------------------

    def _monitor_active_processes(self):
        """后台轮询监控子进程是否存活的守护线程"""
        logger.info("[AnalysisManager] Background process monitor loop started")
        import time
        while True:
            try:
                time.sleep(1.0)
                dead_tasks = []
                for task_id, process in list(self._active_processes.items()):
                    if process and not process.is_alive():
                        dead_tasks.append((task_id, process.exitcode))

                for task_id, exitcode in dead_tasks:
                    task = self.tasks.get(task_id)
                    if task and task.status in ("running", "queued"):
                        logger.error(f"[AnalysisManager] Dead process: task={task_id}, exitcode={exitcode}")
                        task.status = "failed"
                        task.error = f"分析进程异常退出 (Exit code: {exitcode})"
                        task.message = task.error

                        callback = self._progress_callbacks.get(task_id)
                        if callback:
                            try:
                                callback({
                                    "task_id": task_id,
                                    "progress": -1,
                                    "phase": "error",
                                    "message": task.error,
                                    "detail": {},
                                })
                            except Exception as e:
                                logger.error(f"[AnalysisManager] Error notifying crash: {e}")

                        self._active_processes.pop(task_id, None)
                        self._trigger_next_tasks()
                        self._update_project_status_if_done(task.project_id)
            except Exception as e:
                logger.error(f"[AnalysisManager] Error in process monitor: {e}")

    def _listen_to_progress_queue(self):
        """监听子进程发出的进度与结果消息并分发"""
        logger.info("[AnalysisManager] Queue listener loop started")
        while True:
            try:
                msg = self._progress_queue.get()
                if msg is None:
                    break
                self._handle_queue_message(msg)
            except Exception as e:
                logger.error(f"[AnalysisManager] Error in listener queue: {e}")

    def _handle_queue_message(self, msg: dict):
        """处理子进程发来的消息"""
        with self._lock:
            task_id = msg.get("task_id")
            msg_type = msg.get("type")

            task = self.tasks.get(task_id)
            if not task:
                logger.warning(f"[AnalysisManager] Unknown task {task_id}")
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
                        logger.error(f"[AnalysisManager] Progress callback error: {cb_err}")

            elif msg_type == "completed":
                try:
                    self._load_results_from_disk(task)
                    task.status = "completed"
                    task.progress = 100
                    task.phase = "completed"
                    task.message = "分析完成！"

                    # 视频重新分析后，失效相关 Narration 缓存
                    try:
                        from app.services.narration.cache import get_narration_cache
                        get_narration_cache().invalidate_for_project(task.project_id)
                    except Exception:
                        pass

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
                            logger.error(f"[AnalysisManager] Completed callback error: {cb_err}")
                except Exception as load_err:
                    logger.exception(f"[AnalysisManager] Load results failed: {load_err}")
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
                        except Exception:
                            pass
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
                    except Exception:
                        pass
                self._active_processes.pop(task_id, None)
                self._trigger_next_tasks()
                self._update_project_status_if_done(task.project_id)

    # ------------------------------------------------------------------
    # 结果持久化 I/O
    # ------------------------------------------------------------------

    def _load_results_from_disk(self, task: AnalysisTask):
        """从磁盘反序列化结果回 AnalysisTask"""
        output_dir = Path.home() / ".dramaclip" / "analysis" / task.project_id / task.video_id
        if not output_dir.exists():
            raise FileNotFoundError(f"Analysis directory not found: {output_dir}")

        # ASR
        asr_file = output_dir / "asr.json"
        if asr_file.exists():
            asr_data = json.loads(asr_file.read_text(encoding="utf-8"))
            if self._asr_engine == "sensevoice":
                from .sensevoice_asr import SenseVoiceResult, SenseVoiceSegment
                segments = [
                    SenseVoiceSegment(
                        id=s.get("id", ""), text=s.get("text", ""),
                        start=s.get("start", 0.0), end=s.get("end", 0.0),
                        speaker=s.get("speaker", ""), emotion=s.get("emotion", ""),
                        audio_events=s.get("audio_events", []),
                    )
                    for s in asr_data.get("segments", [])
                ]
                task.asr_result = SenseVoiceResult(
                    segments=segments,
                    language=asr_data.get("language", "zh"),
                    duration=asr_data.get("duration", 0.0),
                )
            else:
                from .asr_service import ASRResult, ASRSegment
                segments = [
                    ASRSegment(
                        id=s.get("id", ""), text=s.get("text", ""),
                        start=s.get("start", 0.0), end=s.get("end", 0.0),
                        speaker=s.get("speaker", ""),
                    )
                    for s in asr_data.get("segments", [])
                ]
                task.asr_result = ASRResult(
                    segments=segments,
                    language=asr_data.get("language", "zh"),
                    duration=asr_data.get("duration", 0.0),
                )

        # Emotion
        emotion_file = output_dir / "emotion.json"
        if emotion_file.exists():
            emotion_data = json.loads(emotion_file.read_text(encoding="utf-8"))
            from .emotion_service import EmotionAnalysis, EmotionPoint
            curve = [
                EmotionPoint(
                    timestamp=p.get("timestamp", 0.0), emotion=p.get("emotion", ""),
                    sub_emotion=p.get("sub_emotion", ""), intensity=p.get("intensity", 0.0),
                    confidence=p.get("confidence", 0.0), context=p.get("context", ""),
                )
                for p in emotion_data.get("emotion_curve", [])
            ]
            task.emotion_result = EmotionAnalysis(
                video_id=emotion_data.get("video_id", ""),
                overall_emotion=emotion_data.get("overall_emotion", ""),
                overall_intensity=emotion_data.get("overall_intensity", 0.0),
                emotion_curve=curve,
                emotion_distribution=emotion_data.get("emotion_distribution", {}),
                peak_moments=emotion_data.get("peak_moments", []),
                sentiment_summary=emotion_data.get("sentiment_summary", ""),
            )

        # Visual
        visual_file = output_dir / "visual.json"
        if visual_file.exists():
            visual_data = json.loads(visual_file.read_text(encoding="utf-8"))
            task.visual_result = VisualAnalysis(
                video_id=visual_data.get("video_id", ""),
                duration=visual_data.get("duration", 0.0),
                avg_brightness=visual_data.get("avg_brightness", 0.0),
                avg_contrast=visual_data.get("avg_contrast", 0.0),
                avg_motion=visual_data.get("avg_motion", 0.0),
                avg_sharpness=visual_data.get("avg_sharpness", 0.0),
                total_faces=visual_data.get("total_faces", 0),
                face_ratio=visual_data.get("face_ratio", 0.0),
                frame_scores=visual_data.get("frame_scores", []),
            )

        # Rhythm
        rhythm_file = output_dir / "rhythm.json"
        if rhythm_file.exists():
            rhythm_data = json.loads(rhythm_file.read_text(encoding="utf-8"))
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
                rhythm_curve=rhythm_data.get("rhythm_curve", []),
            )

        # Diarization
        diarization_file = output_dir / "diarization.json"
        if diarization_file.exists():
            diar_data = json.loads(diarization_file.read_text(encoding="utf-8"))
            from .speaker_diarization_service import DiarizationResult, SpeakerProfile, SpeakerSegment
            speakers = [
                SpeakerProfile(
                    speaker_id=s.get("speaker_id", ""), avg_pitch=s.get("avg_pitch", 0.0),
                    avg_energy=s.get("avg_energy", 0.0), mfcc_mean=s.get("mfcc_mean", []),
                    segment_count=s.get("segment_count", 0), total_duration=s.get("total_duration", 0.0),
                )
                for s in diar_data.get("speakers", [])
            ]
            segments = [
                SpeakerSegment(
                    speaker_id=s.get("speaker_id", ""), start=s.get("start", 0.0),
                    end=s.get("end", 0.0), confidence=s.get("confidence", 0.0),
                )
                for s in diar_data.get("segments", [])
            ]
            task.diarization_result = DiarizationResult(
                video_id=diar_data.get("video_id", ""),
                duration=diar_data.get("duration", 0.0),
                speaker_count=diar_data.get("speaker_count", 0),
                speakers=speakers, segments=segments,
                speaker_timeline=diar_data.get("speaker_timeline", []),
            )

        # Highlights
        highlights_file = output_dir / "highlights.json"
        if highlights_file.exists():
            task.highlight_segments = json.loads(highlights_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------
    # 任务调度（排队 + 多进程启动）
    # ------------------------------------------------------------------

    def start_task_process(self, task_id: str, progress_callback: Callable):
        """将任务加入智能并发队列，空闲时通过 multiprocessing.Process 启动"""
        with self._lock:
            task = self.get_task(task_id)
            if not task:
                raise ValueError(f"Task not found: {task_id}")

            self._progress_callbacks[task_id] = progress_callback
            self._cancel_flags[task_id] = False
            task.status = "queued"
            task.progress = 0
            task.phase = "queued"
            task.message = "排队中..."

            if progress_callback:
                try:
                    progress_callback({
                        "task_id": task_id, "progress": 0,
                        "phase": "queued", "message": "排队中...", "detail": {},
                    })
                except Exception as e:
                    logger.error(f"[AnalysisManager] Queue callback error: {e}")

            logger.info(f"[AnalysisManager] Task {task_id} queued.")
            self._trigger_next_tasks()

    def _trigger_next_tasks(self):
        """触发队列中的下一个待执行任务"""
        with self._lock:
            while True:
                active_count = len(self._active_processes)
                if active_count >= self.max_concurrent_tasks:
                    break

                triggered_any = False
                for task_id, task in self.tasks.items():
                    if task.status == "queued" and task_id not in self._active_processes:
                        logger.info(f"[AnalysisManager] Triggering task {task_id} ({active_count}/{self.max_concurrent_tasks})")
                        task.status = "running"
                        task.progress = 0
                        task.phase = "init"
                        task.message = "正在启动独立分析进程..."

                        callback = self._progress_callbacks.get(task_id)
                        if callback:
                            try:
                                callback({
                                    "task_id": task_id, "progress": 0,
                                    "phase": "init", "message": "正在启动独立分析进程...", "detail": {},
                                })
                            except Exception:
                                pass

                        args = (
                            task_id, task.project_id, task.video_id, task.video_path,
                            self._asr_engine, self._asr_model, self._asr_device,
                            self._asr_enable_emotion, self._asr_enable_audio_events,
                            self._progress_queue,
                        )
                        p = multiprocessing.Process(
                            target=run_process_analysis,
                            args=args,
                            name=f"DramaClipWorker-{task_id}",
                        )
                        self._active_processes[task_id] = p
                        p.start()
                        logger.info(f"[AnalysisManager] Worker PID={p.pid} for task {task_id}")
                        triggered_any = True
                        break

                if not triggered_any:
                    break

    # ------------------------------------------------------------------
    # 任务 CRUD
    # ------------------------------------------------------------------

    def create_task(
        self,
        project_id: str,
        video_path: str,
        video_id: Optional[str] = None,
        diarization_options: Optional[Dict[str, Any]] = None,
    ) -> AnalysisTask:
        """创建分析任务"""
        task_id = str(uuid.uuid4())
        task = AnalysisTask(
            task_id=task_id,
            project_id=project_id,
            video_id=video_id or str(uuid.uuid4()),
            video_path=video_path,
            diarization_options=diarization_options or {},
        )
        self.tasks[task_id] = task
        logger.info(f"Created analysis task: {task_id} (video_id: {task.video_id})")
        return task

    def get_task(self, task_id: str) -> Optional[AnalysisTask]:
        """获取任务（含进程存活检查）"""
        task = self.tasks.get(task_id)
        if task and task.status == "running":
            process = self._active_processes.get(task_id)
            if process and not process.is_alive():
                exitcode = process.exitcode
                logger.error(f"[AnalysisManager] Dead process: task={task_id}, exit={exitcode}")
                task.status = "failed"
                task.error = f"分析进程异常退出 (Exit code: {exitcode})"
                task.message = task.error
                self._active_processes.pop(task_id, None)
                self._trigger_next_tasks()
                self._update_project_status_if_done(task.project_id)
        return task

    def cancel_task(self, task_id: str) -> bool:
        """取消任务并强制关闭子进程"""
        with self._lock:
            if task_id not in self.tasks:
                return False

            task = self.tasks[task_id]
            task.status = "cancelled"
            self._cancel_flags[task_id] = True

            process = self._active_processes.get(task_id)
            if process:
                try:
                    logger.info(f"Terminating worker for task {task_id}")
                    process.terminate()
                    process.join(timeout=1.0)
                    if process.is_alive():
                        process.kill()
                except Exception as e:
                    logger.warning(f"Error terminating process: {e}")
                finally:
                    self._active_processes.pop(task_id, None)

            # 清理临时音频
            try:
                temp_path = Path(tempfile.gettempdir()) / "dramaclip_analysis" / f"{task.video_id}_{task.task_id}.wav"
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass

            logger.info(f"Cancelled task: {task_id}")
            self._trigger_next_tasks()
            self._update_project_status_if_done(task.project_id)
            return True

    # ------------------------------------------------------------------
    # 进程内分析（非子进程模式）
    # ------------------------------------------------------------------

    async def run_analysis(
        self,
        task_id: str,
        progress_callback: Optional[Callable[[Dict], None]] = None,
    ):
        """执行完整的视频分析流程（进程内模式）"""
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
                    "task_id": task_id, "progress": progress,
                    "phase": phase, "message": message, "detail": detail or {},
                })

        try:
            send_progress(5, "preparing", "准备音频文件...")
            audio_path = await self._extract_audio(task)
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            send_progress(15, "asr", "正在进行语音识别...")
            asr_result = self._run_asr(task, audio_path, send_progress)
            task.asr_result = asr_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            send_progress(30, "diarization", "正在分离说话人...")
            diarization_result = self._run_diarization(task, audio_path, send_progress)
            task.diarization_result = diarization_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            send_progress(45, "emotion", "正在分析情绪...")
            emotion_result = self._run_emotion_analysis(task, asr_result, send_progress)
            task.emotion_result = emotion_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            send_progress(60, "visual", "正在分析画面特征...")
            visual_result = self._run_visual_analysis(task, send_progress)
            task.visual_result = visual_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            send_progress(75, "rhythm", "正在分析音频节奏...")
            rhythm_result = self._run_rhythm_analysis(task, audio_path, send_progress)
            task.rhythm_result = rhythm_result
            if self._cancel_flags.get(task_id):
                raise InterruptedError("Cancelled")

            send_progress(80, "merge", "正在整合说话人信息...")
            self._merge_speaker_to_asr(task, asr_result, diarization_result)

            send_progress(85, "highlight", "正在识别高光片段...")
            highlights = self._run_highlight_detection(
                task, asr_result, emotion_result, visual_result, rhythm_result, diarization_result,
            )
            task.highlight_segments = highlights

            send_progress(95, "saving", "正在保存结果...")
            self._save_results(task)

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

    # ------------------------------------------------------------------
    # 各分析阶段实现
    # ------------------------------------------------------------------

    async def _extract_audio(self, task: AnalysisTask) -> Path:
        """提取音频"""
        video_path = Path(task.video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Video not found: {task.video_path}")

        temp_dir = Path(tempfile.gettempdir()) / "dramaclip_analysis"
        temp_dir.mkdir(exist_ok=True)
        audio_path = temp_dir / f"{task.video_id}_{task.task_id}.wav"
        task._temp_audio = audio_path

        cmd = [
            get_ffmpeg_path(),
            "-i", str(video_path), "-vn",
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-y",
            str(audio_path),
        ]
        logger.info(f"Extracting audio: {video_path.name}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")
        return audio_path

    def _run_asr(self, task: AnalysisTask, audio_path: Path, send_progress: Callable) -> ASRResultUnion:
        """运行语音识别（支持 Whisper 和 SenseVoice）"""
        def asr_progress(progress: int, message: str):
            send_progress(15 + int(progress * 0.25), "asr", message)

        if self._asr_engine == "sensevoice":
            result = self.asr_service.recognize(
                str(audio_path), video_id=task.video_id,
                progress_callback=asr_progress,
                enable_emotion=self._asr_enable_emotion,
                enable_audio_events=self._asr_enable_audio_events,
            )
        else:
            result = self.asr_service.recognize(
                str(audio_path), model=self._asr_model,
                video_id=task.video_id, progress_callback=asr_progress,
            )

        logger.info(f"ASR completed ({self._asr_engine}): {len(result.segments)} segments")
        return result

    def _run_diarization(
        self, task: AnalysisTask, audio_path: Path,
        send_progress: Callable, use_pyannote: Optional[bool] = None,
    ) -> DiarizationResult:
        """运行说话人分离（支持 pyannote 精准模式）"""
        def diarization_progress(progress: int, message: str):
            send_progress(30 + int(progress * 0.10), "diarization", message)

        if use_pyannote is None:
            use_pyannote = task.diarization_options.get("use_pyannote")
        if use_pyannote is None:
            use_pyannote = task.metadata.get("use_pyannote_diarization")
        if use_pyannote is None:
            diarization_config = _get_diarization_config()
            use_pyannote = diarization_config.get("use_pyannote_by_default", False)

        result = self.diarization_service.diarize(
            str(audio_path), video_id=task.video_id,
            progress_callback=diarization_progress, use_pyannote=use_pyannote,
        )
        logger.info(f"Diarization completed: {result.speaker_count} speakers (pyannote={use_pyannote})")
        return result

    def _run_emotion_analysis(self, task: AnalysisTask, asr_result: ASRResultUnion, send_progress: Callable) -> EmotionAnalysis:
        """运行情绪分析"""
        def emotion_progress(progress: int, message: str):
            send_progress(45 + int(progress * 0.10), "emotion", message)

        text_segments = [
            {"text": seg.text, "start": seg.start, "end": seg.end}
            for seg in asr_result.segments
        ]
        result = self.emotion_service.analyze(text_segments, video_id=task.video_id, progress_callback=emotion_progress)
        logger.info(f"Emotion analysis completed: overall={result.overall_emotion}")
        return result

    def _run_visual_analysis(self, task: AnalysisTask, send_progress: Callable) -> VisualAnalysis:
        """运行视觉分析"""
        def visual_progress(progress: int, message: str):
            send_progress(60 + int(progress * 0.10), "visual", message)

        result = self.visual_service.analyze(task.video_path, video_id=task.video_id, progress_callback=visual_progress)
        logger.info(f"Visual analysis completed: brightness={result.avg_brightness:.2f}")
        return result

    def _run_rhythm_analysis(self, task: AnalysisTask, audio_path: Path, send_progress: Callable) -> RhythmAnalysis:
        """运行节奏分析"""
        def rhythm_progress(progress: int, message: str):
            send_progress(75 + int(progress * 0.10), "rhythm", message)

        result = self.rhythm_service.analyze(str(audio_path), video_id=task.video_id, progress_callback=rhythm_progress)
        logger.info(f"Rhythm analysis completed: bpm={result.avg_bpm:.1f}")
        return result

    def _run_highlight_detection(
        self, task: AnalysisTask, asr_result: ASRResultUnion,
        emotion_result: Optional[EmotionAnalysis],
        visual_result: Optional[VisualAnalysis],
        rhythm_result: Optional[RhythmAnalysis],
        diarization_result: Optional[DiarizationResult] = None,
    ) -> List[Dict]:
        """运行高光识别（委托给 scoring 模块）"""
        return run_highlight_detection(
            asr_result=asr_result,
            emotion_result=emotion_result,
            visual_result=visual_result,
            rhythm_result=rhythm_result,
            diarization_result=diarization_result,
            visual_service=self.visual_service,
            rhythm_service=self.rhythm_service,
            video_path=task.video_path,
        )

    # ------------------------------------------------------------------
    # 结果保存与清理
    # ------------------------------------------------------------------

    def _save_results(self, task: AnalysisTask):
        """保存分析结果到磁盘"""
        output_dir = Path.home() / ".dramaclip" / "analysis" / task.project_id / task.video_id
        output_dir.mkdir(parents=True, exist_ok=True)

        _result_map = [
            ("asr.json", task.asr_result),
            ("emotion.json", task.emotion_result),
            ("visual.json", task.visual_result),
            ("rhythm.json", task.rhythm_result),
            ("diarization.json", task.diarization_result),
        ]
        for filename, result in _result_map:
            if result:
                (output_dir / filename).write_text(
                    json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8",
                )

        (output_dir / "highlights.json").write_text(
            json.dumps(task.highlight_segments, ensure_ascii=False, indent=2), encoding="utf-8",
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
        cmd = [
            get_ffprobe_path(), "-v", "quiet",
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
        self, task: AnalysisTask,
        asr_result: Optional[ASRResultUnion],
        diarization_result: Optional[DiarizationResult],
    ):
        """将说话人信息整合到 ASR 结果中（基于时间重叠度优先，中点距离兜底）"""
        if not asr_result or not diarization_result:
            logger.warning("ASR 或说话人分离结果为空，跳过整合")
            return
        if not diarization_result.segments:
            logger.warning("说话人分离片段为空，跳过整合")
            return

        speaker_segments = diarization_result.segments
        speaker_assigned_count = 0

        for seg in asr_result.segments:
            # 策略 1: 时间重叠度优先
            overlap_durations: Dict[str, float] = {}
            for speaker_seg in speaker_segments:
                overlap_start = max(seg.start, speaker_seg.start)
                overlap_end = min(seg.end, speaker_seg.end)
                if overlap_start < overlap_end:
                    sp_id = speaker_seg.speaker_id
                    overlap_durations[sp_id] = overlap_durations.get(sp_id, 0.0) + (overlap_end - overlap_start)

            if overlap_durations:
                seg.speaker = max(overlap_durations, key=overlap_durations.get)
                speaker_assigned_count += 1
            else:
                # 策略 2: 中点距离兜底
                seg_mid = (seg.start + seg.end) / 2.0
                best_speaker = min(
                    speaker_segments,
                    key=lambda ss: abs(seg_mid - (ss.start + ss.end) / 2.0),
                    default=None,
                )
                if best_speaker:
                    seg.speaker = best_speaker.speaker_id
                    speaker_assigned_count += 1

        logger.info(f"说话人整合完成: {speaker_assigned_count}/{len(asr_result.segments)} 片段已分配")


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_analysis_manager: Optional[AnalysisManager] = None


def get_analysis_manager() -> AnalysisManager:
    """获取分析管理器单例"""
    global _analysis_manager
    if _analysis_manager is None:
        _analysis_manager = AnalysisManager()
    return _analysis_manager

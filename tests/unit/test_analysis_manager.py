"""
单元测试 - AnalysisManager 智能并发调度队列
"""

import pytest
from unittest.mock import MagicMock, patch, mock_open
import multiprocessing
from typing import Callable, Optional
from app.services.analyze.manager import AnalysisManager, AnalysisTask


class MockProcess:
    """模拟 multiprocessing.Process"""
    def __init__(self, target, args, name=None):
        self.target = target
        self.args = args
        self.name = name
        self._alive = True
        self.pid = 12345
        self.exitcode = 0

    def start(self):
        pass

    def is_alive(self):
        return self._alive

    def terminate(self):
        self._alive = False

    def join(self, timeout=None):
        self._alive = False

    def kill(self):
        self._alive = False


@pytest.fixture
def mock_services():
    """Mock 所有外部重型模型服务和配置读取，避免实际加载模型和 GPU 初始化"""
    with patch("app.services.analyze.manager._get_asr_config") as mock_cfg, \
         patch("app.services.analyze.manager.ASRService") as mock_asr, \
         patch("app.services.analyze.manager.SenseVoiceService") as mock_sensevoice, \
         patch("app.services.analyze.manager.EmotionService") as mock_emotion, \
         patch("app.services.analyze.manager.VisualService") as mock_visual, \
         patch("app.services.analyze.manager.RhythmService") as mock_rhythm, \
         patch("app.services.analyze.manager.SpeakerDiarizationService") as mock_diarization:
        
        mock_cfg.return_value = {
            "engine": "faster_whisper",
            "model": "large-v3",
            "device": "cpu"
        }
        yield {
            "cfg": mock_cfg,
            "asr": mock_asr,
            "sensevoice": mock_sensevoice,
            "emotion": mock_emotion,
            "visual": mock_visual,
            "rhythm": mock_rhythm,
            "diarization": mock_diarization
        }


class TestAnalysisManagerQueue:
    """测试 AnalysisManager 智能并发调度队列"""

    @patch("multiprocessing.Process", side_effect=MockProcess)
    def test_queue_limit(self, mock_process, mock_services):
        """测试并发调度队列：超出并发上限的任务自动排队"""
        # 实例化，并传入 is_worker=True 避免启动后台监听线程
        manager = AnalysisManager(is_worker=True)
        manager.max_concurrent_tasks = 2

        # 创建 3 个任务
        t1 = manager.create_task("proj_1", "v1.mp4")
        t2 = manager.create_task("proj_1", "v2.mp4")
        t3 = manager.create_task("proj_1", "v3.mp4")

        # 启动三个任务
        cb = MagicMock()
        manager.start_task_process(t1.task_id, cb)
        manager.start_task_process(t2.task_id, cb)
        manager.start_task_process(t3.task_id, cb)

        # 验证并发上限是否生效
        assert t1.status == "running"
        assert t2.status == "running"
        assert t3.status == "queued"
        
        assert len(manager._active_processes) == 2
        assert t1.task_id in manager._active_processes
        assert t2.task_id in manager._active_processes
        assert t3.task_id not in manager._active_processes

    @patch("multiprocessing.Process", side_effect=MockProcess)
    @patch("app.services.analyze.manager.AnalysisManager._load_results_from_disk")
    def test_auto_scheduling_on_completion(self, mock_load, mock_process, mock_services):
        """测试自动调度：当有任务运行完成后，排队中的任务自动调度执行"""
        manager = AnalysisManager(is_worker=True)
        manager.max_concurrent_tasks = 2

        t1 = manager.create_task("proj_1", "v1.mp4")
        t2 = manager.create_task("proj_1", "v2.mp4")
        t3 = manager.create_task("proj_1", "v3.mp4")

        cb = MagicMock()
        manager.start_task_process(t1.task_id, cb)
        manager.start_task_process(t2.task_id, cb)
        manager.start_task_process(t3.task_id, cb)

        # 初始状态
        assert t3.status == "queued"

        # 模拟 t1 完成并发送 message 给 handle_queue_message
        msg = {
            "task_id": t1.task_id,
            "type": "completed",
            "video_id": t1.video_id,
            "detail": {}
        }
        manager._handle_queue_message(msg)

        # 验证 t1 已完成，t3 被自动调度启动
        assert t1.status == "completed"
        assert t3.status == "running"
        assert len(manager._active_processes) == 2
        assert t1.task_id not in manager._active_processes
        assert t3.task_id in manager._active_processes

    @patch("multiprocessing.Process", side_effect=MockProcess)
    def test_crash_recovery_triggers_next_task(self, mock_process, mock_services):
        """测试进程崩溃恢复：当子进程意外死亡，get_task 应该检测到并标记失败，同时自动调度队列中下一个任务"""
        manager = AnalysisManager(is_worker=True)
        manager.max_concurrent_tasks = 2

        t1 = manager.create_task("proj_1", "v1.mp4")
        t2 = manager.create_task("proj_1", "v2.mp4")
        t3 = manager.create_task("proj_1", "v3.mp4")

        cb = MagicMock()
        manager.start_task_process(t1.task_id, cb)
        manager.start_task_process(t2.task_id, cb)
        manager.start_task_process(t3.task_id, cb)

        # 获取 t1 的进程，并将其模拟为死亡/崩溃状态
        p1 = manager._active_processes[t1.task_id]
        p1._alive = False
        p1.exitcode = 127

        # 轮询获取任务状态触发崩溃检测
        fetched = manager.get_task(t1.task_id)

        # 验证崩溃检测与自动调度
        assert fetched.status == "failed"
        assert "异常退出" in fetched.error
        assert t1.task_id not in manager._active_processes
        
        # 验证排队的任务已自动被调度执行
        assert t3.status == "running"
        assert t3.task_id in manager._active_processes

    @patch("multiprocessing.Process", side_effect=MockProcess)
    def test_cancellation_triggers_next_task(self, mock_process, mock_services):
        """测试取消任务：取消运行中的任务，能安全终止其进程并立刻调度下一个排队任务"""
        manager = AnalysisManager(is_worker=True)
        manager.max_concurrent_tasks = 2

        t1 = manager.create_task("proj_1", "v1.mp4")
        t2 = manager.create_task("proj_1", "v2.mp4")
        t3 = manager.create_task("proj_1", "v3.mp4")

        cb = MagicMock()
        manager.start_task_process(t1.task_id, cb)
        manager.start_task_process(t2.task_id, cb)
        manager.start_task_process(t3.task_id, cb)

        p1 = manager._active_processes[t1.task_id]
        assert p1.is_alive() is True

        # 取消运行中的 t1 任务
        success = manager.cancel_task(t1.task_id)

        assert success is True
        assert t1.status == "cancelled"
        assert p1.is_alive() is False  # 验证进程被终止
        assert t1.task_id not in manager._active_processes

        # 验证 t3 已被立刻调度启动
        assert t3.status == "running"
        assert t3.task_id in manager._active_processes

    @patch("multiprocessing.Process", side_effect=MockProcess)
    def test_cancellation_of_queued_task(self, mock_process, mock_services):
        """测试取消排队中的任务：取消尚在排队队列中的任务时，能正确更新状态，且不影响正在运行的任务"""
        manager = AnalysisManager(is_worker=True)
        manager.max_concurrent_tasks = 2

        t1 = manager.create_task("proj_1", "v1.mp4")
        t2 = manager.create_task("proj_1", "v2.mp4")
        t3 = manager.create_task("proj_1", "v3.mp4")

        cb = MagicMock()
        manager.start_task_process(t1.task_id, cb)
        manager.start_task_process(t2.task_id, cb)
        manager.start_task_process(t3.task_id, cb)

        # 初始状态
        assert t3.status == "queued"

        # 取消处于排队中的 t3
        success = manager.cancel_task(t3.task_id)

        assert success is True
        assert t3.status == "cancelled"
        assert t3.task_id not in manager._active_processes
        
        # 验证运行中的任务依然在正常运行
        assert t1.status == "running"
        assert t2.status == "running"
        assert len(manager._active_processes) == 2

"""
单元测试 - TaskManager
测试任务管理器
"""

import pytest
import time
from app.services.task_manager import (
    TaskManager,
    TaskStatus,
    TaskInfo,
    get_task_manager,
)


class TestTaskManager:
    """TaskManager 测试"""

    def test_create_task(self):
        """测试创建任务"""
        mgr = TaskManager(max_concurrent=2)

        task_id = mgr.create_task(metadata={"type": "clip"})

        assert task_id is not None
        task = mgr.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.PENDING
        assert task.metadata.get("type") == "clip"

    def test_create_task_with_id(self):
        """测试创建带指定ID的任务"""
        mgr = TaskManager()

        task_id = mgr.create_task(task_id="custom-id-123", metadata={"type": "clip"})

        assert task_id == "custom-id-123"
        task = mgr.get_task(task_id)
        assert task is not None
        assert task.task_id == "custom-id-123"

    def test_get_task(self):
        """测试获取任务"""
        mgr = TaskManager()

        created_id = mgr.create_task()
        fetched = mgr.get_task(created_id)

        assert fetched is not None
        assert fetched.task_id == created_id

    def test_update_task(self):
        """测试更新任务"""
        mgr = TaskManager()

        task_id = mgr.create_task()

        mgr.update_task(
            task_id,
            status=TaskStatus.RUNNING,
            progress=50,
            phase="scene_detection",
            message="场景检测中...",
        )

        updated = mgr.get_task(task_id)
        assert updated is not None

        assert updated.status == TaskStatus.RUNNING
        assert updated.progress == 50
        assert updated.phase == "scene_detection"
        assert updated.message == "场景检测中..."

    def test_start_task(self):
        """测试启动任务"""
        mgr = TaskManager(max_concurrent=2)

        task_id = mgr.create_task()

        started = mgr.start_task(task_id)

        assert started is True

        task = mgr.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None

    def test_concurrent_limit(self):
        """测试并发限制"""
        mgr = TaskManager(max_concurrent=2)

        # 创建 3 个任务
        task_ids = [mgr.create_task() for _ in range(3)]

        # 启动前 2 个
        mgr.start_task(task_ids[0])
        mgr.start_task(task_ids[1])

        # 第三个应该失败（达到并发限制）
        started = mgr.start_task(task_ids[2])

        assert started is False

    def test_complete_task(self):
        """测试完成任务"""
        mgr = TaskManager(max_concurrent=2)

        task_id = mgr.create_task()
        mgr.start_task(task_id)

        result = mgr.complete_task(
            task_id,
            output_path="/path/to/output.mp4",
        )

        assert result is True
        task = mgr.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.progress == 100
        assert task.output_path == "/path/to/output.mp4"
        assert task.completed_at is not None

    def test_fail_task(self):
        """测试任务失败"""
        mgr = TaskManager()

        task_id = mgr.create_task()

        mgr.fail_task(task_id, "Video file not found")
        task = mgr.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.error == "Video file not found"

    def test_cancel_task(self):
        """测试取消任务"""
        mgr = TaskManager()

        task_id = mgr.create_task()
        mgr.start_task(task_id)

        cancelled = mgr.cancel_task(task_id)

        assert cancelled is True
        task = mgr.get_task(task_id)
        assert task is not None
        assert task.status == TaskStatus.CANCELLED

    def test_list_tasks(self):
        """测试列出任务"""
        mgr = TaskManager()

        # 创建多个任务
        for i in range(5):
            mgr.create_task()

        tasks = mgr.list_tasks()

        assert len(tasks) == 5

    def test_list_tasks_by_status(self):
        """测试按状态过滤任务"""
        mgr = TaskManager()

        # 创建并完成一些任务
        for _ in range(3):
            task_id = mgr.create_task()
            mgr.start_task(task_id)
            mgr.complete_task(task_id)

        # 创建一些待处理的任务
        for _ in range(2):
            mgr.create_task()

        completed = mgr.list_tasks(status=TaskStatus.COMPLETED)
        pending = mgr.list_tasks(status=TaskStatus.PENDING)

        assert len(completed) == 3
        assert len(pending) == 2

    def test_task_duration(self):
        """测试任务时长计算"""
        mgr = TaskManager()

        task_id = mgr.create_task()
        mgr.start_task(task_id)

        # 模拟一些处理
        time.sleep(0.1)
        task = mgr.get_task(task_id)
        assert task is not None
        assert task.duration is not None
        assert task.duration >= 0.1


class TestTaskInfo:
    """TaskInfo 数据类测试"""

    def test_to_dict(self):
        """测试转换为字典"""
        task = TaskInfo(
            task_id="test-123",
            metadata={"type": "clip"},
        )

        data = task.to_dict()

        assert data["task_id"] == "test-123"
        assert data["status"] == "pending"

    def test_duration_property(self):
        """测试时长属性"""
        import time

        task = TaskInfo(
            task_id="test-123",
            started_at=time.time() - 10,
        )

        # 还未完成
        assert task.duration is not None
        assert task.duration >= 10

        # 标记完成
        task.completed_at = time.time()

        # 时长应该不变
        duration = task.duration
        assert duration >= 10


class TestGetTaskManager:
    """get_task_manager 单例测试"""

    def test_returns_same_instance(self):
        """测试返回相同实例"""
        mgr1 = get_task_manager()
        mgr2 = get_task_manager()

        assert mgr1 is mgr2

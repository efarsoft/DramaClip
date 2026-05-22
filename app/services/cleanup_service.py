"""
自动资源清理服务
P0 核心功能：确保临时文件和缓存被及时清理

功能：
1. 定期清理过期临时文件
2. 根据磁盘使用量自动清理
3. 在磁盘空间不足时紧急清理
4. 提供手动清理接口
"""

import threading
import time
from typing import Optional
from loguru import logger

from app.utils.path_manager import get_path_manager
from app.config.unified_config import config


class AutoCleanupService:
    """
    自动资源清理服务

    在后台线程中定期执行清理任务，确保：
    1. 临时文件不会无限堆积
    2. 磁盘空间不会被耗尽
    3. 清理任务不会影响主业务流程
    """

    _instance: Optional["AutoCleanupService"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._path_mgr = get_path_manager()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 300  # 默认5分钟检查一次
        self._max_temp_age_hours = 24  # 临时文件最大保留时间
        self._max_disk_usage_gb = 10.0  # 最大磁盘使用量
        self._initialized = True

        logger.info("[AutoCleanup] 初始化自动清理服务")

    def configure(
        self,
        interval_seconds: int = 300,
        max_temp_age_hours: int = 24,
        max_disk_usage_gb: float = 10.0
    ) -> None:
        """
        配置清理服务

        Args:
            interval_seconds: 检查间隔（秒）
            max_temp_age_hours: 临时文件最大保留时间（小时）
            max_disk_usage_gb: 最大磁盘使用量（GB）
        """
        self._interval = interval_seconds
        self._max_temp_age_hours = max_temp_age_hours
        self._max_disk_usage_gb = max_disk_usage_gb

        logger.info(
            f"[AutoCleanup] 配置: interval={interval_seconds}s, "
            f"max_age={max_temp_age_hours}h, max_disk={max_disk_usage_gb}GB"
        )

    def start(self) -> None:
        """启动自动清理服务"""
        if self._running:
            logger.warning("[AutoCleanup] 服务已在运行")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        logger.info("[AutoCleanup] 启动自动清理服务")

    def stop(self) -> None:
        """停止自动清理服务"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

        logger.info("[AutoCleanup] 停止自动清理服务")

    def _run_loop(self) -> None:
        """清理循环"""
        while self._running:
            try:
                self._cleanup_once()
            except Exception as e:
                logger.error(f"[AutoCleanup] 清理任务失败: {e}")

            time.sleep(self._interval)

    def _cleanup_once(self) -> None:
        """执行一次清理"""
        # 1. 清理过期临时文件
        count1 = self._path_mgr.cleanup_old_temp_files(self._max_temp_age_hours)
        if count1 > 0:
            logger.info(f"[AutoCleanup] 清理了 {count1} 个过期临时文件")

        # 2. 根据磁盘使用量清理
        count2 = self._path_mgr.cleanup_by_disk_usage(self._max_disk_usage_gb)
        if count2 > 0:
            logger.info(f"[AutoCleanup] 根据磁盘使用量清理了 {count2} 个文件")

        # 3. 清理所有注册的临时文件
        stats = self._path_mgr.cleanup_all()
        if stats["success"] > 0:
            logger.info(
                f"[AutoCleanup] 清理了 {stats['success']} 个注册临时文件"
                f"({stats['failed']} 个失败)"
            )

    def manual_cleanup(self) -> dict:
        """
        手动执行清理

        Returns:
            清理统计信息
        """
        logger.info("[AutoCleanup] 执行手动清理")

        old_count = self._path_mgr.cleanup_old_temp_files(self._max_temp_age_hours)
        disk_count = self._path_mgr.cleanup_by_disk_usage(self._max_disk_usage_gb)
        registered_stats = self._path_mgr.cleanup_all()

        return {
            "old_files_cleaned": old_count,
            "disk_based_cleaned": disk_count,
            "registered_cleaned": registered_stats["success"],
            "disk_usage": self._path_mgr.get_disk_usage()
        }

    def get_status(self) -> dict:
        """
        获取清理服务状态

        Returns:
            状态信息字典
        """
        return {
            "running": self._running,
            "interval_seconds": self._interval,
            "max_temp_age_hours": self._max_temp_age_hours,
            "max_disk_usage_gb": self._max_disk_usage_gb,
            "disk_usage": self._path_mgr.get_disk_usage(),
            "registered_temp_files": len(self._path_mgr._temp_files)
        }


# 全局单例
_service: Optional[AutoCleanupService] = None


def get_cleanup_service() -> AutoCleanupService:
    """获取自动清理服务实例"""
    global _service
    if _service is None:
        _service = AutoCleanupService()
    return _service


def start_cleanup_service(
    interval_seconds: int = 300,
    max_temp_age_hours: int = 24,
    max_disk_usage_gb: float = 10.0
) -> AutoCleanupService:
    """
    启动自动清理服务

    Args:
        interval_seconds: 检查间隔（秒）
        max_temp_age_hours: 临时文件最大保留时间（小时）
        max_disk_usage_gb: 最大磁盘使用量（GB）

    Returns:
        AutoCleanupService 实例
    """
    service = get_cleanup_service()
    service.configure(
        interval_seconds=interval_seconds,
        max_temp_age_hours=max_temp_age_hours,
        max_disk_usage_gb=max_disk_usage_gb
    )
    service.start()
    return service


def stop_cleanup_service() -> None:
    """停止自动清理服务"""
    service = get_cleanup_service()
    service.stop()

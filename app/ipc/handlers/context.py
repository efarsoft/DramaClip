"""
Handler 依赖注入容器
提供统一的服务实例管理和依赖注入
"""

from typing import Optional, Any
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class HandlerContext:
    """
    Handler 依赖容器

    集中管理所有服务实例，支持依赖注入和测试替换
    """
    project_manager: Any = field(default=None)
    analysis_manager: Any = field(default=None)
    clip_manager: Any = field(default=None)
    config: Any = field(default=None)

    _initialized: bool = field(default=False, repr=False)

    def initialize(self):
        """初始化所有服务实例"""
        if self._initialized:
            return

        from app.services.project.manager_sqlite import get_manager
        from app.services.analyze.manager import AnalysisManager
        from app.config.unified_config import config

        self.project_manager = get_manager()
        self.analysis_manager = AnalysisManager()
        self.config = config

        self._initialized = True
        logger.info("[HandlerContext] Initialized all services")

    def get_project_manager(self) -> Any:
        """获取项目管理器实例"""
        if not self._initialized:
            self.initialize()
        return self.project_manager

    def get_analysis_manager(self) -> Any:
        """获取分析管理器实例"""
        if not self._initialized:
            self.initialize()
        return self.analysis_manager

    def get_config(self) -> Any:
        """获取配置实例"""
        if not self._initialized:
            self.initialize()
        return self.config

    def reset(self):
        """重置所有服务实例（用于测试）"""
        self.project_manager = None
        self.analysis_manager = None
        self.clip_manager = None
        self._initialized = False
        logger.info("[HandlerContext] Reset all services")


# 全局单例
_global_context: Optional[HandlerContext] = None


def get_handler_context() -> HandlerContext:
    """获取全局 Handler 上下文"""
    global _global_context
    if _global_context is None:
        _global_context = HandlerContext()
        _global_context.initialize()
    return _global_context


def reset_handler_context():
    """重置全局 Handler 上下文（用于测试）"""
    global _global_context
    if _global_context is not None:
        _global_context.reset()
    _global_context = None

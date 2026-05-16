"""
Router 单元测试
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import MagicMock

# 确保 app 在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.ipc.router import Router


@pytest.fixture
def router():
    """创建路由器实例"""
    return Router()


class TestRouter:
    """Router 测试"""

    def test_register_and_resolve(self, router):
        """注册后应能解析方法"""
        handler = MagicMock(return_value="result")
        router.register("project", "list", handler)

        resolved = router.resolve("project.list")
        assert resolved is handler

    def test_resolve_not_found(self, router):
        """未注册的方法应返回 None"""
        resolved = router.resolve("nonexistent.method")
        assert resolved is None

    def test_list_methods(self, router):
        """应列出所有已注册的方法"""
        handler1 = MagicMock()
        handler2 = MagicMock()

        router.register("project", "list", handler1)
        router.register("project", "create", handler2)

        methods = router.list_methods()
        assert "project.list" in methods
        assert "project.create" in methods
        assert len(methods) == 2

    def test_unregister(self, router):
        """取消注册后应无法解析"""
        handler = MagicMock()
        router.register("project", "list", handler)

        assert router.resolve("project.list") is handler

        router.unregister("project", "list")
        assert router.resolve("project.list") is None

    def test_unregister_not_existing(self, router):
        """取消注册不存在的方法不应报错"""
        router.unregister("nonexistent", "method")  # 不应抛出异常

    def test_multiple_namespaces(self, router):
        """不同命名空间的同名方法应能共存"""
        handler1 = MagicMock(return_value="result1")
        handler2 = MagicMock(return_value="result2")

        router.register("project", "list", handler1)
        router.register("analyze", "list", handler2)

        assert router.resolve("project.list") is handler1
        assert router.resolve("analyze.list") is handler2

    def test_overwrite_handler(self, router):
        """重复注册应覆盖旧处理器"""
        handler1 = MagicMock(return_value="result1")
        handler2 = MagicMock(return_value="result2")

        router.register("project", "list", handler1)
        router.register("project", "list", handler2)

        assert router.resolve("project.list") is handler2
        assert len(router.list_methods()) == 1

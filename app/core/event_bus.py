"""
进程内 pub/sub 事件总线（参考 OmniVoice-Studio backend/core/event_bus.py）

用途：
- 后端代码在任何状态变更时调用 emit(kind, payload)
- IPC 服务器注册监听器，将事件转发给前端（通过 IPC notification）
- 未来迁移到 WebSocket/SSE 时只需替换传输层

事件类型（kind）：
- project_updated     项目数据变更
- analysis_progress   分析进度更新
- clip_progress       剪辑进度更新
- export_progress     导出进度更新
- task_status         任务状态变更
- model_status        模型下载/加载状态
- settings_changed    设置变更
- system_error        系统级错误（需前端展示引导）
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from loguru import logger


# 监听器注册表：kind -> [callback]
_listeners: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
_lock = threading.Lock()


def subscribe(kind: str, callback: Callable[[Dict[str, Any]], None]) -> None:
    """
    订阅指定类型的事件

    Args:
        kind: 事件类型（如 'project_updated'）
        callback: 回调函数，接收事件 payload 字典
    """
    with _lock:
        if kind not in _listeners:
            _listeners[kind] = []
        if callback not in _listeners[kind]:
            _listeners[kind].append(callback)
            logger.debug(f"[EventBus] 已订阅: {kind}")


def unsubscribe(kind: str, callback: Callable[[Dict[str, Any]], None]) -> None:
    """取消订阅"""
    with _lock:
        if kind in _listeners:
            try:
                _listeners[kind].remove(callback)
            except ValueError:
                pass


def emit(kind: str, payload: Optional[Dict[str, Any]] = None) -> None:
    """
    广播事件到所有监听者

    安全调用：同步/异步上下文均可使用。
    失败隔离：单个监听器的异常不影响其他监听器。

    Args:
        kind: 事件类型
        payload: 事件数据（可选）
    """
    event = {
        "kind": kind,
        "ts": time.time(),
        **(payload or {}),
    }

    with _lock:
        callbacks = list(_listeners.get(kind, []))
        # 通配符监听器（监听所有事件）
        callbacks.extend(_listeners.get("*", []))

    for cb in callbacks:
        try:
            cb(event)
        except Exception as e:
            logger.warning(f"[EventBus] 监听器执行失败 ({kind}): {e}")


def emit_json(kind: str, payload: Optional[Dict[str, Any]] = None) -> str:
    """
    广播事件并返回 JSON 字符串（用于 IPC notification）

    Returns:
        事件的 JSON 字符串表示
    """
    event = {
        "kind": kind,
        "ts": time.time(),
        **(payload or {}),
    }
    event_str = json.dumps(event, ensure_ascii=False)

    # 同步触发监听器
    with _lock:
        callbacks = list(_listeners.get(kind, []))
        callbacks.extend(_listeners.get("*", []))

    for cb in callbacks:
        try:
            cb(event)
        except Exception as e:
            logger.warning(f"[EventBus] 监听器执行失败 ({kind}): {e}")

    return event_str


def list_subscriptions() -> Dict[str, int]:
    """列出当前所有订阅（调试用）"""
    with _lock:
        return {kind: len(cbs) for kind, cbs in _listeners.items()}


def clear_all() -> None:
    """清空所有订阅（测试用）"""
    with _lock:
        _listeners.clear()

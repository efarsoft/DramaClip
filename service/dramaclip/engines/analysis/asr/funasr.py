"""funasr 双路径装配（E-2）：进程内优先（dev/测试），冻结态走 tts-venv worker。

自 transcriber.py 拆出（拆分专项）：打包态主包不含 torch/funasr（build-service
excludes），此时 funasr 从本地智能运行环境（tts-venv）的 worker 进程获得；
dev 装了 ml 组或测试桩在 sys.modules 里放了 funasr 时走进程内真 import——
两个分支对引擎只暴露同一个 .generate() 形状。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager import worker_bridge

_LOGGER = logging.getLogger(__name__)


class _FunasrWorker:
    """venv 内 funasr AutoModel 的进程代理：``.generate(**kwargs)`` 与真模型同形。

    生命周期跟引擎实例（AnalysisRuntime 缓存单例 → 全应用一个 worker），进程
    统一在 service_app 退出时由桥的 shutdown 回收——不收会在 Windows 上留占着
    模型内存的孤儿进程（indextts2 同款教训）。
    """

    def __init__(self, config: dict[str, Any]) -> None:
        from dramaclip.engines.tts.workers import funasr_worker

        self._config = dict(config)
        self._inner = worker_bridge.VenvWorker(Path(funasr_worker.__file__), config)
        self.device = "cpu"
        self.ready: dict[str, Any] = {}

    def start(self) -> None:
        ready = self._inner.start()
        self.ready = dict(ready)
        self.device = str(ready.get("device") or "cpu")

    def generate(self, **kwargs: Any) -> list:  # type: ignore[type-arg]
        try:
            return self._call(kwargs)
        except RuntimeError as exc:
            # worker 进程死亡（原生崩溃/OOM）不该连坐本批剩余每一集：
            # 就地重生一次再试；再挂如实上抛（那时的错误仍是可读的人话）。
            # 重生以「意外退出」错误为唯一触发——每次调用至多重生一次，
            # 重试再挂就按单集失败上报，不在同一请求里无限循环。
            if "意外退出" not in str(exc):
                raise
            _LOGGER.warning("funasr worker 已退出，重启后重试本次请求")
            self._inner.close()
            fresh = _spawn_funasr_worker(self._config)
            self._inner = fresh._inner
            self.ready = fresh.ready
            self.device = fresh.device
            return self._call(kwargs)

    def _call(self, kwargs: dict[str, Any]) -> list:  # type: ignore[type-arg]
        payload = {**kwargs, "input": str(kwargs.get("input", ""))}
        msg = self._inner.request({"kwargs": payload})
        if not msg.get("ok"):
            raise RuntimeError(f"funasr 转写失败: {msg.get('error')}")
        return list(msg.get("raw") or [])

    @property
    def _proc(self) -> Any:
        return self._inner.proc  # 测试断言用：shutdown 后为 None


def shutdown_funasr_workers() -> None:
    """service_app 退出钩子（薄别名）：回收 funasr/kokoro 等全部 venv worker。"""
    worker_bridge.shutdown_venv_workers()


def _spawn_funasr_worker(config: dict[str, Any]) -> _FunasrWorker:
    worker = _FunasrWorker(config)
    worker_bridge.register_venv_worker(worker._inner)
    worker.start()
    return worker


def _inproc_funasr() -> Any:
    """进程内 funasr.AutoModel；不可用返回 None（调用方走 venv worker 并给引导文案）。"""
    try:
        from funasr import AutoModel  # ml extras 懒加载/测试桩
    except ImportError:
        return None
    return AutoModel

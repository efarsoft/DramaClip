"""慢探测结果的「先回旧值、后台刷新」缓存。

给「算一次要十几到几十秒」的探测用（子进程 import、联网自检这类）。直接套
TTL 缓存有两个毛病：过期后第一个调用方同步等满一次探测；并发的几个调用方各
等各的、同时起好几份探测（2026-11-26 实锤：同一秒两条 44.6s/44.7s）。
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import cast


class _Entry[T]:
    __slots__ = ("probed_at", "value")

    def __init__(self, value: T, probed_at: float) -> None:
        self.value = value
        self.probed_at = probed_at


class _Flight[T]:
    """在途的一次探测：等它的调用方从这取结果。"""

    __slots__ = ("done", "error", "generation", "value")

    def __init__(self, generation: int) -> None:
        self.generation = generation
        self.done = threading.Event()
        self.value: T | None = None
        self.error: BaseException | None = None


class StaleWhileRevalidate[T]:
    """按键缓存慢探测：命中即回，过期后由**单个**后台线程刷新。

    - 冷启动（没有旧值）：同步探一次；同键的并发调用等在途的那次，不重复起探测。
    - 过期：立刻回旧值，只派一个后台线程刷新。
    - 探测失败：保留旧值，并把这次尝试记作已探测——重试频率同样是一个 ``ttl_s``
      一次，不会每来一个调用就再探一遍。冷启动时失败则原样抛给调用方。
    - ``invalidate``：作废旧值；在途的那次作废（探测中途世界变了，结果不采纳）。
    """

    def __init__(
        self,
        probe: Callable[[str], T],
        *,
        ttl_s: float,
        thread_name: str = "stale-refresh",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._probe = probe
        self._ttl_s = ttl_s
        self._thread_name = thread_name
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry[T]] = {}
        self._flights: dict[str, _Flight[T]] = {}
        self._generations: dict[str, int] = {}

    def get(self, key: str) -> T:
        with self._lock:
            entry = self._entries.get(key)
            inflight = self._flights.get(key)
            if entry is not None:
                expired = self._clock() - entry.probed_at >= self._ttl_s
                if not expired or inflight is not None:
                    return entry.value  # 没过期，或已有刷新在途
                inflight = _Flight(self._generations.get(key, 0))
                self._flights[key] = inflight
                self._spawn(key, inflight)
                return entry.value
            if inflight is None:
                flight: _Flight[T] = _Flight(self._generations.get(key, 0))
                self._flights[key] = flight
                compute_here = True  # 冷启动：本次调用自己探
            else:
                flight = inflight
                compute_here = False  # 等在途的那次，不重复探
        if compute_here:
            self._refresh(key, flight)  # 探测在锁外跑，别的调用方照回旧值
        flight.done.wait()
        if flight.error is not None:
            raise flight.error
        return cast(T, flight.value)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._entries.pop(key, None)
            self._generations[key] = self._generations.get(key, 0) + 1

    def _spawn(self, key: str, flight: _Flight[T]) -> None:
        """调用方须已持锁。起不了线程就撤掉这次在途：旧值照回，下个调用再试。"""
        try:
            threading.Thread(
                target=self._refresh, args=(key, flight), daemon=True, name=self._thread_name
            ).start()
        except RuntimeError:
            self._flights.pop(key, None)

    def _refresh(self, key: str, flight: _Flight[T]) -> None:
        try:
            try:
                flight.value = self._probe(key)
            except BaseException as exc:  # noqa: BLE001 - 失败交给等结果的调用方/旧值
                flight.error = exc
            with self._lock:
                self._flights.pop(key, None)
                if flight.generation != self._generations.get(key, 0):
                    return  # 探测中途被 invalidate：结果不采纳
                entry = self._entries.get(key)
                if flight.error is None:
                    self._entries[key] = _Entry(cast(T, flight.value), self._clock())
                elif entry is not None:
                    entry.probed_at = self._clock()  # 失败也计一次探测（退避）
        finally:
            flight.done.set()

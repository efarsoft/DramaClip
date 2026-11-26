"""慢探测缓存：命中即回、过期后台刷新且单飞、作废。全部用假时钟与闸门做确定性验证。"""

from __future__ import annotations

import threading

from dramaclip.infra.stale_cache import StaleWhileRevalidate


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _drained() -> None:
    """等后台刷新线程收尾。"""
    for thread in threading.enumerate():
        if thread.name == "stale-refresh":
            thread.join(timeout=5)


def test_cold_miss_computes_once_then_serves_from_cache() -> None:
    clock = _Clock()
    calls: list[str] = []
    cache = StaleWhileRevalidate(
        lambda key: calls.append(key) or len(calls), ttl_s=60.0, clock=clock
    )

    assert cache.get("a") == 1
    clock.now += 59.0
    assert cache.get("a") == 1
    assert calls == ["a"], "TTL 内不再探"


def test_expired_returns_stale_and_refreshes_once_in_background() -> None:
    clock = _Clock()
    calls: list[str] = []
    second_started = threading.Event()
    gate = threading.Event()

    def probe(key: str) -> str:
        calls.append(key)
        if len(calls) == 1:
            return "v1"
        second_started.set()
        gate.wait(5)  # 第二次探测算得慢：卡到测试放行为止
        return "v2"

    cache = StaleWhileRevalidate(probe, ttl_s=60.0, clock=clock)
    assert cache.get("k") == "v1"
    clock.now += 61.0

    assert cache.get("k") == "v1", "过期先回旧值，不等探测"
    assert cache.get("k") == "v1", "刷新在途：照回旧值"
    assert second_started.wait(5), "后台确实派了刷新"
    assert calls == ["k", "k"], "在途时不再派第二个探测（单飞）"
    gate.set()
    _drained()
    assert cache.get("k") == "v2"


def test_cold_start_concurrent_callers_share_one_probe() -> None:
    calls: list[str] = []
    entered = threading.Event()
    release = threading.Event()

    def probe(key: str) -> str:
        calls.append(key)
        entered.set()
        release.wait(5)
        return "v"

    cache = StaleWhileRevalidate(probe, ttl_s=60.0, clock=_Clock())
    results: list[str] = []
    workers = [
        threading.Thread(target=lambda: results.append(cache.get("k"))) for _ in range(4)
    ]
    for worker in workers:
        worker.start()
    assert entered.wait(5)
    release.set()
    for worker in workers:
        worker.join(timeout=5)

    assert results == ["v"] * 4
    assert calls == ["k"], "四个调用方同时冷启，只起一份探测"


def test_refresh_failure_keeps_old_value_and_backs_off() -> None:
    clock = _Clock()
    calls: list[str] = []

    def probe(key: str) -> str:
        calls.append(key)
        if len(calls) == 1:
            return "v1"
        raise OSError("探测坏了")

    cache = StaleWhileRevalidate(probe, ttl_s=60.0, clock=clock)
    assert cache.get("k") == "v1"
    clock.now += 61.0
    assert cache.get("k") == "v1"
    _drained()
    assert cache.get("k") == "v1"
    assert calls == ["k", "k"], "失败也算探过一次：一个 TTL 内不再连探"
    clock.now += 61.0
    assert cache.get("k") == "v1"
    _drained()
    assert len(calls) == 3, "过了 TTL 才再试"


def test_cold_failure_raises_to_caller() -> None:
    def probe(_key: str) -> str:
        raise OSError("起不来")

    cache = StaleWhileRevalidate(probe, ttl_s=60.0, clock=_Clock())
    try:
        cache.get("k")
    except OSError as exc:
        assert str(exc) == "起不来"
    else:
        raise AssertionError("冷启动没有旧值可回：失败原样抛给调用方")


def test_invalidate_drops_value_and_rejects_inflight_result() -> None:
    clock = _Clock()
    calls: list[str] = []
    second_started = threading.Event()
    gate = threading.Event()

    def probe(key: str) -> str:
        calls.append(key)
        if len(calls) == 1:
            return "v1"
        if len(calls) == 2:
            second_started.set()
            gate.wait(5)  # 这次探测中途世界变了（被 invalidate）
            return "过期结果"
        return "v3"

    cache = StaleWhileRevalidate(probe, ttl_s=60.0, clock=clock)
    assert cache.get("k") == "v1"
    clock.now += 61.0
    assert cache.get("k") == "v1"  # 派出刷新
    assert second_started.wait(5)

    cache.invalidate("k")
    gate.set()
    _drained()

    assert cache.get("k") == "v3", "作废后重探；在途那次的结果不采纳"
    assert calls == ["k", "k", "k"]

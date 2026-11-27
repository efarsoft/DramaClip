"""阶段耗时记账：分析这类多段长流程的归因仪表。

为什么要有它：真机批次跑完只能看到「每集约 N 分钟」，归因不到转写/OCR/视觉/
语义各自占多少——优化无从下手。StageClock 用 ``with`` 包住每个阶段，最后
``summary()`` 出一行人读账面进日志面板与 backend.log。

只记账不改行为：阶段内抛异常照常上抛（耗时照记），取消/失败路径由调用方
既有的日志兜底，不额外发薄账。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager


class StageClock:
    """按出现顺序记各阶段秒数；``summary()`` 出单行人读账面。

    ``clock`` 可注入（测试用假时钟做确定性断言）；同名阶段出现多次就记多条，
    汇总时不合并——先后各跑一次的同一个阶段，账面上就该是两笔。
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.spans: list[tuple[str, float]] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = self._clock()
        try:
            yield
        finally:
            self.spans.append((name, self._clock() - started))

    def summary(self) -> str:
        """「转写 3.2m / OCR 41s / 语义 58s」——分钟起进位，秒级不凑零头。"""
        parts = []
        for name, seconds in self.spans:
            rendered = f"{name} {seconds / 60:.1f}m" if seconds >= 60 else f"{name} {seconds:.0f}s"
            parts.append(rendered)
        return " / ".join(parts)

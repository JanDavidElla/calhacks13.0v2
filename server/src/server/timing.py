from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter


class Timings:
    """Collects stage durations for the Server-Timing response header."""

    def __init__(self) -> None:
        self.durations_ms: dict[str, float] = {}

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        start = perf_counter()
        try:
            yield
        finally:
            self.durations_ms[stage] = (perf_counter() - start) * 1000

    def header(self) -> str:
        return ", ".join(f"{stage};dur={ms:.0f}" for stage, ms in self.durations_ms.items())

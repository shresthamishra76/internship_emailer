"""collect_from: parallel fetching keeps source order and isolates failures."""

import threading
import time

from src.main import collect_from
from src.models import Job
from src.sources.base import Source


class _Src(Source):
    def __init__(self, name, n, delay=0.0, crash=False):
        self.name, self.n, self.delay, self.crash = name, n, delay, crash
        self.thread = None

    def fetch(self, session):
        self.thread = threading.get_ident()
        time.sleep(self.delay)
        if self.crash:
            raise RuntimeError("boom")
        return [Job(company=self.name, title=f"t{i}", url=f"https://x/{self.name}/{i}") for i in range(self.n)]


def test_collect_from_preserves_order_and_runs_in_parallel():
    srcs = [_Src("a", 2, delay=0.3), _Src("b", 1), _Src("c", 3, delay=0.3)]
    t0 = time.monotonic()
    jobs = collect_from(srcs, workers=3)
    elapsed = time.monotonic() - t0
    assert [j.company for j in jobs] == ["a", "a", "b", "c", "c", "c"]
    assert elapsed < 0.5  # sequential would be >= 0.6
    assert len({s.thread for s in srcs}) > 1


def test_collect_from_serial_when_one_worker():
    srcs = [_Src("a", 1), _Src("b", 2)]
    assert [j.company for j in collect_from(srcs, workers=1)] == ["a", "b", "b"]


def test_collect_from_isolates_crashing_source():
    srcs = [_Src("a", 1), _Src("bad", 0, crash=True), _Src("c", 1)]
    assert [j.company for j in collect_from(srcs, workers=4)] == ["a", "c"]

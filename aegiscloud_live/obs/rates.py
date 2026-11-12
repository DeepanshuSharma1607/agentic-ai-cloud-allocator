"""
rates.py - "how many per second, lately?" for any event (a request sent, answered, failed ...).

ROLE
    The sender and the counter both need a fair "per second" number that does not jump around. This tiny helper keeps one
    bucket per second for the last two minutes and averages over a window you choose. Because both apps use the same
    helper, their per-second numbers can be compared side by side on the pages.

HOW IT WORKS
    add()            call it each time the event happens
    per_second(n)    the counts of the last n COMPLETE seconds, oldest first (0 where nothing happened)
    rate(n)          their average = events per second over the last n seconds

REMEMBER
    - The current, unfinished second is left out so the number is stable. That means the rate lags real life by about 1 s.
    - It stores only counts (no request details), so it costs almost nothing, even at thousands of events per second.

TEST    python -m pytest tests/test_part2.py -q
"""
from __future__ import annotations

import time
from collections import deque

KEEP_S = 120


class RateWindow:
    def __init__(self, keep_s: int = KEEP_S):
        self.keep_s = keep_s
        self.buckets: deque = deque()                       # [second, count]

    def add(self, n: int = 1) -> None:
        sec = int(time.time())
        if self.buckets and self.buckets[-1][0] == sec:
            self.buckets[-1][1] += n
            return
        self.buckets.append([sec, n])
        while self.buckets and self.buckets[0][0] < sec - self.keep_s:
            self.buckets.popleft()

    def per_second(self, seconds: int = 10) -> list[int]:
        last = int(time.time()) - 1
        have = {sec: n for sec, n in self.buckets}
        return [have.get(s, 0) for s in range(last - seconds + 1, last + 1)]

    def rate(self, seconds: int = 10) -> float:
        counts = self.per_second(seconds)
        return round(sum(counts) / max(len(counts), 1), 1)

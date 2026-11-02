import random

import settings as S
from traffic.loadgen.plans import Planner


def planner():
    return Planner(random.Random(0))


def test_fixed_and_idle():
    p = planner()
    assert p.count({"mode": "fixed", "n": 300}, 0) == 300
    assert p.count({"mode": "idle"}, 0) == 0


def test_cap_is_enforced():
    assert planner().count({"mode": "fixed", "n": 10 ** 9}, 0) == S.MAX_REQUESTS_PER_TICK


def test_random_stays_in_range():
    p = planner()
    vals = [p.count({"mode": "random", "lo": 50, "hi": 80}, 0) for _ in range(200)]
    assert min(vals) >= 50 and max(vals) <= 80


def test_pattern_follows_the_day_curve():
    p = planner()
    plan = {"mode": "pattern", "noise": 0.0, "burst_prob": 0.0}
    peak = max(range(S.DAY), key=lambda m: p.profile[m])
    trough = min(range(S.DAY), key=lambda m: p.profile[m])
    assert p.count(plan, peak) > p.count(plan, trough)


def test_bursts_multiply_traffic():
    p = planner()
    plan = {"mode": "pattern", "noise": 0.0, "burst_prob": 1.0, "burst_mult": 4.0}
    quiet = Planner(random.Random(0)).count({"mode": "pattern", "noise": 0.0, "burst_prob": 0.0}, 100)
    assert p.count(plan, 100) >= 3.5 * quiet


def test_schedule_overrides_base():
    from traffic.loadgen.engine import LoadEngine
    import time
    e = LoadEngine()
    e.set_base({"mode": "fixed", "n": 10})
    e.add_segment({"mode": "fixed", "n": 500}, duration_s=60, start_ts=time.time() - 1)
    label, plan, _ = e.active(time.time())
    assert plan["n"] == 500 and label.startswith("schedule#")
    e.add_segment({"mode": "fixed", "n": 5}, duration_s=60, start_ts=time.time() + 100)     # future one must not apply
    assert e.active(time.time())[1]["n"] == 500
    e.stop()
    assert e.active(time.time())[1]["mode"] == "idle" and e.segments == []

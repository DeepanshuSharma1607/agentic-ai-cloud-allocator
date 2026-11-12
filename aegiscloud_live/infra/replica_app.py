"""
replica_app.py - the app that runs inside every replica (container, Pod or local process).

It IS your existing demo app (traffic/target_app/app.py), unchanged, with one difference: the CPU the app burns per request is
measured in CPU time (process_time), not wall-clock time. With a wall-clock burn, a container whose CPU share is limited would
not get slower, so "splitting the CPU" would change nothing. With CPU time, a replica limited to 0.5 core really handles
half as many requests, which is what a real service does.
"""
import time

from traffic.target_app import app as _base


def _cpu_burn(ms):
    end = time.process_time() + ms / 1000.0
    while time.process_time() < end:
        pass


_base._burn = _cpu_burn          # /work calls _burn(...) by name, so this replaces it inside the unchanged app
app = _base.app

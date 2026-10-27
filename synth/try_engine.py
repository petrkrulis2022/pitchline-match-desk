"""Run the engine for a few seeds and print match-level statistics."""
import sys
import time
from collections import Counter

from engine import Sim

HOME = {"code": "RMA", "name": "Redmoor Athletic", "kit": "#b3261e", "str": 1.04}
AWAY = {"code": "STB", "name": "Stonebridge Town", "kit": "#1f4e9c", "str": 0.97}


def summarize(sim):
    ev = sim.events
    c = Counter((e["type"], e["team"]) for e in ev)
    passes = {t["code"]: (c[("pass", t["code"])]) for t in sim.teams}
    shots = {t["code"]: c[("shot", t["code"])] for t in sim.teams}
    tot = sum(passes.values()) or 1
    return {
        "score": [t["score"] for t in sim.teams],
        "passes": passes, "poss%": {k: round(100 * v / tot) for k, v in passes.items()},
        "shots": shots, "corners": {t["code"]: c[("corner_awarded", t["code"])] for t in sim.teams},
        "fouls": {t["code"]: c[("foul", t["code"])] for t in sim.teams},
        "cards": [(e["period"], int(e["t"] // 60), e["team"], e["detail"]["card"]) for e in ev if e["type"] == "card"],
        "subs": c[("substitution", "RMA")] + c[("substitution", "STB")],
        "var": [e["detail"]["reason"] for e in ev if e["type"] == "var"],
        "offsides": c[("offside", "RMA")] + c[("offside", "STB")],
        "events": len(ev), "added": [e["detail"]["minutes"] for e in ev if e["type"] == "added_time"],
        "end_clock": [round(e["t"] / 60, 1) for e in ev if e["type"] == "period_end"],
    }


if __name__ == "__main__":
    seeds = [int(s) for s in sys.argv[1:]] or [1]
    for s in seeds:
        t0 = time.time()
        sim = Sim(s, HOME, AWAY, record_tracking=False).run()
        print(s, round(time.time() - t0, 1), "s", summarize(sim))

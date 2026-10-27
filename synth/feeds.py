"""Turn the engine's ground truth into the three feeds a real pipeline would see.

1. events feed: event types as a collector would log them, stamped late and delivered with push latency
2. vision feed: per-frame detections in pitch coordinates, with missed players, a flaky ball and non-wide shots
3. truth: exact events and squads, used only to check the other feeds

The noise levels are illustrative: events stamped a few seconds late, a ball that is rarely found and about nine in ten
players found. They are not measurements of any provider.
"""
import json
import random
from pathlib import Path

from engine import Sim, L, W


def clock_str(period, t):
    s = int(t) + (45 * 60 if period == 2 else 0)
    return f"{s // 60}:{s % 60:02d}"


def build_events_feed(sim, seed):
    rng = random.Random(seed + 1000)
    wanted = {"goal", "shot", "save", "foul", "card", "corner_awarded", "offside", "tackle", "interception", "clearance",
              "substitution", "var", "period_start", "period_end", "added_time", "penalty_awarded", "block", "pass",
              "free_kick_awarded", "throw_in_awarded", "goal_kick_awarded", "ball_recovery"}
    roles = {pl.pid: pl.role for t in sim.teams for pl in t["all"]}
    starters = {t["code"]: [pl for pl in t["all"][:11] if pl.role in ("DF", "MF")] for t in sim.teams}

    def collector_credit(e):
        """Defensive actions are credited to a defender or midfielder, the one lined up closest across the pitch."""
        pid = e["player"]
        if e["type"] in ("interception", "tackle", "clearance") and roles.get(pid) == "FW":
            return min(starters[e["team"]], key=lambda pl: abs(pl.slot_y - e["y"])).pid
        return pid

    items = []
    for e in sim.events:
        e = dict(e)
        if e["type"] == "interception" and e["id"] % 8 != 0:
            e["type"] = "ball_recovery"
        if e["type"] not in wanted:
            continue
        r = rng.random()
        lag = rng.uniform(0.5, 2.5) if r < 0.70 else rng.uniform(2.5, 5.0) if r < 0.95 else rng.uniform(5.0, 9.0)
        if e["type"] in ("period_start", "period_end", "added_time"):
            lag = rng.uniform(0.0, 1.0)
        late_card = e["type"] == "card" and rng.random() < 0.15
        if late_card:
            lag += rng.uniform(120, 260)
        stamped = e["t"] + lag
        delivered = stamped + rng.uniform(0.4, 2.2)
        detail = {k: v for k, v in e["detail"].items() if k != "cancelled"}
        items.append({
            "event_id": e["id"], "period": e["period"], "clock": clock_str(e["period"], stamped), "stamped_sec": round(stamped, 1),
            "delivered_sec": round(delivered, 1), "type": e["type"], "team": e["team"], "player": collector_credit(e),
            "x": e["x"], "y": e["y"], "detail": detail, "late_card": late_card,
        })
    items.sort(key=lambda i: (i["period"], i["delivered_sec"]))
    for n, it in enumerate(items, start=1):
        it["seq"] = n
    return items


def build_vision_feed(sim, seed, every_sec=2.0):
    rng = random.Random(seed + 2000)
    tr = sim.tracking
    stride = 4 + 44
    frames = len(tr) // stride
    non_wide = []
    for e in sim.events:
        if e["type"] == "goal":
            non_wide += [(e["period"], e["t"] + 1, e["t"] + 12, "close"), (e["period"], e["t"] + 12, e["t"] + 32, "replay")]
        elif e["type"] == "card":
            non_wide.append((e["period"], e["t"] + 1, e["t"] + 9, "close"))
        elif e["type"] in ("foul", "substitution", "var") and rng.random() < 0.6:
            non_wide.append((e["period"], e["t"] + 1, e["t"] + 6, "close"))
        elif e["type"] == "save" or (e["type"] == "shot" and e["detail"].get("outcome") in ("post", "off_target")):
            non_wide.append((e["period"], e["t"] + 9, e["t"] + 19, "replay"))
    for period in (1, 2):
        t = rng.uniform(20, 60)
        while t < 45 * 60 + 240:
            non_wide.append((period, t, t + rng.uniform(4, 9), "close"))
            t += rng.uniform(35, 80)
    out = []
    step = int(every_sec / 0.1)
    for f in range(0, frames, step):
        base = f * stride
        period, t, bx, by = int(tr[base]), tr[base + 1], tr[base + 2], tr[base + 3]
        shot = "wide"
        for (p, a, b, kind) in non_wide:
            if p == period and a <= t < b:
                shot = kind
                break
        frame = {"period": period, "t": round(t, 1), "clock": clock_str(period, t), "shot": shot, "players": [], "ball": None}
        if shot == "wide":
            for ti, team in enumerate(sim.teams):
                for k in range(11):
                    px, py = tr[base + 4 + (ti * 11 + k) * 2], tr[base + 5 + (ti * 11 + k) * 2]
                    if px < 0 or abs(px - bx) > 40 or rng.random() > 0.90:
                        continue
                    label = team["code"] if rng.random() > 0.06 else sim.teams[1 - ti]["code"]
                    frame["players"].append({"x": round(px + rng.gauss(0, 1.0), 1), "y": round(py + rng.gauss(0, 1.0), 1), "team": label})
            if rng.random() < 0.5:
                frame["players"].append({"x": round(bx + rng.uniform(-20, 20), 1), "y": rng.choice([-2.5, W + 2.5]), "team": "unknown"})
            if rng.random() < 0.30:
                frame["ball"] = {"x": round(bx + rng.gauss(0, 0.8), 1), "y": round(by + rng.gauss(0, 0.8), 1)}
                frame["_ball_is_real"] = True
            elif rng.random() < 0.5:
                frame["ball"] = {"x": round(bx + rng.uniform(-22, 22), 1), "y": round(rng.uniform(5, W - 5), 1)}
                frame["_ball_is_real"] = False
        out.append(frame)
    return out


def write_all(seed, home, away, outdir):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    sim = Sim(seed, home, away, record_tracking=True).run()
    squads = {}
    for t in sim.teams:
        squads[t["code"]] = {"name": t["name"], "kit": t["kit"],
                             "players": [{"id": p.pid, "name": p.name, "number": p.number, "role": p.role} for p in t["all"]]}
    (out / "truth.json").write_text(json.dumps({"synthetic": True, "seed": seed, "squads": squads, "events": sim.events}, indent=1))
    feed = build_events_feed(sim, seed)
    (out / "events_feed.jsonl").write_text("\n".join(json.dumps(i) for i in feed) + "\n")
    vision = build_vision_feed(sim, seed)
    (out / "vision_feed.jsonl").write_text("\n".join(json.dumps(f) for f in vision) + "\n")
    return sim, feed, vision


if __name__ == "__main__":
    import sys
    from try_engine import HOME, AWAY
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    sim, feed, vision = write_all(seed, HOME, AWAY, Path(__file__).resolve().parent / "out" / f"match-{seed:03d}")
    wide = [f for f in vision if f["shot"] == "wide"]
    print("score", [t["score"] for t in sim.teams], "| truth events", len(sim.events), "| events feed", len(feed),
          "| vision frames", len(vision), "wide", len(wide))
    print("mean players per wide frame", round(sum(len(f["players"]) for f in wide) / len(wide), 1),
          "| frames with a ball box", sum(1 for f in wide if f["ball"]), "of which real", sum(1 for f in wide if f.get("_ball_is_real")))
    lates = [i for i in feed if i["late_card"]]
    print("late cards", [(i["clock"], i["delivered_sec"]) for i in lates])

"""Reconcile the events feed and the vision feed into verified match facts (facts.json).

What it does beyond copying events:
- finds the key moments and weights them, merging shot + save + goal records
- corrects cards that the feed stamped minutes late, by matching them to the foul that caused them
- applies VAR decisions to the score
- checks shots and goals against the vision feed (were attackers near the goal in the wide shots just before?)
- computes match statistics from the feed, per half and full time
Everything is synthetic. Nothing here touches real match data.
"""
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from enrich import enrich, fill_lulls

HEADER = {"competition": "Premier Division", "season": "2026/2027", "round": "11", "kickoff_local": "2026-10-31 15:00",
          "venue": "Harrowgate Park", "period_length": 45, "attendance": 38412,
          "officials": {"Main": "Gareth Aldous", "Video Assistant Referee": "Simon Greaves"}}
HALF = 2700.0


def minute_label(period, sec):
    total = sec + (HALF if period == 2 else 0)
    m = int(total // 60) + 1
    cap = 45 * period
    return f"{cap}+{m - cap}'" if m > cap else f"{m}'"


def clock(period, sec):
    total = max(0, int(sec + (HALF if period == 2 else 0)))
    return f"{total // 60}:{total % 60:02d}"


def build(dirpath, home_code, away_code):
    d = Path(dirpath)
    truth = json.load(open(d / "truth.json"))
    feed = [json.loads(line) for line in open(d / "events_feed.jsonl")]
    vision = [json.loads(line) for line in open(d / "vision_feed.jsonl")]
    squads = truth["squads"]
    pname = {p["id"]: p["name"] for s in squads.values() for p in s["players"]}
    tname = {c: s["name"] for c, s in squads.items()}

    fouls_by_player = defaultdict(list)
    for it in feed:
        if it["type"] == "foul":
            fouls_by_player[it["player"]].append(it)
    saves = [it for it in feed if it["type"] == "save"]
    shots = [it for it in feed if it["type"] == "shot"]

    moments, corrections = [], []

    def add(kind, it, weight, sec=None, **detail):
        sec = it["stamped_sec"] if sec is None else sec
        moments.append({"kind": kind, "period": it["period"], "sec": sec, "team": it["team"], "team_name": tname.get(it["team"]),
                        "player": pname.get(it["player"]), "player_id": it["player"], "x": it["x"], "y": it["y"],
                        "detail": detail, "weight": weight, "sources": [it["event_id"]]})
        return moments[-1]

    for it in feed:
        t, dt = it["type"], it["detail"]
        if t == "goal":
            shot = next((s for s in shots if s["player"] == it["player"] and s["period"] == it["period"] and abs(s["stamped_sec"] - it["stamped_sec"]) < 6), None)
            m = add("goal", it, 5, situation=dt["situation"], assist=pname.get(dt.get("assist")), assist_kind=dt.get("assist_kind"),
                    xg=(shot or {}).get("detail", {}).get("xg"))
            m["event_id"] = it["event_id"]
            if shot:
                m["sources"].append(shot["event_id"])
        elif t == "var":
            add("var", it, 5, decision=dt["decision"], reason=dt["reason"], goal_event=dt["goal_event"])
        elif t == "penalty_awarded":
            foul = next((f for f in reversed(feed) if f["type"] == "foul" and f["period"] == it["period"] and 0 <= it["stamped_sec"] - f["stamped_sec"] < 8), None)
            add("penalty", it, 5, fouled=pname.get(it["player"]), fouler=pname.get((foul or {}).get("player")))
        elif t == "card":
            near = [f for f in fouls_by_player.get(it["player"], [])
                    if f["period"] == it["period"] and -12 <= it["stamped_sec"] - f["stamped_sec"] < 600]
            foul = min(near, key=lambda f: abs(it["stamped_sec"] - f["stamped_sec"])) if near else None
            sec = it["stamped_sec"]
            if foul and it["stamped_sec"] - foul["stamped_sec"] > 40:
                sec = foul["stamped_sec"] + 1.0
                corrections.append({"card_event": it["event_id"], "player": pname.get(it["player"]), "stamped": clock(it["period"], it["stamped_sec"]),
                                    "corrected_to": clock(it["period"], sec), "reason": "matched to the foul that caused it"})
            card = dt["card"]
            m = add("card", it, 5 if card != "yellow" else 3, sec=sec, card=card, victim=pname.get(((foul or {}).get("detail") or {}).get("victim")))
            if foul:
                m["sources"].append(foul["event_id"])
        elif t == "shot":
            o = dt["outcome"]
            if o == "goal":
                continue
            xg = dt.get("xg", 0)
            w = 4 if (o == "post" or (o == "saved" and xg >= 0.2)) else 3 if (o == "saved" and xg >= 0.1) or xg >= 0.2 else 2
            if dt.get("situation") == "penalty":
                w = 5
            sv = next((s for s in saves if s["detail"].get("shooter") == it["player"] and s["period"] == it["period"] and abs(s["stamped_sec"] - it["stamped_sec"]) < 8), None)
            m = add("shot", it, w, outcome=o, xg=xg, situation=dt.get("situation"), body=dt.get("body"), saved_by=pname.get(sv["player"]) if sv else None,
                    assist=pname.get(dt.get("assist")), assist_kind=dt.get("assist_kind"))
            if sv:
                m["sources"].append(sv["event_id"])
        elif t == "substitution":
            add("substitution", it, 3, off=pname.get(dt.get("off")))
        elif t == "offside":
            add("offside", it, 2, pass_from=pname.get(dt.get("pass_from")))
        elif t == "added_time":
            add("added_time", it, 3, minutes=dt["minutes"])
        elif t == "period_start":
            add("period_start", it, 3)
        elif t == "period_end":
            add("period_end", it, 4)

    period_end = {it["period"]: it["stamped_sec"] for it in feed if it["type"] == "period_end"}
    cancelled_goals = {it["detail"]["goal_event"] for it in feed if it["type"] == "var" and it["detail"].get("decision") == "cancelled"}
    extra, players, windows = enrich(feed, squads, home_code, away_code, pname, tname, cancelled_goals, period_end)
    moments += extra
    moments += fill_lulls(moments, feed, home_code, away_code, tname, period_end)
    moments.sort(key=lambda m: (m["period"], m["sec"]))

    score = [0, 0]
    goal_by_event = {}
    for i, m in enumerate(moments, start=1):
        m["id"] = f"m{i}"
        m["minute"] = minute_label(m["period"], m["sec"])
        m["clock"] = clock(m["period"], m["sec"])
        if m["kind"] == "goal":
            score[0 if m["team"] == home_code else 1] += 1
            goal_by_event[m["event_id"]] = m
        elif m["kind"] == "var" and m["detail"]["decision"] == "cancelled":
            g = goal_by_event.get(m["detail"]["goal_event"])
            if g:
                score[0 if g["team"] == home_code else 1] -= 1
                g["cancelled"] = True
                g["weight"] = 4
                m["detail"]["cancelled_goal"] = g["id"]
        m["score_after"] = list(score)

    # vision cross-check for the moments a reader cares about
    checked = {"supported": 0, "unsupported": 0, "no_wide_frame": 0}
    for m in moments:
        if m["kind"] not in ("goal", "shot", "penalty") or m["weight"] < 2 or m["x"] is None:
            continue
        gx = 105.0 if m["x"] > 52.5 else 0.0
        frames = [f for f in vision if f["period"] == m["period"] and f["shot"] == "wide" and m["sec"] - 12 <= f["t"] <= m["sec"] - 0.5]
        if not frames:
            m["vision"] = {"check": "no_wide_frame"}
            checked["no_wide_frame"] += 1
            continue
        counts = [sum(1 for p in f["players"] if p["team"] == m["team"] and abs(p["x"] - gx) < 30) for f in frames]
        med = statistics.median(counts)
        ok = med >= 2
        m["vision"] = {"check": "supported" if ok else "unsupported", "frames": len(frames), "attackers_within_30m_of_goal": med}
        checked["supported" if ok else "unsupported"] += 1

    stats = compute_stats(feed, home_code, away_code)
    header = dict(HEADER)
    header["teams"] = {c: {"name": s["name"], "short": s["name"].split()[0], "code": c, "side": "home" if c == home_code else "away", "kit": s["kit"]}
                       for c, s in squads.items()}
    header["data_class"] = "synthetic"
    lineups = {c: {"starting": [f'{p["number"]} {p["name"]}' for p in s["players"][:11]],
                   "bench": [f'{p["number"]} {p["name"]}' for p in s["players"][11:]]} for c, s in squads.items()}
    top = {c: [p["id"] for p in players if p["team"] == c][:3] for c in squads}
    return {"header": header, "lineups": lineups, "moments": moments, "stats": stats, "players": players, "windows": windows, "top_performers": top,
            "reconciliation": {"vision_checks": checked, "card_time_corrections": corrections}}


def compute_stats(feed, home, away):
    def blank():
        return {home: defaultdict(float), away: defaultdict(float)}
    periods = {"h1": blank(), "h2": blank(), "ft": blank()}
    for it in feed:
        for key in ("ft", "h1" if it["period"] == 1 else "h2"):
            s = periods[key].get(it["team"])
            if s is None:
                continue
            t, dt = it["type"], it["detail"]
            if t == "pass":
                s["passes"] += 1
                s["passes_completed"] += 1 if dt.get("outcome") == 1 else 0
            elif t == "shot":
                s["shots"] += 1
                s["on_target"] += 1 if dt["outcome"] in ("goal", "saved") else 0
                s["xg"] += dt.get("xg", 0)
            elif t == "corner_awarded":
                s["corners"] += 1
            elif t == "foul":
                s["fouls"] += 1
            elif t == "card":
                s["yellow" if dt["card"] == "yellow" else "red"] += 1
            elif t == "offside":
                s["offsides"] += 1
    out = {}
    for key, per in periods.items():
        tot = sum(per[c]["passes_completed"] for c in (home, away)) or 1
        out[key] = {c: {**{k: (round(v, 2) if k == "xg" else int(v)) for k, v in per[c].items()},
                        "possession_pct": round(100 * per[c]["passes_completed"] / tot)} for c in (home, away)}
    return out


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else "out/match-006"
    facts = build(src, "RMA", "STB")
    Path(src, "facts.json").write_text(json.dumps(facts, indent=1, ensure_ascii=False))
    print("moments", len(facts["moments"]), "| weights", {w: sum(1 for m in facts["moments"] if m["weight"] == w) for w in (5, 4, 3, 2, 1)})
    print("reconciliation", facts["reconciliation"])
    print("stats ft", json.dumps(facts["stats"]["ft"]))
    for m in facts["moments"]:
        if m["weight"] >= 4 or m["kind"] in ("substitution",):
            print(m["id"].ljust(4), m["minute"].ljust(7), m["kind"].ljust(12), str(m["team"]).ljust(4), str(m["player"]).ljust(18), m["score_after"],
                  {k: v for k, v in m["detail"].items() if k != "xg"}, (m.get("vision") or {}).get("check", ""))

"""Derive richer match moments and statistics from the events feed.

Adds to the reconciler's moments: line-ups, corners, fouls, defensive stands, pressing wins, passing sequences, spells of
pressure, 15-minute windows and phase notes that fill quiet stretches. Also computes per-player statistics.
Everything here is computed from the feed; nothing is invented.
"""
from collections import defaultdict

PITCH_L = 105.0
SEQ_BREAKERS = {"interception", "ball_recovery", "tackle", "foul", "offside", "corner_awarded", "free_kick_awarded", "throw_in_awarded",
                "goal_kick_awarded", "shot", "goal", "save", "block", "clearance", "period_start", "period_end", "var", "penalty_awarded"}
WINDOWS = [(1, 0, 900, "1-15"), (1, 900, 1800, "16-30"), (1, 1800, 99999, "31-45+"),
           (2, 0, 900, "46-60"), (2, 900, 1800, "61-75"), (2, 1800, 99999, "76-90+")]


def attack_x(team, period, x, home):
    home_dir = 1 if period == 1 else -1
    d = home_dir if team == home else -home_dir
    return x if d == 1 else PITCH_L - x


def thin(items, key, gap):
    out, last = [], {}
    for it in sorted(items, key=key):
        k = (it["period"], it["team"])
        if k in last and key(it)[1] - last[k] < gap:
            continue
        last[k] = key(it)[1]
        out.append(it)
    return out


def mk(kind, period, sec, team, pid, weight, sources, pname, tname, x=None, y=None, **detail):
    return {"kind": kind, "period": period, "sec": sec, "team": team, "team_name": tname.get(team), "player": pname.get(pid),
            "player_id": pid, "x": x, "y": y, "detail": detail, "weight": weight, "sources": list(sources)}


def player_stats(feed, squads, cancelled_goal_ids):
    meta = {p["id"]: {"name": p["name"], "team": c, "role": p["role"], "number": p["number"]} for c, s in squads.items() for p in s["players"]}
    s = defaultdict(lambda: defaultdict(float))
    for it in feed:
        t, p, d = it["type"], it["player"], it["detail"]
        if t == "pass":
            s[p]["passes"] += 1
            s[p]["passes_completed"] += 1 if d.get("outcome") == 1 else 0
        elif t == "shot":
            s[p]["shots"] += 1
            s[p]["on_target"] += 1 if d["outcome"] in ("goal", "saved") else 0
            if d.get("assist"):
                s[d["assist"]]["key_passes"] += 1
        elif t == "goal" and it["event_id"] not in cancelled_goal_ids:
            s[p]["goals"] += 1
            if d.get("assist"):
                s[d["assist"]]["assists"] += 1
        elif t == "tackle" and d.get("won"):
            s[p]["tackles_won"] += 1
        elif t == "interception":
            s[p]["interceptions"] += 1
        elif t == "ball_recovery":
            s[p]["recoveries"] += 1
        elif t == "clearance":
            s[p]["clearances"] += 1
        elif t == "foul":
            s[p]["fouls_committed"] += 1
            if d.get("victim"):
                s[d["victim"]]["fouls_won"] += 1
        elif t == "save":
            s[p]["saves"] += 1
        elif t == "card":
            s[p]["yellow" if d["card"] == "yellow" else "red"] += 1
    players = []
    for pid, m in meta.items():
        st = {k: int(v) for k, v in s.get(pid, {}).items()}
        if not st.get("passes") and not st.get("shots") and not st.get("saves") and not st.get("tackles_won"):
            continue
        st["pass_pct"] = round(100 * st.get("passes_completed", 0) / st["passes"]) if st.get("passes") else 0
        score = (4 * st.get("goals", 0) + 3 * st.get("assists", 0) + st.get("key_passes", 0) + 0.6 * st.get("on_target", 0)
                 + 0.04 * st.get("passes_completed", 0) + 0.5 * st.get("tackles_won", 0) + 0.3 * st.get("interceptions", 0)
                 + 0.3 * st.get("clearances", 0) + 0.6 * st.get("saves", 0) - 0.3 * st.get("fouls_committed", 0))
        players.append({"id": pid, **m, "stats": st, "score": round(score, 2)})
    players.sort(key=lambda p: -p["score"])
    return players


def window_stats(feed, home, away, period, a, b):
    sel = [it for it in feed if it["period"] == period and a <= it["stamped_sec"] < b]
    out = {c: defaultdict(int) for c in (home, away)}
    for it in sel:
        c, t, d = it["team"], it["type"], it["detail"]
        if c not in out:
            continue
        if t == "pass" and d.get("outcome") == 1:
            out[c]["passes"] += 1
            if attack_x(c, period, it["x"], home) > 70:
                out[c]["final_third_passes"] += 1
        elif t == "shot":
            out[c]["shots"] += 1
            out[c]["on_target"] += 1 if d["outcome"] in ("goal", "saved") else 0
        elif t == "corner_awarded":
            out[c]["corners"] += 1
        elif t == "foul":
            out[c]["fouls"] += 1
    tot = sum(out[c]["passes"] for c in out) or 1
    ft = sum(out[c]["final_third_passes"] for c in out) or 1
    return {c: {"possession_pct": round(100 * out[c]["passes"] / tot), "field_tilt_pct": round(100 * out[c]["final_third_passes"] / ft),
                "shots": out[c]["shots"], "on_target": out[c]["on_target"], "corners": out[c]["corners"], "fouls": out[c]["fouls"]} for c in out}


def sequences(feed, home):
    out, cur = [], None

    def close(end):
        nonlocal cur
        if cur and cur["passes"] >= 8:
            cur["ended_with"] = end
            out.append(cur)
        cur = None

    for it in sorted(feed, key=lambda i: i["event_id"]):
        t = it["type"]
        if t == "pass":
            if it["detail"].get("outcome") == 1:
                if cur and cur["team"] == it["team"] and cur["period"] == it["period"]:
                    cur["passes"] += 1
                    cur["players"].add(it["player"])
                    cur["end_sec"], cur["end_x"] = it["stamped_sec"], attack_x(it["team"], it["period"], it["detail"].get("end_x", it["x"]), home)
                    cur["sources"].append(it["event_id"])
                else:
                    close("lost the ball")
                    cur = {"team": it["team"], "period": it["period"], "passes": 1, "players": {it["player"]}, "start_sec": it["stamped_sec"],
                           "end_sec": it["stamped_sec"], "start_x": attack_x(it["team"], it["period"], it["x"], home),
                           "end_x": attack_x(it["team"], it["period"], it["detail"].get("end_x", it["x"]), home), "sources": [it["event_id"]]}
            else:
                close("lost the ball")
        elif t in SEQ_BREAKERS:
            end = {"shot": "a shot", "goal": "a goal", "foul": "a foul", "offside": "an offside", "corner_awarded": "a corner",
                   "free_kick_awarded": "a free kick"}.get(t, "lost the ball")
            if cur and t in ("shot", "goal") and it["team"] != cur["team"]:
                end = "lost the ball"
            close(end)
    close("lost the ball")
    return out


def pressure_spells(feed):
    by_team = defaultdict(list)
    for it in feed:
        if it["type"] in ("shot", "corner_awarded"):
            by_team[(it["team"], it["period"])].append(it)
    out = []
    for (team, period), items in by_team.items():
        items.sort(key=lambda i: i["stamped_sec"])
        cluster = [items[0]]
        for it in items[1:] + [None]:
            if it is not None and it["stamped_sec"] - cluster[-1]["stamped_sec"] <= 180:
                cluster.append(it)
                continue
            if len(cluster) >= 3:
                out.append({"team": team, "period": period, "from": cluster[0]["stamped_sec"], "to": cluster[-1]["stamped_sec"],
                            "shots": sum(1 for c in cluster if c["type"] == "shot"), "corners": sum(1 for c in cluster if c["type"] == "corner_awarded"),
                            "sources": [c["event_id"] for c in cluster]})
            cluster = [it] if it is not None else []
    return out


def enrich(feed, squads, home, away, pname, tname, cancelled_goal_ids, period_end):
    """Return (moments, players, windows)."""
    moments = []
    players = player_stats(feed, squads, cancelled_goal_ids)

    # line-ups
    for c, s in squads.items():
        xi = s["players"][:11]
        names = lambda role: [f'{p["number"]} {p["name"]}' for p in xi if p["role"] == role]
        moments.append(mk("lineup", 1, -5.0 if c == home else -4.0, c, None, 3, [], pname, tname, formation="4-4-2", goalkeeper=names("GK")[0],
                          defenders=", ".join(names("DF")), midfielders=", ".join(names("MF")), forwards=", ".join(names("FW"))))

    # corners (numbered per team), dangerous free kicks, fouls, clearances
    corner_no = defaultdict(int)
    for it in sorted(feed, key=lambda i: i["event_id"]):
        t, c, p = it["type"], it["team"], it["period"]
        if t == "corner_awarded":
            corner_no[c] += 1
            moments.append(mk("corner", p, it["stamped_sec"], c, None, 2, [it["event_id"]], pname, tname, number=corner_no[c]))
        elif t == "foul":
            victim = it["detail"].get("victim")
            vteam = next((pl["team"] for pl in players if pl["id"] == victim), None)
            zone_x = attack_x(vteam, p, it["x"], home) if vteam else 50
            zone = "in the attacking third" if zone_x > 72 else "in the defensive third" if zone_x < 30 else "in midfield"
            moments.append(mk("foul", p, it["stamped_sec"], c, it["player"], 2 if zone_x > 72 else 1, [it["event_id"]], pname, tname,
                              x=it["x"], y=it["y"], fouled=pname.get(victim), zone=zone))
        elif t == "clearance" and attack_x(c, p, it["x"], home) < 30:
            moments.append(mk("clearance", p, it["stamped_sec"], c, it["player"], 2, [it["event_id"]], pname, tname, x=it["x"], y=it["y"]))

    # defensive stands and pressing wins (tackles/interceptions), thinned so they do not crowd the blog
    stands, presses = [], []
    for it in feed:
        if it["type"] in ("tackle", "interception", "ball_recovery") and it["team"] in (home, away) and not (it["type"] == "tackle" and not it["detail"].get("won", True)):
            axv = attack_x(it["team"], it["period"], it["x"], home)
            row = {"period": it["period"], "team": it["team"], "sec": it["stamped_sec"], "it": it, "type": it["type"]}
            if axv < 20:
                stands.append(row)
            elif axv > 78:
                presses.append(row)
    for kind, rows, gap in (("defensive_stand", stands, 240), ("pressing_win", presses, 240)):
        for r in thin(rows, lambda r: (r["period"], r["sec"]), gap):
            it = r["it"]
            moments.append(mk(kind, r["period"], r["sec"], r["team"], it["player"], 2, [it["event_id"]], pname, tname, x=it["x"], y=it["y"], action=it["type"]))

    # passing sequences
    seqs = sequences(feed, home)
    seqs.sort(key=lambda s: -s["passes"])
    for i, s in enumerate(seqs[:12]):
        w = 3 if i < 4 or s["ended_with"] in ("a shot", "a goal") else 2
        moments.append(mk("sequence", s["period"], s["end_sec"], s["team"], None, w, s["sources"][-3:], pname, tname, passes=s["passes"], players=len(s["players"]),
                          start_minute_sec=int(s["start_sec"]), duration_sec=int(s["end_sec"] - s["start_sec"]),
                          progress_m=int(max(0, s["end_x"] - s["start_x"])), ended_with=s["ended_with"]))

    # spells of pressure
    for sp in pressure_spells(feed):
        moments.append(mk("pressure", sp["period"], sp["to"], sp["team"], None, 3, sp["sources"], pname, tname, shots=sp["shots"], corners=sp["corners"],
                          span_seconds=int(sp["to"] - sp["from"])))

    # 15-minute windows (as insights); the last window of each half is covered by the half-time and full-time notes
    windows = []
    for period, a, b, label in WINDOWS:
        end = min(b, period_end.get(period, b))
        st = window_stats(feed, home, away, period, a, end)
        windows.append({"period": period, "from": a, "to": end, "label": label, "stats": {tname[c]: v for c, v in st.items()}})
        if label in ("1-15", "16-30", "46-60", "61-75"):
            moments.append(mk("window", period, end, None, None, 3, [], pname, tname, label=label, **{"stats": {tname[c]: v for c, v in st.items()}}))
    return moments, players, windows


def fill_lulls(moments, feed, home, away, tname, period_end, max_gap=150):
    """Add a phase note wherever the ticker-worthy moments leave a gap longer than max_gap seconds."""
    extra = []
    for period in (1, 2):
        marks = sorted(m["sec"] for m in moments if m["period"] == period and m["weight"] >= 2 and m["sec"] >= 0)
        end = period_end.get(period, 2700)
        pts = [0.0] + marks + [end]
        for a, b in zip(pts, pts[1:]):
            if b - a <= max_gap:
                continue
            k = max(1, int((b - a) // 210))
            for i in range(k):
                lo, hi = a + (b - a) * i / k, a + (b - a) * (i + 1) / k
                st = window_stats(feed, home, away, period, lo, hi)
                ctrl = max(st, key=lambda c: st[c]["possession_pct"])
                extra.append({"kind": "phase", "period": period, "sec": hi - 5, "team": ctrl, "team_name": tname[ctrl], "player": None, "player_id": None,
                              "x": None, "y": None, "weight": 2, "sources": [],
                              "detail": {"from_minute": int(lo // 60) + 1 + (45 if period == 2 else 0), "to_minute": int(hi // 60) + 1 + (45 if period == 2 else 0),
                                         "possession_pct": st[ctrl]["possession_pct"], "field_tilt_pct": st[ctrl]["field_tilt_pct"],
                                         "shots_home": st[home]["shots"], "shots_away": st[away]["shots"]}})
    return extra

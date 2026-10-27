"""Synthetic football match: fictional clubs, 10 Hz tracking for 22 players and the ball, exact ground-truth events.

Every name, club and number here is invented. Nothing is derived from real match data or footage.
Pitch is 105 x 68 m. The home side attacks towards x=105 in the first half.
"""
import math
import random
from array import array

L, W = 105.0, 68.0
DT = 0.1
GOAL_HALF = 3.66
FORMATION = [("GK", 4, 34), ("DF", 24, 10), ("DF", 24, 25), ("DF", 24, 43), ("DF", 24, 58),
             ("MF", 44, 12), ("MF", 44, 26), ("MF", 44, 42), ("MF", 44, 56), ("FW", 62, 26), ("FW", 62, 42)]
NUMBERS = [1, 2, 4, 5, 3, 7, 8, 6, 11, 9, 10]
FIRST = ["Jory", "Callum", "Declan", "Rhys", "Tobias", "Marcus", "Elliot", "Joel", "Lewis", "Kieran", "Owen", "Reece",
         "Dominic", "Harvey", "Finley", "Jasper", "Nathan", "Alfie", "Connor", "Stefan", "Ravi", "Idris", "Mateo", "Luca",
         "Kofi", "Sami", "Tomas", "Nico", "Aled", "Bram", "Cai", "Dev", "Emeka", "Femi", "Gabe", "Hugo"]
LAST = ["Whitlam", "Harcourt", "Pellow", "Thackeray", "Ormerod", "Latimer", "Bexley", "Kinsella", "Dunmore", "Farrow",
        "Gosling", "Hallam", "Ibbotson", "Jessop", "Kerridge", "Lowther", "Marlowe", "Nuttall", "Pickering", "Quayle",
        "Rudge", "Stanhope", "Tolley", "Upton", "Venn", "Wragg", "Yeoman", "Ashdown", "Brigg", "Cleaver", "Dobbin",
        "Eastley", "Fenner", "Garside", "Holloway", "Iredale", "Jarrow", "Kemble", "Lisle", "Mercer", "Nairn", "Oakes",
        "Pargeter", "Radley", "Sutcliffe", "Trenholm", "Underhill", "Voss", "Wetherby", "Yarrow"]


def hyp(a, b):
    return math.hypot(a, b)


class Player:
    def __init__(self, pid, name, team, number, role, slot_ax, slot_y, skill, speed):
        self.pid, self.name, self.team, self.number, self.role = pid, name, team, number, role
        self.slot_ax, self.slot_y, self.skill, self.speed = slot_ax, slot_y, skill, speed
        self.x = self.y = self.vx = self.vy = self.tx = self.ty = 0.0
        self.yellow = 0
        self.sprint = False


class Sim:
    def __init__(self, seed, home, away, record_tracking=True):
        self.rng = random.Random(seed)
        self.seed = seed
        used = set()
        self.teams = []
        for k, club in enumerate((home, away)):
            squad, bench = self.make_squad(club, used, k)
            self.teams.append({"code": club["code"], "name": club["name"], "kit": club["kit"], "str": club.get("str", 1.0),
                               "dir": 1 if k == 0 else -1, "players": squad, "bench": bench, "all": squad + bench,
                               "score": 0, "subs": 0, "sub_plan": sorted(self.rng.sample(range(56, 86), 3))})
        self.events, self.eid = [], 0
        self.tracking = array("f") if record_tracking else None
        self.period, self.t = 1, 0.0
        self.mode, self.timer = "dead", 0.0
        self.carrier = None
        self.ball = [L / 2, W / 2]
        self.flight = None
        self.restart = None
        self.last_pass = None
        self.next_decision = 0.0
        self.override = {}
        self.stoppage = 0.0
        self.added = None
        self.pending_var = None

    def make_squad(self, club, used, k):
        rng = self.rng
        def name():
            while True:
                f, l = rng.choice(FIRST), rng.choice(LAST)
                if l not in used:
                    used.add(l)
                    return f"{f} {l}", l
        squad, bench = [], []
        for i, (role, ax, y) in enumerate(FORMATION):
            full, _ = name()
            squad.append(Player(f"{club['code']}{NUMBERS[i]}", full, club["code"], NUMBERS[i], role, ax, y,
                                min(1.25, max(0.75, rng.gauss(1.0, 0.07))), rng.uniform(5.3, 6.5)))
        for j, role in enumerate(["GK", "DF", "DF", "MF", "MF", "FW", "FW"]):
            full, _ = name()
            n = 12 + j
            bench.append(Player(f"{club['code']}{n}", full, club["code"], n, role, 0, 0,
                                min(1.25, max(0.75, rng.gauss(1.0, 0.07))), rng.uniform(5.3, 6.5)))
        return squad, bench

    # ---- helpers
    def opp(self, team):
        return self.teams[1] if team is self.teams[0] else self.teams[0]

    def team_of(self, p):
        return self.teams[0] if p.team == self.teams[0]["code"] else self.teams[1]

    def goal_x(self, team):
        return L if team["dir"] == 1 else 0.0

    def ax(self, team, x):
        return x if team["dir"] == 1 else L - x

    def clock(self):
        return self.t

    def log(self, typ, team=None, player=None, x=None, y=None, **detail):
        self.eid += 1
        if x is None:
            x, y = self.ball
        e = {"id": self.eid, "period": self.period, "t": round(self.t, 1), "type": typ,
             "team": team["code"] if isinstance(team, dict) else team,
             "player": player.pid if player else None, "x": round(x, 1), "y": round(y, 1), "detail": detail}
        self.events.append(e)
        return e

    def possession_team(self):
        if self.mode == "carried" and self.carrier:
            return self.team_of(self.carrier)
        if self.mode == "flight" and self.flight:
            return self.flight["team"]
        if self.mode == "dead" and self.restart:
            return self.restart["team"]
        return None

    def gk(self, team):
        return next((p for p in team["players"] if p.role == "GK"), team["players"][0])

    def field(self, team):
        return [p for p in team["players"] if p.role != "GK"]

    def nearest(self, plist, x, y):
        return min(plist, key=lambda p: hyp(p.x - x, p.y - y))

    # ---- setup / kickoff
    def reset_formation(self, kick_team):
        for team in self.teams:
            for p in team["players"]:
                ax = min(p.slot_ax, 50.0 if p.role != "GK" else 4)
                p.x = ax if team["dir"] == 1 else L - ax
                p.y = p.slot_y
                p.vx = p.vy = 0.0
        taker = max(self.field(kick_team), key=lambda p: p.slot_ax)
        taker.x, taker.y = L / 2 - 0.5 * kick_team["dir"], W / 2
        self.ball = [L / 2, W / 2]
        self.mode, self.carrier, self.restart = "dead", None, {"team": kick_team, "kind": "kickoff", "taker": taker}
        self.timer = 3.0

    def start_period(self, period, kick_team):
        self.period, self.t, self.added = period, 0.0, None
        if period == 2:
            for team in self.teams:
                team["dir"] = -team["dir"]
        self.log("period_start", None, None, L / 2, W / 2)
        self.reset_formation(kick_team)

    def period_len(self):
        base = 45 * 60 * self.period
        return base + (self.added or 0) * 60

    # ---- main loop
    def run(self):
        first_kick = self.teams[0]
        for period in (1, 2):
            self.start_period(period, first_kick if period == 1 else self.teams[1])
            period_end_clock = 45 * 60
            while True:
                if self.added is None and self.t >= period_end_clock - 1:
                    self.announce_added()
                if self.added is not None and self.t >= period_end_clock + self.added * 60 + self.rng.uniform(0, 30) and self.mode in ("carried", "dead"):
                    break
                self.step()
            self.log("period_end", None, None, L / 2, W / 2)
        return self

    def announce_added(self):
        goals = sum(t["score"] for t in self.teams)
        subs = sum(t["subs"] for t in self.teams)
        cards = sum(1 for e in self.events if e["type"] == "card" and e["period"] == self.period)
        self.added = max(1, min(7, int(round(0.7 + 0.5 * goals * (self.period - 1) + 0.25 * subs + 0.3 * cards + self.rng.uniform(0, 1.5)))))
        self.log("added_time", None, None, L / 2, W / 2, minutes=self.added)

    def step(self):
        if self.mode == "dead":
            self.timer -= DT
            if self.timer <= 0:
                self.do_restart()
        elif self.mode == "flight":
            self.advance_flight()
        elif self.mode == "carried":
            self.next_decision -= DT
            if self.next_decision <= 0:
                self.decide()
        self.compute_targets()
        self.move_players()
        if self.mode == "carried" and self.carrier:
            d = self.team_of(self.carrier)["dir"]
            self.ball = [self.carrier.x + 0.6 * d, self.carrier.y]
        self.t += DT
        if self.tracking is not None:
            self.record()

    def record(self):
        tr = self.tracking
        tr.append(self.period)
        tr.append(self.t)
        tr.append(self.ball[0])
        tr.append(self.ball[1])
        for team in self.teams:
            for p in team["players"]:
                tr.append(p.x)
                tr.append(p.y)
            for _ in range(11 - len(team["players"])):
                tr.append(-1.0)
                tr.append(-1.0)

    # ---- movement
    def compute_targets(self):
        bx, by = self.ball
        poss = self.possession_team()
        for team in self.teams:
            d = team["dir"]
            axb = self.ax(team, bx)
            in_poss = poss is team
            shift = (axb - 52.0) * 0.5 + (6.0 if in_poss else -3.0)
            for p in team["players"]:
                p.sprint = False
                if p in self.override:
                    p.tx, p.ty = self.override[p]
                    p.sprint = True
                    continue
                if p.role == "GK":
                    tax = 4 + max(0.0, min(8.0, (axb - 52) * 0.08))
                    ty = max(26.0, min(42.0, 34 + (by - 34) * 0.2))
                else:
                    k = {"DF": 0.4, "MF": 0.7, "FW": 0.9}[p.role]
                    tax = max(6.0, min(98.0, p.slot_ax + shift * k))
                    ty = max(3.0, min(65.0, p.slot_y + (by - 34) * 0.25))
                p.tx = tax if d == 1 else L - tax
                p.ty = ty
        if self.mode == "carried" and self.carrier:
            c = self.carrier
            ct = self.team_of(c)
            c.tx, c.ty, c.sprint = c.x + ct["dir"] * 8, c.y, False
            press = self.opp(ct)
            near = sorted(self.field(press), key=lambda p: hyp(p.x - c.x, p.y - c.y))
            for i, p in enumerate(near[:2]):
                if p not in self.override:
                    p.tx, p.ty, p.sprint = c.x, c.y, True
        elif self.mode == "flight" and self.flight:
            f = self.flight
            r = f["receiver"]
            if r is not None:
                r.tx, r.ty, r.sprint = f["ex"], f["ey"], True
            for p in sorted(self.field(self.opp(f["team"])), key=lambda p: hyp(p.x - f["ex"], p.y - f["ey"]))[:1]:
                p.tx, p.ty, p.sprint = f["ex"], f["ey"], True

    def move_players(self):
        for team in self.teams:
            for p in team["players"]:
                dx, dy = p.tx - p.x, p.ty - p.y
                dist = hyp(dx, dy)
                if dist > 0.05:
                    vmax = p.speed if p.sprint else p.speed * 0.6
                    des = min(vmax, dist * 1.5)
                    dvx, dvy = dx / dist * des, dy / dist * des
                else:
                    dvx = dvy = 0.0
                ax, ay = dvx - p.vx, dvy - p.vy
                mag = hyp(ax, ay)
                lim = 5.0 * DT
                if mag > lim:
                    ax, ay = ax / mag * lim, ay / mag * lim
                p.vx += ax
                p.vy += ay
                p.x = max(-1.0, min(L + 1.0, p.x + p.vx * DT))
                p.y = max(-1.0, min(W + 1.0, p.y + p.vy * DT))

    # ---- decisions
    def decide(self):
        c = self.carrier
        team = self.team_of(c)
        opp = self.opp(team)
        rng = self.rng
        self.next_decision = rng.uniform(0.9, 2.0)
        for o in sorted(self.field(opp), key=lambda p: hyp(p.x - c.x, p.y - c.y))[:1]:
            if hyp(o.x - c.x, o.y - c.y) < 2.2 and rng.random() < 0.16:
                self.tackle(o, c)
                return
        gx = self.goal_x(team)
        dist = hyp(gx - c.x, 34 - c.y)
        if c.role != "GK" and dist < 26 and rng.random() < 0.34 * (26 - dist) / 26 * team["str"] + 0.008:
            self.shot(c, "open_play", "foot")
            return
        if rng.random() < 0.80 or c.role == "GK":
            self.pass_ball(c)
        else:
            c.tx = c.x + team["dir"] * 8
            self.next_decision = rng.uniform(0.9, 1.6)

    def tackle(self, tackler, victim):
        rng = self.rng
        vt, tt = self.team_of(victim), self.team_of(tackler)
        r = rng.random()
        if r < 0.55:
            self.log("tackle", tt, tackler, tackler.x, tackler.y, won=True, victim=victim.pid)
            self.take_possession(tackler)
        elif r < 0.78:
            self.foul(tackler, victim)
        else:
            self.next_decision = 0.5

    def take_possession(self, p):
        self.carrier, self.mode, self.flight = p, "carried", None
        self.next_decision = self.rng.uniform(0.5, 1.2)
        self.ball = [p.x, p.y]

    def foul(self, fouler, victim):
        rng = self.rng
        ft, vt = self.team_of(fouler), self.team_of(victim)
        x, y = victim.x, victim.y
        self.log("foul", ft, fouler, x, y, victim=victim.pid)
        roll = rng.random()
        card = None
        if roll < 0.005:
            card = "red"
        elif roll < 0.15:
            card = "yellow"
        if card:
            if card == "yellow" and fouler.yellow == 1:
                card = "second_yellow"
            if card == "yellow":
                fouler.yellow = 1
            self.log("card", ft, fouler, x, y, card=card, reason="foul")
            if card in ("red", "second_yellow"):
                ft["players"].remove(fouler)
                self.override.pop(fouler, None)
        ax = self.ax(vt, x)
        if ax > 88.5 and abs(y - 34) < 20.2:
            self.penalty(vt, victim)
            return
        self.set_piece(vt, "free_kick", x, y, rng.uniform(8, 18))

    def offside_flag(self, passer, receiver, team):
        opp = self.opp(team)
        d = team["dir"]
        xs = sorted((self.ax(team, p.x) for p in opp["players"]), reverse=True)
        line = xs[1] if len(xs) > 1 else xs[0]
        r_ax = self.ax(team, receiver.x)
        return r_ax > line + 0.8 and r_ax > self.ax(team, passer.x) + 1.0 and receiver.role != "GK"

    def pass_ball(self, c):
        rng = self.rng
        team = self.team_of(c)
        opp = self.opp(team)
        d = team["dir"]
        mates = [p for p in team["players"] if p is not c]
        scored = []
        for m in mates:
            dist = hyp(m.x - c.x, m.y - c.y)
            if dist < 4 or dist > 45:
                continue
            fwd = d * (m.x - c.x)
            near_opp = min(hyp(o.x - m.x, o.y - m.y) for o in opp["players"])
            s = 1.1 * fwd / 25 - abs(dist - 17) / 30 + min(near_opp, 12) / 12 + rng.uniform(-0.6, 0.6)
            if c.role == "GK" and m.role == "FW":
                s -= 1.5
            scored.append((s, m))
        if not scored:
            self.next_decision = 0.8
            return
        scored.sort(key=lambda t: -t[0])
        weights = [math.exp(2.0 * s) for s, _ in scored[:5]]
        r = rng.random() * sum(weights)
        for w, (_, m) in zip(weights, scored[:5]):
            r -= w
            if r <= 0:
                break
        if self.offside_flag(c, m, team) and rng.random() < 0.55:
            self.log("offside", team, m, m.x, m.y, pass_from=c.pid)
            self.set_piece(opp, "free_kick", m.x, m.y, rng.uniform(5, 10), silent=True)
            return
        dist = hyp(m.x - c.x, m.y - c.y)
        lane = self.lane_gap(opp, c, m)
        near_opp = min(hyp(o.x - m.x, o.y - m.y) for o in opp["players"])
        p_ok = 0.93 - 0.006 * max(0.0, dist - 15) - 0.22 * math.exp(-lane / 2.0) - 0.12 * math.exp(-near_opp / 3.0)
        p_ok = max(0.35, min(0.96, p_ok * c.skill * team["str"] ** 0.5))
        speed = rng.uniform(13, 20)
        ex, ey = m.x + m.vx * dist / speed, m.y + m.vy * dist / speed
        ex, ey = max(2.0, min(L - 2.0, ex)), max(2.0, min(W - 2.0, ey))
        outcome, inter = "complete", None
        if rng.random() > p_ok:
            if rng.random() < 0.28:
                outcome = "out"
            else:
                outcome = "intercept"
                inter = self.nearest(self.field(opp), (c.x + ex) / 2, (c.y + ey) / 2)
        fwd_gain = d * (ex - c.x)
        wide = abs(c.y - 34) > 20
        into_box = self.ax(team, ex) > 85 and abs(ey - 34) < 20.5
        pkind = ("cross" if wide and into_box and self.ax(team, c.x) > 60 else
                 "through_ball" if fwd_gain > 20 and self.ax(team, ex) > 65 else "long_ball" if dist > 35 else "pass")
        self.log("pass", team, c, c.x, c.y, end_x=round(ex, 1), end_y=round(ey, 1), to=m.pid, outcome=1 if outcome == "complete" else 0,
                 length=round(dist, 1), forward=fwd_gain > 5, kind=pkind)
        self.last_pass = {"passer": c, "team": team, "t": self.t, "ok": outcome == "complete", "kind": pkind}
        dur = max(0.3, hyp(ex - c.x, ey - c.y) / speed)
        self.flight = {"team": team, "passer": c, "receiver": m if outcome == "complete" else None, "sx": c.x, "sy": c.y, "ex": ex, "ey": ey,
                       "t0": self.t, "dur": dur, "outcome": outcome, "inter": inter, "target": m}
        self.mode, self.carrier = "flight", None

    def lane_gap(self, opp, a, b):
        ax, ay, bx, by = a.x, a.y, b.x, b.y
        dx, dy = bx - ax, by - ay
        n = dx * dx + dy * dy or 1.0
        best = 99.0
        for o in opp["players"]:
            t = max(0.0, min(1.0, ((o.x - ax) * dx + (o.y - ay) * dy) / n))
            best = min(best, hyp(o.x - (ax + t * dx), o.y - (ay + t * dy)))
        return best

    def advance_flight(self):
        f = self.flight
        frac = min(1.0, (self.t - f["t0"]) / f["dur"])
        self.ball = [f["sx"] + (f["ex"] - f["sx"]) * frac, f["sy"] + (f["ey"] - f["sy"]) * frac]
        if frac < 1.0:
            return
        team, rng = f["team"], self.rng
        if f["outcome"] == "complete":
            self.take_possession(f["receiver"])
            self.next_decision = rng.uniform(0.4, 1.0)
        elif f["outcome"] == "intercept":
            i = f["inter"]
            self.log("interception", self.team_of(i), i, f["ex"], f["ey"])
            i.x, i.y = f["ex"], f["ey"]
            self.take_possession(i)
        else:
            self.out_of_play(team, f["ex"], f["ey"], f["sx"], f["sy"])

    def out_of_play(self, last_team, x, y, sx, sy):
        rng = self.rng
        other = self.opp(last_team)
        side = rng.random() < 0.55
        if side:
            ty = 0.0 if y < W / 2 else W
            self.log("throw_in_awarded", other, None, x, ty)
            self.set_piece(other, "throw_in", x, ty, rng.uniform(5, 10), silent=True)
            return
        end_x = L if x > L / 2 else 0.0
        def_team = last_team if (self.goal_x(self.opp(last_team)) == end_x) else other
        att_team = self.opp(def_team)
        if self.goal_x(att_team) == end_x and last_team is def_team:
            cy = 0.0 if y < W / 2 else W
            cx = end_x
            self.log("corner_awarded", att_team, None, cx, cy)
            self.set_piece(att_team, "corner", cx, cy, rng.uniform(12, 25), silent=True)
        else:
            gk_team = self.opp(last_team) if self.goal_x(last_team) != end_x else last_team
            gx = 5.5 if end_x == 0.0 else L - 5.5
            team_gk = def_team
            self.log("goal_kick_awarded", team_gk, None, gx, 34)
            self.set_piece(team_gk, "goal_kick", gx, 34, rng.uniform(8, 16), silent=True)

    # ---- dead balls
    def set_piece(self, team, kind, x, y, delay, silent=False):
        if kind == "free_kick" and not silent:
            self.log("free_kick_awarded", team, None, x, y)
        if kind == "goal_kick":
            taker = self.gk(team)
        elif kind == "corner":
            taker = self.nearest(self.field(team), x, y)
        else:
            taker = self.nearest(self.field(team), x, y)
        self.mode, self.carrier, self.flight = "dead", None, None
        self.restart = {"team": team, "kind": kind, "x": x, "y": y, "taker": taker}
        self.timer = delay
        self.ball = [x, y]
        taker.x, taker.y = x, y
        taker.vx = taker.vy = 0.0
        self.override = {}
        if kind in ("corner", "free_kick") and self.ax(team, x) > 70:
            att = [p for p in self.field(team) if p is not taker]
            dfd = self.field(self.opp(team))
            gx = self.goal_x(team)
            sign = -team["dir"]
            for i, p in enumerate(sorted(att, key=lambda p: -self.ax(team, p.x))[:5]):
                self.override[p] = (gx + sign * self.rng.uniform(6, 16), 34 + self.rng.uniform(-10, 10))
            for p in dfd[:8]:
                self.override[p] = (gx + sign * self.rng.uniform(3, 14), 34 + self.rng.uniform(-11, 11))
            gk = self.gk(self.opp(team))
            self.override[gk] = (gx + sign * 3, 34)

    def do_restart(self):
        r = self.restart
        team, taker, rng = r["team"], r["taker"], self.rng
        kind = r["kind"]
        self.override = {}
        if self.pending_var is not None:
            self.pending_var = None
        self.maybe_substitute()
        if kind in ("corner", "free_kick") and self.ax(team, r["x"]) > 70 and (kind == "corner" or rng.random() < 0.75):
            self.delivery(team, taker, kind, r["x"], r["y"])
            return
        self.take_possession(taker)
        if kind == "free_kick" and self.ax(team, taker.x) > 70:
            pass
        self.next_decision = rng.uniform(0.4, 1.0)

    def delivery(self, team, taker, kind, x, y):
        rng = self.rng
        opp = self.opp(team)
        att = sorted([p for p in self.field(team) if p is not taker], key=lambda p: -self.ax(team, p.x))[:4]
        target = rng.choice(att)
        self.log("pass", team, taker, x, y, end_x=round(target.x, 1), end_y=round(target.y, 1), to=target.pid, outcome=1, length=round(hyp(target.x - x, target.y - y), 1),
                 forward=True, set_piece=kind, cross=True)
        self.last_pass = {"passer": taker, "team": team, "t": self.t, "ok": True, "kind": "corner" if kind == "corner" else "free_kick_delivery"}
        if rng.random() < 0.44 * team["str"]:
            target.x, target.y = self.goal_x(team) - team["dir"] * rng.uniform(6, 14), 34 + rng.uniform(-9, 9)
            self.ball = [target.x, target.y]
            self.shot(target, "corner" if kind == "corner" else "free_kick", "header")
        else:
            d = self.nearest(self.field(opp), self.goal_x(team) - team["dir"] * 9, 34)
            self.log("clearance", opp, d, d.x, d.y)
            d.x, d.y = self.goal_x(team) - team["dir"] * 20, 34 + rng.uniform(-18, 18)
            self.take_possession(d)

    def penalty(self, team, victim):
        rng = self.rng
        self.log("penalty_awarded", team, victim)
        taker = max(self.field(team), key=lambda p: p.skill)
        gx = self.goal_x(team)
        taker.x, taker.y = gx - team["dir"] * 11, 34
        self.ball = [taker.x, taker.y]
        self.t += rng.uniform(40, 80)
        self.stoppage += 1
        r = rng.random()
        if r < 0.77:
            outcome = "goal"
        elif r < 0.94:
            outcome = "saved"
        else:
            outcome = "off_target"
        self.shot_outcome(taker, team, outcome, 0.77, "penalty", "foot", forced=True)

    # ---- shooting
    def shot(self, shooter, situation, body):
        team = self.team_of(shooter)
        gx = self.goal_x(team)
        dist = hyp(gx - shooter.x, 34 - shooter.y)
        inbox = self.ax(team, shooter.x) > 88.5 and abs(shooter.y - 34) < 20.2
        xg = max(0.02, min(0.5, 0.04 + 0.42 * math.exp(-(dist - 6) / 9.0)))
        if body == "header":
            xg *= 0.7
        xg = min(0.5, xg * shooter.skill)
        rng = self.rng
        r = rng.random()
        if r < xg:
            outcome = "goal"
        else:
            r2 = (r - xg) / (1 - xg)
            outcome = "saved" if r2 < 0.34 else "blocked" if r2 < 0.58 else "post" if r2 < 0.63 else "off_target"
        self.shot_outcome(shooter, team, outcome, xg, situation, body)

    def shot_outcome(self, shooter, team, outcome, xg, situation, body, forced=False):
        rng = self.rng
        opp = self.opp(team)
        gk = self.gk(opp)
        gx = self.goal_x(team)
        self.log("shot", team, shooter, shooter.x, shooter.y, outcome=outcome, xg=round(xg, 2), situation=situation, body=body,
                 assist=self.assist_for(team, shooter), assist_kind=self.assist_kind_for(team, shooter))
        if outcome == "goal":
            self.goal(shooter, team, situation)
            return
        if outcome == "saved":
            self.log("save", opp, gk, gk.x, gk.y, shooter=shooter.pid)
            if rng.random() < 0.28:
                self.log("corner_awarded", team, None, gx, 0.0 if shooter.y < 34 else W)
                self.set_piece(team, "corner", gx, 0.0 if shooter.y < 34 else W, rng.uniform(12, 25), silent=True)
            else:
                gk.x, gk.y = gx - team["dir"] * 4, 34
                self.take_possession(gk)
        elif outcome == "blocked":
            d = self.nearest(self.field(opp), shooter.x + team["dir"] * 4, shooter.y)
            self.log("block", opp, d, d.x, d.y, shooter=shooter.pid)
            if rng.random() < 0.40:
                self.log("corner_awarded", team, None, gx, 0.0 if shooter.y < 34 else W)
                self.set_piece(team, "corner", gx, 0.0 if shooter.y < 34 else W, rng.uniform(12, 25), silent=True)
            else:
                self.take_possession(d)
        elif outcome == "post":
            d = self.nearest(self.field(opp), gx - team["dir"] * 8, 34)
            self.take_possession(d)
        else:
            gx_k = L - 5.5 if gx == L else 5.5
            self.log("goal_kick_awarded", opp, None, gx_k, 34)
            self.set_piece(opp, "goal_kick", gx_k, 34, rng.uniform(8, 16), silent=True)

    def assist_for(self, team, shooter):
        lp = self.last_pass
        if lp and lp["ok"] and lp["team"] is team and self.t - lp["t"] < 8 and lp["passer"] is not shooter:
            return lp["passer"].pid
        return None

    def assist_kind_for(self, team, shooter):
        lp = self.last_pass
        if lp and lp["ok"] and lp["team"] is team and self.t - lp["t"] < 8 and lp["passer"] is not shooter:
            return lp.get("kind")
        return None

    def goal(self, scorer, team, situation):
        rng = self.rng
        team["score"] += 1
        opp = self.opp(team)
        e = self.log("goal", team, scorer, scorer.x, scorer.y, situation=situation, assist=self.assist_for(team, scorer),
                     assist_kind=self.assist_kind_for(team, scorer),
                     score=[self.teams[0]["score"], self.teams[1]["score"]])
        self.stoppage += 0.7
        cancel = rng.random() < 0.07 and situation == "open_play"
        self.t += rng.uniform(25, 45)
        if cancel:
            self.t += rng.uniform(45, 90)
            team["score"] -= 1
            e["detail"]["cancelled"] = True
            self.log("var", team, scorer, scorer.x, scorer.y, decision="cancelled", reason="offside", goal_event=e["id"],
                     score=[self.teams[0]["score"], self.teams[1]["score"]])
            self.set_piece(opp, "free_kick", scorer.x, scorer.y, 6.0, silent=True)
            return
        self.reset_formation(opp)

    # ---- substitutions
    def maybe_substitute(self):
        minute = (self.t + 45 * 60 * (self.period - 1)) / 60
        for team in self.teams:
            if team["sub_plan"] and self.period == 2 and minute >= team["sub_plan"][0]:
                team["sub_plan"].pop(0)
                cands = [p for p in self.field(team)]
                off = self.rng.choice(cands)
                on = next((b for b in team["bench"] if b.role == off.role), None) or (team["bench"][0] if team["bench"] else None)
                if on is None:
                    continue
                team["bench"].remove(on)
                idx = team["players"].index(off)
                on.slot_ax, on.slot_y = off.slot_ax, off.slot_y
                on.x, on.y, on.vx, on.vy = off.x, off.y, 0.0, 0.0
                team["players"][idx] = on
                team["subs"] += 1
                self.override.pop(off, None)
                self.log("substitution", team, on, off.x, off.y, off=off.pid)
                if self.restart and self.restart.get("taker") is off:
                    self.restart["taker"] = on
                self.stoppage += 0.25

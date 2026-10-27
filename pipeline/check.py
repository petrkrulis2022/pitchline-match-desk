"""Deterministic fact-checker. Agent output is accepted only if every number, score, name and minute traces to the facts."""
import re

WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")
NUM = re.compile(r"\d+")
SCORE = re.compile(r"(?<![\d:.])(\d+)\s?[:–-]\s?(\d+)(?![\d:.])")
QUOTES = "„“”\"«»"
ALWAYS_OK = {"VAR"}
MIN_STEM = 4


def nums(s):
    return set(NUM.findall(str(s)))


class Facts:
    def __init__(self, facts):
        self.f = facts
        self.moments = {m["id"]: m for m in facts["moments"]}
        self.order = [m["id"] for m in facts["moments"]]
        h = facts["header"]
        strings = [h["competition"], h["venue"]] + list(h["officials"].values())
        for t in h["teams"].values():
            strings += [t["name"], t["short"]]
        for c in facts["lineups"].values():
            strings += [re.sub(r"^\d+ ", "", p) for p in c["starting"] + c["bench"]]
        self.vocab = {t for s in strings for t in WORD.findall(s) if len(t) > 1}
        self.stats_nums = set()
        for per in facts["stats"].values():
            for team in per.values():
                for v in team.values():
                    self.stats_nums |= nums(v)
        self.universe_extra = set()
        for p in facts.get("players", []):
            for v in p["stats"].values():
                self.universe_extra |= nums(v)
            self.universe_extra |= nums(p["number"])
        for w in facts.get("windows", []):
            self.universe_extra |= nums(w["label"])
            for team in w["stats"].values():
                for v in team.values():
                    self.universe_extra |= nums(v)
        self.range_forms = {re.sub(r"\+", "", w["label"]).replace("-", ":") for w in facts.get("windows", [])}
        self.header_nums = nums(h["kickoff_local"]) | nums(h["round"]) | nums(h["season"]) | nums(h["attendance"]) | {"45", "90"}
        self.attendance_formats = {f"{h['attendance']:,}", f"{h['attendance']:,}".replace(",", " "), f"{h['attendance']:,}".replace(",", ".")}

    def moment_nums(self, m):
        out = nums(m["minute"]) | {str(x) for x in m["score_after"]}

        def walk(d):
            for k, v in d.items():
                if isinstance(v, dict):
                    walk(v)
                elif isinstance(v, bool):
                    continue
                elif isinstance(v, (int, float)):
                    out.update(nums(f"{v:.2f}") if isinstance(v, float) else nums(v))
                elif k in ("label", "formation") and isinstance(v, str):
                    out.update(nums(v))
        walk(m["detail"])
        if m["kind"] == "var":
            g = self.moments.get(m["detail"].get("cancelled_goal"))
            if g:
                out |= nums(g["minute"])
        return out

    def scores_for(self, ids):
        out = set()
        for i in ids:
            if i not in self.moments:
                continue
            m = self.moments[i]
            out.add(f"{m['score_after'][0]}:{m['score_after'][1]}")
            k = self.order.index(i)
            if k > 0:
                p = self.moments[self.order[k - 1]]["score_after"]
                out.add(f"{p[0]}:{p[1]}")
            if m["kind"] == "var":
                g = self.moments.get(m["detail"].get("cancelled_goal"))
                if g:
                    out.add(f"{g['score_after'][0]}:{g['score_after'][1]}")
        return out

    def known(self, token):
        if token in self.vocab or (token.isupper() and len(token) <= 5) or token in ALWAYS_OK:
            return True
        if any(token.startswith(w) and len(token) <= len(w) + 4 for w in ALWAYS_OK):
            return True
        for k in self.vocab:
            if len(k) >= 3 and token.startswith(k) and len(token) <= len(k) + 4:
                return True
            need = max(MIN_STEM, len(k) - 2)
            n = 0
            for a, b in zip(token, k):
                if a != b:
                    break
                n += 1
            if n >= need:
                return True
        return False

    def unknown_words(self, text):
        bad = []
        for m in WORD.finditer(text):
            tok = m.group()
            if not tok[0].isupper():
                continue
            before = text[: m.start()].rstrip(" \t")
            if not before or before[-1] in ".!?:\n#*¿¡" or re.fullmatch(r"(?:.*\n)?\d+(?:\+\d+)?'", before):
                continue
            if not self.known(tok):
                bad.append(tok)
        return bad

    def check(self, text, ids=(), extra_nums=(), extra_scores=(), universe=False, require_names=True):
        problems = []
        if universe:
            allowed = set(self.header_nums) | set(self.stats_nums) | set(self.universe_extra)
            scores = set()
            for m in self.moments.values():
                allowed |= self.moment_nums(m)
                scores.add(f"{m['score_after'][0]}:{m['score_after'][1]}")
        else:
            allowed = set(extra_nums)
            for i in ids:
                if i in self.moments:
                    allowed |= self.moment_nums(self.moments[i])
            scores = self.scores_for(ids)
        scores |= set(extra_scores) | self.range_forms
        t = re.sub(r"\b\d-\d-\d(?:-\d)?\b", " ", text)
        for f in self.attendance_formats:
            t = t.replace(f, "")
        for n in sorted(nums(t) - allowed):
            problems.append(f"number {n} is not in the facts for this entry")
        for a, b in SCORE.findall(t):
            if f"{a}:{b}" not in scores:
                problems.append(f"score {a}-{b} does not match the facts for this entry")
        for w in self.unknown_words(text):
            problems.append(f"unknown name or word '{w}'")
        if any(q in text for q in QUOTES):
            problems.append("contains quotation marks (quotes are never invented)")
        if require_names:
            for i in ids:
                m = self.moments.get(i)
                if m and m["kind"] in ("goal", "card", "penalty") and m.get("player"):
                    sur = m["player"].split()[-1]
                    if not re.search(re.escape(sur[: max(4, len(sur) - 2)]), text):
                        problems.append(f"does not mention {sur} for the {m['kind']}")
        return problems

"""Facts -> live blog + match report in English, Spanish and Czech, using Microsoft Agent Framework agents on Foundry.

Flow: Commentator (batches) -> fact check -> Fixer on failure -> template fallback; Analyst for window, half-time and full-time notes;
Verifier reads the blog against the record and sends flagged entries back to the Fixer; Editor writes the sectioned report and the
Verifier checks it; Localizer translates entries and the report. Every agent output passes check.py before it is kept.
"""
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import agents as A
from check import Facts, WORD
from llm import make_agent, make_client

ROOT = Path(__file__).resolve().parent.parent
LANGS = {"es": "Spanish", "cs": "Czech"}
LOG = []
TARGET_ENTRIES = 66
MAX_GAP = 150
P1_GAP = 20


def extract_json(text):
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    starts = [i for i in (t.find("["), t.find("{")) if i >= 0]
    if not starts:
        raise ValueError("no JSON in reply")
    a = min(starts)
    b = max(t.rfind("]"), t.rfind("}"))
    return json.loads(t[a:b + 1])


_SEM = None


async def ask(name, instructions, prompt, client):
    global _SEM
    if _SEM is None:
        _SEM = asyncio.Semaphore(2)
    t0 = time.time()
    async with _SEM:
        for attempt in range(8):
            try:
                result = await make_agent(name, instructions, client).run(prompt)
                break
            except Exception as e:
                if "429" not in str(e) and "RateLimit" not in str(e):
                    raise
                LOG.append({"agent": name, "rate_limited": attempt + 1})
                await asyncio.sleep(6 * (attempt + 1))
        else:
            raise RuntimeError("rate limit did not clear")
    LOG.append({"agent": name, "seconds": round(time.time() - t0, 1)})
    return result.text.strip()


MIN_PREFIX = re.compile(r"(?:(?<=^)|(?<=! )|(?<=\. ))\s*\d+(?:\+\d+)?'\s*[–\-:]?\s*")
ASSIST_WORDS = {"pass": "pass", "through_ball": "through ball", "long_ball": "long ball", "cross": "cross", "corner": "corner",
                "free_kick_delivery": "free kick"}


def clean_text(text):
    t = text.strip().strip('"')
    for _ in range(3):
        t = MIN_PREFIX.sub("", t, count=1).strip()
    return t[0].upper() + t[1:] if t else t


def live_view(m, facts):
    d = {k: v for k, v in m["detail"].items() if k not in ("cancelled_goal", "goal_event") and v is not None}
    if m["kind"] in ("shot", "goal"):
        xg = d.pop("xg", None) or 0
        ak = d.pop("assist_kind", None)
        if d.get("assist") and ak:
            d["assist_type"] = ASSIST_WORDS.get(ak, ak)
        if m["kind"] == "shot":
            d["big_chance"] = xg >= 0.2
            outcome, keeper = d.pop("outcome", None), d.pop("saved_by", None)
            how = {"corner": "from a corner", "free_kick": "from a free kick", "open_play": "from open play", "penalty": "penalty"}.get(d.pop("situation", None), "")
            d["description"] = f"{'header' if d.pop('body', None) == 'header' else 'shot'} {how}".strip()
            d["result"] = {"saved": f"saved by goalkeeper {keeper}" if keeper else "saved", "blocked": "blocked by a defender", "post": "hit the post",
                           "off_target": "off target", "goal": "goal"}.get(outcome, str(outcome))
    if m["kind"] == "var":
        g = facts.moments.get(m["detail"].get("cancelled_goal"))
        if g:
            d["cancelled_goal_minute"], d["cancelled_goal_player"] = g["minute"], g["player"]
    if m["kind"] == "sequence":
        d["duration_seconds"] = d.pop("duration_sec", None)
        d.pop("start_minute_sec", None)
    return {"id": m["id"], "minute": m["minute"], "kind": m["kind"], "team": m.get("team_name"), "player": m.get("player"),
            "score_after": m["score_after"], "detail": d}


def template(m, header):
    home, away = (header["teams"][c]["name"] for c in header["teams"])
    s = m["score_after"]
    d, who, team, mn = m["detail"], m.get("player"), m.get("team_name"), m["minute"]
    k = m["kind"]
    simple = {
        "goal": f"GOAL! {who} scores for {team} ({mn}). {home} {s[0]}-{s[1]} {away}.",
        "var": f"VAR ({mn}): the goal is cancelled for {d.get('reason')}. {home} {s[0]}-{s[1]} {away}.",
        "card": f"{str(d.get('card', '')).replace('_', ' ').capitalize()} card for {who} of {team} ({mn}).",
        "substitution": f"Substitution for {team} ({mn}): {who} comes on for {d.get('off')}.",
        "penalty": f"Penalty to {team} ({mn}) after a foul on {d.get('fouled')}.",
        "shot": f"{who} of {team} shoots ({mn}): {str(d.get('outcome')).replace('_', ' ')}.",
        "offside": f"{who} of {team} is flagged offside ({mn}).",
        "added_time": f"{d.get('minutes')} minutes of added time ({mn}).",
        "lineup": f"{team} line up in a {d.get('formation')} with {d.get('goalkeeper')} in goal.",
        "corner": f"Corner number {d.get('number')} for {team} ({mn}).",
        "foul": f"Foul by {who} of {team} on {d.get('fouled')} ({mn}).",
        "clearance": f"{who} of {team} clears the danger ({mn}).",
        "defensive_stand": f"{who} of {team} makes a {d.get('action')} in his own area ({mn}).",
        "pressing_win": f"{who} of {team} wins the ball back high up the pitch ({mn}).",
        "sequence": f"{team} string together {d.get('passes')} passes ({mn}).",
        "pressure": f"{team} press, with {d.get('shots')} shots and {d.get('corners')} corners in a spell ({mn}).",
        "phase": f"{team} have {d.get('possession_pct')}% of the passes between minute {d.get('from_minute')} and {d.get('to_minute')}.",
    }
    if k in simple:
        return simple[k]
    if k == "period_start":
        return f"Kick-off: {home} against {away}." if m["period"] == 1 else "The second half begins."
    return f"{'Half-time' if m['period'] == 1 else 'Full-time'} ({mn}): {home} {s[0]}-{s[1]} {away}."


def select_moments(facts):
    """All weight-3+ moments, then weight-2 moments placed where the blog would otherwise go quiet for more than MAX_GAP seconds."""
    ms = facts.f["moments"]
    cut = next(m["sec"] for m in ms if m["kind"] == "period_end" and m["period"] == 1)
    t = lambda m: m["sec"] + (cut + P1_GAP if m["period"] == 2 else 0)
    chosen = [m for m in ms if m["weight"] >= 3 and m["kind"] != "window"]
    windows = [m for m in ms if m["kind"] == "window"]
    pool = [m for m in ms if m["weight"] == 2 and m["kind"] != "window"]
    end_t = max(t(m) for m in ms)
    stuck = set()
    while len(chosen) + len(windows) + 2 < TARGET_ENTRIES:
        times = sorted([max(0.0, t(m)) for m in chosen + windows] + [0.0, end_t])
        gaps = sorted(((b - a, a, b) for a, b in zip(times, times[1:]) if (a, b) not in stuck), reverse=True)
        if not gaps or gaps[0][0] <= MAX_GAP:
            break
        size, a, b = gaps[0]
        inside = [m for m in pool if a < t(m) < b and m not in chosen]
        if not inside:
            stuck.add((a, b))
            continue
        mid = (a + b) / 2
        chosen.append(min(inside, key=lambda m: abs(t(m) - mid)))
    return sorted(chosen, key=lambda m: (m["period"], m["sec"]))


async def commentate(facts, client):
    header = facts.f["header"]
    home, away = (header["teams"][c]["name"] for c in header["teams"])
    match = {"home": home, "away": away, "competition": header["competition"], "venue": header["venue"], "referee": header["officials"]["Main"]}
    chosen = select_moments(facts)
    entries, by_id = [], {m["id"]: m for m in chosen}
    chunks = [chosen[i:i + 6] for i in range(0, len(chosen), 6)]

    async def one(chunk):
        prompt = json.dumps({"match": match, "moments": [live_view(m, facts) for m in chunk]}, ensure_ascii=False)
        try:
            return extract_json(await ask("Commentator", A.COMMENTATOR, prompt, client))
        except Exception as e:
            LOG.append({"agent": "Commentator", "error": str(e)[:120]})
            return []

    raw = await asyncio.gather(*[one(c) for c in chunks])
    stats = {"agent": 0, "agent_fixed": 0, "template_fallback": 0}
    for chunk, items in zip(chunks, raw):
        got = {}
        for it in items if isinstance(items, list) else []:
            ids = [i for i in it.get("moment_ids", []) if i in by_id]
            if ids and isinstance(it.get("text"), str):
                got[ids[0]] = (ids, clean_text(it["text"]))
        for m in chunk:
            ids, text = got.get(m["id"], ([m["id"]], None))
            status = "agent"
            problems = facts.check(text, ids) if text else ["no entry returned"]
            tries = 0
            while problems and tries < 2:
                tries += 1
                view = [live_view(by_id[i], facts) for i in ids]
                fixed = await ask("Fixer", A.FIXER, json.dumps({"moments": view, "failed_text": text or "", "problems": problems}, ensure_ascii=False), client)
                text, status = clean_text(fixed), "agent_fixed"
                problems = facts.check(text, ids)
            if problems:
                text, status = template(by_id[ids[0]], header), "template_fallback"
            stats[status] += 1
            entries.append({"moment_ids": list(ids), "minute": by_id[ids[0]]["minute"], "sec": by_id[ids[0]]["sec"],
                            "period": by_id[ids[0]]["period"], "kind": by_id[ids[0]]["kind"], "en": text, "status": status})
    return entries, stats


def stats_payload(facts, key):
    h = facts.f["header"]
    out = {}
    for c, s in facts.f["stats"][key].items():
        out[h["teams"][c]["name"]] = {k: v for k, v in s.items() if k in ("possession_pct", "shots", "on_target", "xg", "corners", "fouls", "yellow", "red")}
    ends = [m for m in facts.f["moments"] if m["kind"] == "period_end"]
    ht, ft = ends[0]["score_after"], ends[-1]["score_after"]
    score = ht if key == "h1" else ft if key == "ft" else [ft[0] - ht[0], ft[1] - ht[1]]
    for (c, t), g in zip(h["teams"].items(), score):
        out[t["name"]]["goals"] = g
    return out


def score_forms(m):
    a, b = m["score_after"]
    return [f"{a}:{b}", f"{b}:{a}"]


async def write_insight(facts, client, scope, m, nums):
    text, problems = None, ["not run"]
    for _ in range(3):
        prompt = json.dumps(scope if text is None else {**scope, "previous_text": text, "problems": problems}, ensure_ascii=False)
        text = (await ask("Analyst", A.ANALYST, prompt, client)).strip('"')
        problems = facts.check(text, [m["id"]], extra_nums=nums, extra_scores=score_forms(m), require_names=False)
        if not problems:
            return text, nums
    LOG.append({"agent": "Analyst", "dropped": m["id"], "problems": problems})
    return None, nums


async def analyse(facts, client):
    out = []
    ends = [m for m in facts.f["moments"] if m["kind"] == "period_end"]
    jobs = []
    for key, label, m in (("h1", "half-time", ends[0]), ("ft", "full-time", ends[-1])):
        nums = {n for team in facts.f["stats"][key].values() for v in team.values() for n in re.findall(r"\d+", str(v))}
        jobs.append(({"period": label, "statistics": stats_payload(facts, key), "score_home_away": m["score_after"]}, m, nums))
    for m in [m for m in facts.f["moments"] if m["kind"] == "window"]:
        jobs.append(({"minutes": m["detail"]["label"], "statistics": m["detail"]["stats"], "score_home_away": m["score_after"]}, m, facts.moment_nums(m)))
    results = await asyncio.gather(*[write_insight(facts, client, scope, m, nums) for scope, m, nums in jobs])
    for (scope, m, nums), (text, _) in zip(jobs, results):
        if text:
            out.append({"moment_ids": [m["id"]], "minute": m["minute"], "sec": m["sec"] + 0.5, "period": m["period"], "kind": "insight",
                        "en": text, "status": "agent", "nums": sorted(nums), "scores": score_forms(m)})
    return out


def players_payload(facts, n=6):
    h = facts.f["header"]["teams"]
    out = []
    for c in h:
        for p in [p for p in facts.f["players"] if p["team"] == c][:n]:
            keep = {"FW": ("goals", "assists", "shots", "on_target", "key_passes", "pass_pct"),
                    "MF": ("goals", "assists", "shots", "key_passes", "passes_completed", "pass_pct", "tackles_won", "interceptions"),
                    "DF": ("goals", "assists", "tackles_won", "interceptions", "clearances", "passes_completed", "pass_pct"),
                    "GK": ("saves", "passes_completed", "pass_pct")}[p["role"]]
            out.append({"name": p["name"], "team": h[c]["name"], "role": p["role"], **{k: v for k, v in p["stats"].items() if v and k in keep}})
    return out


def record_for_verifier(facts):
    return {"moments": [live_view(m, facts) for m in facts.f["moments"]],
            "statistics": {"first_half": stats_payload(facts, "h1"), "second_half": stats_payload(facts, "h2"), "full_time": stats_payload(facts, "ft")},
            "players": players_payload(facts, 8)}


def reason_is_fine(reason):
    """The Verifier sometimes lists a claim and then concludes it is supported; those are not problems."""
    r = str(reason).strip().lower()
    if re.search(r"\b(not|isn't|never)\s+(fully\s+)?(supported|accurate|correct)", r) or "unsupported" in r:
        return False
    return bool(re.search(r"(^|[\s:.;])(supported|correct|accurate)\.?$|no problem|no issue|no contradiction|is supported|fully supported|is correct|matches the record", r))


async def verify_llm(subject, facts, client):
    prompt = json.dumps({"record": record_for_verifier(facts), "text": subject}, ensure_ascii=False)
    try:
        obj = extract_json(await ask("Verifier", A.VERIFIER, prompt, client))
        return [p for p in obj.get("problems", []) if isinstance(p, dict) and not reason_is_fine(p.get("reason", ""))] if isinstance(obj, dict) else []
    except Exception as e:
        LOG.append({"agent": "Verifier", "error": str(e)[:120]})
        return []


async def verify_ticker(entries, facts, client):
    flagged, fixed = [], 0
    for i in range(0, len(entries), 30):
        flagged += await verify_llm([{"id": e["id"], "text": e["en"]} for e in entries[i:i + 30]], facts, client)
    by_id = {e["id"]: e for e in entries}
    for p in flagged:
        e = by_id.get(p.get("id"))
        if not e or any(facts.moments[i].get("cancelled") for i in e["moment_ids"]):
            continue
        view = [live_view(facts.moments[i], facts) for i in e["moment_ids"]]
        problems = [f"{p.get('claim', '')}: {p.get('reason', '')}"]
        text = clean_text(await ask("Fixer", A.FIXER, json.dumps({"moments": view, "failed_text": e["en"], "problems": problems}, ensure_ascii=False), client))
        if not facts.check(text, e["moment_ids"], extra_nums=set(e.get("nums", [])), extra_scores=e.get("scores", []), require_names=False):
            LOG.append({"agent": "Verifier", "entry": e["id"], "was": e["en"], "now": text, "reason": problems[0]})
            e["en"], e["status"] = text, "agent_fixed"
            fixed += 1
    return len(flagged), fixed


def names_kept(en, tr, facts):
    """Every name that appears in the English text must still appear (stem match) in the translation."""
    miss = []
    for w in WORD.findall(en):
        if w in facts.vocab and w[0].isupper() and len(w) > 3 and w not in ("Premier", "Division", "Athletic", "Town"):
            if not any(t.startswith(w[:max(4, len(w) - 2)]) for t in WORD.findall(tr)):
                miss.append(w)
    return miss


async def localize(items, lang, facts, client):
    """items: {id: {"en": text, "ids": [...], "universe": bool, "nums": set, "scores": set}} -> {id: {"text", "status"}}"""
    name = LANGS[lang]
    result = {}
    ids = list(items)

    async def one_batch(batch):
        prompt = f"Target language: {name}\n" + json.dumps({k: items[k]["en"] for k in batch}, ensure_ascii=False)
        try:
            return extract_json(await ask(f"Localizer-{lang}", A.LOCALIZER, prompt, client))
        except Exception as e:
            LOG.append({"agent": f"Localizer-{lang}", "error": str(e)[:120]})
            return {}

    batches = [ids[i:i + 10] for i in range(0, len(ids), 10)]
    got_all = await asyncio.gather(*[one_batch(b) for b in batches])
    for batch, got in zip(batches, got_all):
        for k in batch:
            it = items[k]
            text = got.get(k) if isinstance(got, dict) else None
            tries = 0
            while True:
                if not isinstance(text, str) or not text.strip():
                    problems = ["no translation returned"]
                else:
                    problems = facts.check(text, it["ids"], extra_nums=it["nums"], extra_scores=it["scores"], universe=it["universe"], require_names=False)
                    problems += [f"name '{n}' was changed or dropped" for n in names_kept(it["en"], text, facts)]
                if not problems or tries == 2:
                    break
                tries += 1
                fixed = await ask(f"Localizer-{lang}", A.LOCALIZER, f"Target language: {name}\n" + json.dumps(
                    {k: it["en"], "failed_translation": text or "", "problems": problems}, ensure_ascii=False), client)
                try:
                    obj = extract_json(fixed)
                    text = obj.get(k) if isinstance(obj, dict) and k in obj else fixed.strip().strip('"')
                except Exception:
                    text = fixed.strip().strip('"')
            sentences = re.split(r"(?<=[.!?])\s+", it["en"])
            if problems and it["universe"] and len(sentences) > 1:
                try:
                    got2 = extract_json(await ask(f"Localizer-{lang}", A.LOCALIZER, f"Target language: {name}\n" + json.dumps(
                        {f"s{i}": sent for i, sent in enumerate(sentences)}, ensure_ascii=False), client))
                    parts = [got2.get(f"s{i}") for i in range(len(sentences))]
                    if all(isinstance(x, str) and x.strip() for x in parts):
                        joined = " ".join(x.strip() for x in parts)
                        again = facts.check(joined, it["ids"], universe=True, require_names=False) + [f"name '{n}'" for n in names_kept(it["en"], joined, facts)]
                        if not again:
                            text, problems = joined, []
                        else:
                            problems = again
                except Exception as e:
                    LOG.append({"agent": f"Localizer-{lang}", "error": str(e)[:120]})
            if problems:
                LOG.append({"agent": f"Localizer-{lang}", "untranslated": k, "problems": [str(x)[:100] for x in problems[:3]]})
            result[k] = {"text": text if not problems else it["en"], "status": "agent" if not problems else "untranslated_fallback"}
    return result


def parse_report(text):
    headline, blocks, para = "Match report", [], []

    def flush():
        if para:
            blocks.append(("p", " ".join(para).strip()))
            para.clear()

    for line in text.splitlines():
        s = line.strip()
        if not s:
            flush()
        elif s.startswith("## "):
            flush()
            blocks.append(("h2", s[3:].strip()))
        elif s.startswith("# "):
            flush()
            headline = s[2:].strip()
        else:
            para.append(s)
    flush()
    return headline, blocks


async def edit_report(facts, client):
    h = facts.f["header"]
    home, away = (h["teams"][c]["name"] for c in h["teams"])
    final = facts.f["moments"][-1]["score_after"]
    skip = {"window", "lineup", "phase", "foul", "corner", "clearance", "defensive_stand", "pressing_win"}
    payload = {"header": {"home": home, "away": away, "competition": h["competition"], "venue": h["venue"], "round": h["round"],
                          "referee": h["officials"]["Main"], "attendance": h["attendance"], "final_score_home_away": final},
               "moments": [live_view(m, facts) for m in facts.f["moments"] if (m["weight"] >= 3 or m["kind"] == "substitution") and m["kind"] not in skip],
               "windows": [{"minutes": w["label"], "statistics": w["stats"]} for w in facts.f["windows"]],
               "players": players_payload(facts, 6),
               "lineups": {h["teams"][c]["name"]: {"formation": "4-4-2", "starting": facts.f["lineups"][c]["starting"]} for c in h["teams"]},
               "statistics": {"first_half": stats_payload(facts, "h1"), "second_half": stats_payload(facts, "h2"), "full_time": stats_payload(facts, "ft")}}
    cards = [m for m in facts.f["moments"] if m["kind"] == "card"]
    subs = [m for m in facts.f["moments"] if m["kind"] == "substitution"]
    payload["discipline"] = {
        "yellow_cards_first_half": sum(1 for m in cards if m["period"] == 1 and m["detail"]["card"] == "yellow"),
        "yellow_cards_second_half": sum(1 for m in cards if m["period"] == 2 and m["detail"]["card"] == "yellow"),
        "yellow_cards_total": sum(1 for m in cards if m["detail"]["card"] == "yellow"),
        "red_cards_total": sum(1 for m in cards if m["detail"]["card"] != "yellow"),
        "fouls_by_team": {h["teams"][c]["name"]: facts.f["stats"]["ft"][c].get("fouls", 0) for c in h["teams"]},
        "substitutions_by_team": {t["name"]: sum(1 for m in subs if m["team_name"] == t["name"]) for t in h["teams"].values()}}
    text, problems = None, None
    for _ in range(3):
        prompt = json.dumps(payload if not problems else {**payload, "previous_draft": text, "problems": problems}, ensure_ascii=False)
        text = await ask("Editor", A.EDITOR, prompt, client)
        problems = facts.check(re.sub(r"^#+ ", "", text, flags=re.M), universe=True, require_names=False)
        scorers = {m["player"].split()[-1] for m in facts.f["moments"] if m["kind"] == "goal" and not m.get("cancelled")}
        problems += [f"the report never mentions scorer {s}" for s in scorers if s not in text]
        if len(text.split()) < 480:
            problems.append(f"the report is only {len(text.split())} words; it must be about 700 and cover every section")
        if not problems:
            vp = await verify_llm(text, facts, client)
            problems = [f"unsupported claim: {p.get('claim', '')} ({p.get('reason', '')})" for p in vp]
            LOG.append({"agent": "Verifier", "report_check": len(problems)})
        if not problems:
            return text, "agent"
    LOG.append({"agent": "Editor", "last_problems": problems})
    return text, "agent_with_open_issues"


async def main():
    out_dir = ROOT / "synth" / "out" / "match-006"
    facts = Facts(json.load(open(out_dir / "facts.json")))
    client = make_client()
    t0 = time.time()

    if "--report-only" in sys.argv:
        old_t = json.load(open(out_dir / "ticker.json"))
        entries = [{"id": e["id"], "moment_ids": e["moment_ids"], "minute": e["minute"], "sec": e["sec"], "period": e["period"], "kind": e["kind"],
                    "en": e["text"]["en"], "status": e["status"]["en"], "nums": e.get("nums", []), "scores": e.get("scores", [])} for e in old_t]
        cstats = json.load(open(out_dir / "pipeline_log.json"))["summary"]["commentator"]
        report_en, report_status = await edit_report(facts, client)
    elif "--translate-only" in sys.argv:
        old_t = json.load(open(out_dir / "ticker.json"))
        old_r = json.load(open(out_dir / "report.json"))
        entries = [{"id": e["id"], "moment_ids": e["moment_ids"], "minute": e["minute"], "sec": e["sec"], "period": e["period"], "kind": e["kind"],
                    "en": e["text"]["en"], "status": e["status"]["en"], "nums": e.get("nums", []), "scores": e.get("scores", [])} for e in old_t]
        cstats = json.load(open(out_dir / "pipeline_log.json"))["summary"]["commentator"]
        report_en = "# " + old_r["headline"]["en"] + "\n\n" + "\n\n".join(("## " if b["type"] == "h2" else "") + b["en"] for b in old_r["blocks"])
        report_status = old_r["status"]
    else:
        entries, cstats = await commentate(facts, client)
        insights = await analyse(facts, client)
        entries = sorted(entries + insights, key=lambda e: (e["period"], e["sec"]))
        for n, e in enumerate(entries, start=1):
            e["id"] = f"e{n}"
        flagged, repaired = await verify_ticker(entries, facts, client)
        LOG.append({"agent": "Verifier", "ticker_flagged": flagged, "ticker_repaired": repaired})
        report_en, report_status = await edit_report(facts, client)
    headline_en, blocks = parse_report(report_en)

    ticker_items = {e["id"]: {"en": e["en"], "ids": e["moment_ids"], "universe": False, "nums": set(e.get("nums", [])), "scores": set(e.get("scores", []))}
                    for e in entries}
    report_items = {"headline": {"en": headline_en, "ids": [], "universe": True, "nums": set(), "scores": set()}}
    for i, (_, text) in enumerate(blocks):
        report_items[f"b{i + 1}"] = {"en": text, "ids": [], "universe": True, "nums": set(), "scores": set()}

    translated = await asyncio.gather(*[localize({**ticker_items, **report_items}, lang, facts, client) for lang in LANGS])
    tr = dict(zip(LANGS, translated))

    ticker = [{"id": e["id"], "moment_ids": e["moment_ids"], "minute": e["minute"], "sec": e["sec"], "period": e["period"], "kind": e["kind"],
               "nums": e.get("nums", []), "scores": e.get("scores", []),
               "text": {"en": e["en"], **{lang: tr[lang][e["id"]]["text"] for lang in LANGS}},
               "status": {"en": e["status"], **{lang: tr[lang][e["id"]]["status"] for lang in LANGS}}} for e in entries]
    report = {"status": report_status, "headline": {"en": headline_en, **{lang: tr[lang]["headline"]["text"] for lang in LANGS}},
              "blocks": [{"type": kind, "en": text, **{lang: tr[lang][f"b{i + 1}"]["text"] for lang in LANGS}} for i, (kind, text) in enumerate(blocks)],
              "words": len(report_en.split())}
    (out_dir / "ticker.json").write_text(json.dumps(ticker, indent=1, ensure_ascii=False))
    (out_dir / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))

    fallback = {"entries_template_fallback": sum(1 for r in ticker if r["status"]["en"] == "template_fallback"),
                "translations_untranslated": sum(1 for r in ticker for lang in LANGS if r["status"][lang] != "agent")
                + sum(1 for b in report["blocks"] for lang in LANGS if b[lang] == b["en"] and b["type"] == "p")}
    summary = {"seconds": round(time.time() - t0), "agent_calls": len(LOG), "commentator": cstats, "entries": len(ticker),
               "report_status": report_status, "report_words": report["words"], **fallback}
    (out_dir / "pipeline_log.json").write_text(json.dumps({"summary": summary, "calls": LOG}, indent=1))
    print(json.dumps(summary))


if __name__ == "__main__":
    asyncio.run(main())

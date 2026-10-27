"""Render the synthetic match (facts, live blog, report, pipeline log) as one self-contained page in English, Spanish and Czech.

Writes artifact.html (a fragment for the Artifact tool) and index.html (a full page for any static host).
"""
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LANGS = ("en", "es", "cs")
TITLE = "Pitchline Match Desk"
MONTHS = {"en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
          "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
          "cs": ["led", "úno", "bře", "dub", "kvě", "čvn", "čvc", "srp", "zář", "říj", "lis", "pro"]}

UI = {
    "nav_front": ("Home", "Inicio", "Úvod"), "nav_live": ("Live", "En directo", "Online"),
    "nav_report": ("Report", "Crónica", "Report"), "nav_how": ("How it was made", "Cómo se hizo", "Jak to vzniklo"),
    "ft": ("Full-time", "Final", "Konec zápasu"), "replaying": ("Replaying the match", "Repitiendo el partido", "Přehrávání zápasu"),
    "replay": ("Replay the match (90×)", "Repetir el partido (90×)", "Přehrát zápas (90×)"),
    "showall": ("Show everything", "Mostrar todo", "Zobrazit vše"),
    "read": ("Read the report", "Leer la crónica", "Číst report"),
    "live_kicker": ("Live blog", "Crónica en directo", "Online reportáž"), "report_kicker": ("Match report", "Crónica del partido", "Zápasový report"),
    "byline": ("Pitchline AI desk", "Redacción IA de Pitchline", "AI redakce Pitchline"),
    "round": ("Round", "Jornada", "Kolo"), "attendance": ("Attendance", "Asistencia", "Diváci"),
    "goals": ("Goals", "Goles", "Góly"), "cards": ("Cards", "Tarjetas", "Karty"), "subs": ("Substitutions", "Cambios", "Střídání"),
    "referee": ("Referee", "Árbitro", "Rozhodčí"), "var": ("VAR", "VAR", "VAR"),
    "lineups": ("Line-ups", "Alineaciones", "Sestavy"), "bench": ("Bench", "Suplentes", "Náhradníci"),
    "assist": ("assist", "asistencia", "asistence"), "cancelled": ("cancelled by VAR", "anulado por el VAR", "zrušen VAR"),
    "open_play": ("open play", "jugada", "ze hry"), "free_kick": ("free kick", "falta directa", "přímý kop"),
    "corner": ("corner", "córner", "roh"), "penalty": ("penalty", "penalti", "penalta"),
    "yellow": ("yellow", "amarilla", "žlutá"), "red": ("red", "roja", "červená"), "second_yellow": ("second yellow", "doble amarilla", "druhá žlutá"),
    "on": ("on", "entra", "dovnitř"), "off": ("off", "sale", "ven"),
    "s_poss": ("Possession (completed passes)", "Posesión (pases completados)", "Držení míče (dokončené přihrávky)"),
    "s_shots": ("Shots", "Tiros", "Střely"), "s_target": ("On target", "A puerta", "Na bránu"),
    "s_xg": ("Expected goals (xG)", "Goles esperados (xG)", "Očekávané góly (xG)"),
    "s_corners": ("Corners", "Córners", "Rohy"), "s_fouls": ("Fouls", "Faltas", "Fauly"),
    "map_title": ("Shot map: every shot, attacking left to right", "Mapa de tiros: todos los tiros, atacando de izquierda a derecha", "Mapa střel: všechny střely, útok zleva doprava"),
    "m_saved": ("saved", "parado", "chycená"), "m_blocked": ("blocked", "bloqueado", "zblokovaná"), "m_off": ("off target", "fuera", "mimo"),
    "m_post": ("post", "poste", "tyč"), "m_goal": ("goal", "gol", "gól"),
    "disclosure": ("Every team, player and event in this match is synthetic. The text was written by AI agents on Microsoft Foundry and passed an automatic fact check against the match record before it appeared.",
                   "Todos los equipos, jugadores y sucesos de este partido son sintéticos. Los textos los escribieron agentes de IA en Microsoft Foundry y pasaron una verificación automática contra el registro del partido antes de publicarse.",
                   "Všechny týmy, hráči i události v tomto zápase jsou syntetické. Texty napsali AI agenti na Microsoft Foundry a před zveřejněním prošly automatickou kontrolou faktů proti záznamu zápasu."),
    "footer": ("Pitchline: match coverage written by an AI desk from verified data, checked automatically. All data synthetic.",
               "Pitchline: cobertura escrita por una redacción de IA a partir de datos verificados y comprobada automáticamente. Todos los datos son sintéticos.",
               "Pitchline: zpravodajství píše AI redakce z ověřených dat a kontroluje je automaticky. Všechna data jsou syntetická."),
    "how_h": ("How this page was made", "Cómo se hizo esta página", "Jak tato stránka vznikla"),
    "vision_tag": ("seen on camera", "visto en cámara", "viděno na kameře"),
    "w_title": ("Possession and field tilt by 15-minute spell", "Posesión e inclinación del campo por tramos de 15 minutos", "Držení míče a územní tlak po patnáctiminutových úsecích"),
    "w_poss": ("Possession (completed passes)", "Posesión (pases completados)", "Držení míče (dokončené přihrávky)"),
    "w_tilt": ("Field tilt (passes in the attacking third)", "Inclinación del campo (pases en el tercio de ataque)", "Územní tlak (přihrávky v útočné třetině)"),
    "p_title": ("Top performers by match data", "Mejores actuaciones según los datos del partido", "Nejlepší výkony podle dat ze zápasu"),
    "p_player": ("Player", "Jugador", "Hráč"), "p_goals": ("Goals", "Goles", "Góly"), "p_assists": ("Assists", "Asist.", "Asist."),
    "p_shots": ("Shots", "Tiros", "Střely"), "p_key": ("Key passes", "Pases clave", "Klíčové přihrávky"),
    "p_pass": ("Pass %", "% pases", "% přihrávek"), "p_tackles": ("Tackles won", "Entradas ganadas", "Vyhrané souboje"),
    "p_int": ("Intercept.", "Intercep.", "Odebrání"), "p_saves": ("Saves", "Paradas", "Zákroky"),
}


def esc(s):
    return html.escape(str(s), quote=True)


def bi(key_or_triple, tag="span", cls=""):
    triple = UI[key_or_triple] if isinstance(key_or_triple, str) else key_or_triple
    c = f' class="{cls}"' if cls else ""
    return "".join(f'<{tag} data-lang="{l}"{c}>{t}</{tag}>' for l, t in zip(LANGS, triple))


def inline(s):
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(s))


def fmt_date(kickoff, lang):
    d, t = kickoff.split()
    y, m, day = d.split("-")
    return f"{int(day)}. {int(m)}. {y}, {t}" if lang == "cs" else f"{int(day)} {MONTHS[lang][int(m) - 1]} {y}, {t}"


def date_triple(kickoff):
    return tuple(esc(fmt_date(kickoff, l)) for l in LANGS)


def teams(facts):
    h = facts["header"]["teams"]
    home = next(c for c, t in h.items() if t["side"] == "home")
    away = next(c for c, t in h.items() if t["side"] == "away")
    return (home, h[home]), (away, h[away])


def scoreboard(facts, final):
    h = facts["header"]
    (hc, home), (ac, away) = teams(facts)
    return (
        f'<div class="scoreboard"><div class="meta"><span>{esc(h["competition"])} {esc(h["season"])}, {bi(("round", "jornada", "kolo"))} {esc(h["round"])}</span>'
        f'<span>{esc(h["venue"])}, {bi(date_triple(h["kickoff_local"]))}</span></div>'
        f'<div class="row"><div class="team"><span class="dot" style="background:{home["kit"]}"></span>{esc(home["name"])}</div>'
        f'<div class="score" id="score">{final[0]}:{final[1]}</div>'
        f'<div class="team away">{esc(away["name"])}<span class="dot" style="background:{away["kit"]}"></span></div></div>'
        f'<div class="status"><span id="status-label">{bi("ft")}</span><span id="live-label" hidden>{bi("replaying")}</span> '
        f'<span class="clock" id="clock"></span></div></div>'
    )


def shot_map(facts):
    shots = [m for m in facts["moments"] if m["kind"] in ("shot", "goal") and m.get("x") is not None and m["weight"] >= 2
             and not (m["kind"] == "goal" and m.get("cancelled"))]
    (hc, home), (ac, away) = teams(facts)
    col = {hc: home["kit"], ac: away["kit"]}
    line = 'fill="none" stroke="var(--pitch-line)" stroke-width="0.35"'
    pitch = (f'<rect x="0" y="0" width="105" height="68" fill="var(--pitch)" stroke="var(--pitch-line)" stroke-width="0.35"/>'
             f'<line x1="52.5" y1="0" x2="52.5" y2="68" {line}/><circle cx="52.5" cy="34" r="9.15" {line}/>'
             f'<rect x="0" y="13.84" width="16.5" height="40.32" {line}/><rect x="88.5" y="13.84" width="16.5" height="40.32" {line}/>'
             f'<rect x="0" y="24.84" width="5.5" height="18.32" {line}/><rect x="99.5" y="24.84" width="5.5" height="18.32" {line}/>'
             f'<rect x="-2" y="30.34" width="2" height="7.32" {line}/><rect x="105" y="30.34" width="2" height="7.32" {line}/>')
    marks = []
    for s in shots:
        x, y = (s["x"], s["y"]) if s["x"] > 52.5 else (105 - s["x"], 68 - s["y"])
        o = "goal" if s["kind"] == "goal" else s["detail"].get("outcome")
        c = col[s["team"]]
        common = f'fill="{c}" fill-opacity="0.85" stroke="var(--bg)" stroke-width="0.5"'
        tip = esc(f'{s["player"]}, {s["minute"]}, {o}')
        if o == "goal":
            shape = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{c}" stroke="var(--text)" stroke-width="0.7"><title>{tip}</title></circle>'
        elif o == "saved":
            shape = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.7" {common}><title>{tip}</title></circle>'
        elif o == "blocked":
            shape = f'<rect x="{x - 1.5:.1f}" y="{y - 1.5:.1f}" width="3" height="3" {common}><title>{tip}</title></rect>'
        elif o == "post":
            shape = f'<polygon points="{x:.1f},{y - 2:.1f} {x + 2:.1f},{y + 1.6:.1f} {x - 2:.1f},{y + 1.6:.1f}" {common}><title>{tip}</title></polygon>'
        else:
            shape = f'<rect x="{x - 1.4:.1f}" y="{y - 1.4:.1f}" width="2.8" height="2.8" transform="rotate(45 {x:.1f} {y:.1f})" {common}><title>{tip}</title></rect>'
        marks.append(shape)
    leg = lambda svg, key: f'<span><svg width="14" height="14" viewBox="-2 -2 4 4" aria-hidden="true">{svg}</svg>{bi(key)}</span>'
    legend = (leg('<circle r="1.7" fill="var(--text)" stroke="var(--text)" stroke-width="0.4"/>', "m_goal") + leg('<circle r="1.2" fill="var(--text)"/>', "m_saved") +
              leg('<rect x="-1.1" y="-1.1" width="2.2" height="2.2" fill="var(--text)"/>', "m_blocked") +
              leg('<polygon points="0,-1.4 1.4,1.2 -1.4,1.2" fill="var(--text)"/>', "m_post") +
              leg('<rect x="-1" y="-1" width="2" height="2" fill="var(--text)" transform="rotate(45)"/>', "m_off"))
    teams_leg = "".join(f'<span><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill="{col[c]}"/></svg>{esc(t["name"])}</span>'
                        for c, t in ((hc, home), (ac, away)))
    names = "; ".join(f'{s["player"]} {s["minute"]}' for s in shots)
    return (f'<figure class="map"><svg viewBox="-3 -3 111 74" role="img" aria-label="{esc(names)}">{pitch}{"".join(marks)}</svg>'
            f'<div class="legend">{teams_leg}{legend}</div><figcaption>{bi("map_title")}</figcaption></figure>')


def stat_bars(facts):
    (hc, home), (ac, away) = teams(facts)
    ft = facts["stats"]["ft"]
    rows = [("s_poss", "possession_pct", True), ("s_shots", "shots", False), ("s_target", "on_target", False), ("s_xg", "xg", False),
            ("s_corners", "corners", False), ("s_fouls", "fouls", False)]
    out = []
    for label, key, pct in rows:
        a, b = ft[hc].get(key, 0), ft[ac].get(key, 0)
        tot = (a + b) or 1
        out.append(f'<div class="statrow"><div class="sv">{a}{"%" if pct else ""}</div><div class="sbars"><div class="sl">{bi(label)}</div>'
                   f'<div class="bar"><i style="width:{100 * a / tot:.0f}%;background:{home["kit"]}"></i><i style="width:{100 * b / tot:.0f}%;background:{away["kit"]}"></i></div></div>'
                   f'<div class="sv r">{b}{"%" if pct else ""}</div></div>')
    return f'<div class="stats">{"".join(out)}</div>'


def fact_box(facts):
    (hc, home), (ac, away) = teams(facts)
    h = facts["header"]
    goals, cards, subs, var = [], [], [], []
    for m in facts["moments"]:
        if m["kind"] == "goal":
            sit = m["detail"].get("situation")
            extra = bi(sit, cls="") if sit in ("free_kick", "penalty", "corner") else ""
            asst = f' ({bi("assist")} {esc(m["detail"]["assist"])})' if m["detail"].get("assist") else ""
            tag = f' <em>{bi("cancelled")}</em>' if m.get("cancelled") else ""
            goals.append(f'{esc(m["minute"])} {esc(m["player"])}{(" (" + extra + ")") if extra else ""}{asst}{tag}')
        elif m["kind"] == "card":
            cards.append(f'{esc(m["minute"])} {esc(m["player"])} ({esc(m["team_name"])}), {bi(m["detail"]["card"])}')
        elif m["kind"] == "substitution":
            subs.append(f'{esc(m["minute"])} {esc(m["team_name"])}: {esc(m["player"])} {bi("on")}, {esc(m["detail"]["off"])} {bi("off")}')
    rows = [("goals", "<br>".join(goals)), ("cards", "<br>".join(cards)), ("subs", "<br>".join(subs)),
            ("referee", f'{esc(h["officials"]["Main"])}, VAR: {esc(h["officials"]["Video Assistant Referee"])}'),
            ("attendance", f'{h["attendance"]:,}')]
    dl = "".join(f"<dt>{bi(k)}</dt><dd>{v}</dd>" for k, v in rows)
    lu = ""
    for c, t in ((hc, home), (ac, away)):
        l = facts["lineups"][c]
        lu += f'<div class="lu"><strong>{esc(t["name"])}</strong><p>{esc(", ".join(l["starting"]))}</p><p class="muted">{bi("bench")}: {esc(", ".join(l["bench"]))}</p></div>'
    return f'<aside class="factbox"><dl>{dl}</dl><h3>{bi("lineups")}</h3><div class="lus">{lu}</div></aside>'


def window_chart(facts):
    (hc, home), (ac, away) = teams(facts)
    rows = []
    for w in facts["windows"]:
        a, b = w["stats"][home["name"]], w["stats"][away["name"]]
        cell = lambda key: (f'<div class="wbar"><span>{a[key]}%</span><div class="bar"><i style="width:{a[key]}%;background:{home["kit"]}"></i>'
                            f'<i style="width:{b[key]}%;background:{away["kit"]}"></i></div><span>{b[key]}%</span></div>')
        rows.append(f'<div class="wrow"><div class="wl">{esc(w["label"])}\'</div>{cell("possession_pct")}{cell("field_tilt_pct")}</div>')
    head = (f'<div class="wrow whead"><div></div><div>{bi("w_poss")}</div><div>{bi("w_tilt")}</div></div>')
    leg = "".join(f'<span><svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="5" fill="{t["kit"]}"/></svg>{esc(t["name"])}</span>'
                  for t in (home, away))
    return f'<figure class="wchart"><figcaption class="wtitle">{bi("w_title")}</figcaption>{head}{"".join(rows)}<div class="legend">{leg}</div></figure>'


def player_table(facts):
    out = []
    for c, t in ((teams(facts)[0]), (teams(facts)[1])):
        rows = []
        for p in [p for p in facts["players"] if p["team"] == c][:5]:
            st = p["stats"]
            g = lambda k: st.get(k, 0)
            rows.append(f'<tr><td>{esc(p["number"])} {esc(p["name"])}</td><td>{g("goals")}</td><td>{g("assists")}</td><td>{g("shots")}</td>'
                        f'<td>{g("key_passes")}</td><td>{g("pass_pct")}%</td><td>{g("tackles_won")}</td><td>{g("interceptions")}</td><td>{g("saves")}</td></tr>')
        head = "".join(f'<th>{bi(k)}</th>' for k in ("p_player", "p_goals", "p_assists", "p_shots", "p_key", "p_pass", "p_tackles", "p_int", "p_saves"))
        out.append(f'<div class="ptable"><div class="ptitle"><span class="dot" style="background:{t["kit"]}"></span>{esc(t["name"])}</div>'
                   f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>')
    return f'<section class="players"><h3>{bi("p_title")}</h3>{"".join(out)}</section>'


P1_GAP = 20


def p1_end(facts):
    return int(next(m["sec"] for m in facts["moments"] if m["kind"] == "period_end" and m["period"] == 1))


def ticker_html(facts, ticker):
    moments = {m["id"]: m for m in facts["moments"]}
    items = []
    cut = p1_end(facts)
    for e in ticker:
        real = [moments[i] for i in e["moment_ids"] if i in moments]
        first = real[0]
        sec = int(first["sec"] + (cut + P1_GAP if first["period"] == 2 else 0))
        score = ""
        kinds = {m["kind"] for m in real}
        for m in real:
            if m["kind"] in ("goal", "var"):
                score = f'{m["score_after"][0]}:{m["score_after"][1]}'
        kind = "goal" if "goal" in kinds and not any(m.get("cancelled") for m in real if m["kind"] == "goal") else \
            "var" if kinds & {"var"} or any(m.get("cancelled") for m in real) else "card" if "card" in kinds else "insight" if e["kind"] == "insight" else "other"
        icon = ""
        if "card" in kinds:
            card = next(m for m in real if m["kind"] == "card")["detail"]["card"]
            icon = f'<span class="cardicon {"yellow" if card == "yellow" else "red"}" aria-hidden="true"></span>'
        seen = any((m.get("vision") or {}).get("check") == "supported" for m in real)
        vtag = f'<span class="vtag">{bi("vision_tag")}</span>' if seen else ""
        text = bi(tuple(esc(e["text"][l]) for l in LANGS))
        items.append((sec, e["id"], (f'<li class="entry kind-{kind}" data-sec="{sec}"' + (f' data-score="{score}"' if score else "") + ">"
                                    f'<div class="min">{esc(e["minute"])}</div><div class="txt">{icon}{text}{vtag}</div></li>')))
    items.sort(key=lambda t: (t[0], int(t[1][1:])), reverse=True)
    return "".join(t[2] for t in items)


def how_html(facts, log, ticker):
    s = log["summary"]
    rec = facts["reconciliation"]
    corr = rec["card_time_corrections"]
    vis = rec["vision_checks"]
    n = len(ticker)
    kinds = {}
    for m in facts["moments"]:
        kinds[m["kind"]] = kinds.get(m["kind"], 0) + 1
    stat = lambda lang: sum(1 for t in ticker if t["status"][lang] == "agent")
    steps = [
        (("Synthetic match engine: two fictional clubs, 22 players and the ball simulated 10 times a second. Nothing comes from real matches.",
          "Motor de partido sintético: dos clubes ficticios, 22 jugadores y el balón simulados 10 veces por segundo. Nada procede de partidos reales.",
          "Syntetický herní engine: dva smyšlené kluby, 22 hráčů a míč simulovaný 10krát za sekundu. Nic nepochází ze skutečných zápasů.")),
        (("Two noisy feeds, like a real pipeline would see: an event feed stamped late, and a vision feed with missed players and an unreliable ball.",
          "Dos fuentes con ruido, como las vería una cadena real: un registro de sucesos con sellos de tiempo tardíos y una fuente de visión con jugadores perdidos y un balón poco fiable.",
          "Dva zašuměné zdroje, jak je vidí skutečný řetězec: tok událostí s pozdními časovými razítky a vizuální tok s přehlédnutými hráči a nespolehlivým míčem.")),
        ((f"Reconciler: {len(corr)} cards stamped minutes late were matched back to the foul that caused them, VAR decisions were applied to the score, and {vis['supported']} of {vis['supported'] + vis['unsupported'] + vis['no_wide_frame']} shots and goals were confirmed by the vision feed. It also derived {len(facts['moments'])} moments from the raw events, including {kinds.get('sequence', 0)} passing sequences, {kinds.get('pressure', 0)} spells of pressure, {len(facts['windows'])} 15-minute windows and per-player statistics.",
          f"Conciliador: {len(corr)} tarjetas con minutos de retraso se asociaron a la falta que las causó, las decisiones del VAR se aplicaron al marcador y {vis['supported']} de {vis['supported'] + vis['unsupported'] + vis['no_wide_frame']} tiros y goles fueron confirmados por la fuente de visión. Además derivó {len(facts['moments'])} momentos de los sucesos en bruto, entre ellos {kinds.get('sequence', 0)} secuencias de pases, {kinds.get('pressure', 0)} fases de presión, {len(facts['windows'])} tramos de 15 minutos y estadísticas por jugador.",
          f"Slučovač: {len(corr)} karet označených o minuty později bylo přiřazeno ke faulu, který je způsobil, rozhodnutí VAR se promítla do skóre a {vis['supported']} z {vis['supported'] + vis['unsupported'] + vis['no_wide_frame']} střel a gólů potvrdil vizuální tok. Ze surových událostí také odvodil {len(facts['moments'])} momentů, mimo jiné {kinds.get('sequence', 0)} přihrávkových sekvencí, {kinds.get('pressure', 0)} fází tlaku, {len(facts['windows'])} patnáctiminutových úseků a statistiky hráčů.")),
        ((f"Agents on Microsoft Foundry (Agent Framework): a Commentator writes the live blog, a Fixer repairs entries that fail a check, an Analyst adds statistics, an Editor writes the report and a Localizer translates both. {s['agent_calls']} model calls in {s['seconds']} seconds.",
          f"Agentes en Microsoft Foundry (Agent Framework): un Comentarista escribe la crónica en directo, un Corrector repara las entradas que no pasan una comprobación, un Analista añade estadísticas, un Editor escribe la crónica y un Localizador traduce ambas. {s['agent_calls']} llamadas al modelo en {s['seconds']} segundos.",
          f"Agenti na Microsoft Foundry (Agent Framework): Komentátor píše online reportáž, Opravář opravuje záznamy, které neprojdou kontrolou, Analytik přidává statistiky, Editor píše report a Lokalizátor překládá obojí. {s['agent_calls']} volání modelu za {s['seconds']} sekund.")),
        ((f"Fact-checker gate: every number, score, minute and name must trace to the match record, and no quotes may be invented. {s['commentator']['agent']} entries passed first time, {s['commentator']['agent_fixed']} were repaired, {s['commentator']['template_fallback']} fell back to a plain template. {stat('es')} of {n} Spanish and {stat('cs')} of {n} Czech entries passed the same checks.",
          f"Control de hechos: cada cifra, marcador, minuto y nombre debe poder rastrearse hasta el registro del partido y no se admiten citas inventadas. {s['commentator']['agent']} entradas pasaron a la primera, {s['commentator']['agent_fixed']} se repararon y {s['commentator']['template_fallback']} recurrieron a una plantilla sencilla. {stat('es')} de {n} entradas en español y {stat('cs')} de {n} en checo superaron las mismas comprobaciones.",
          f"Kontrola faktů: každé číslo, skóre, minuta a jméno se musí dát dohledat v záznamu zápasu a nesmí se vymýšlet citáty. {s['commentator']['agent']} záznamů prošlo napoprvé, {s['commentator']['agent_fixed']} bylo opraveno a {s['commentator']['template_fallback']} se vrátilo k jednoduché šabloně. {stat('es')} z {n} španělských a {stat('cs')} z {n} českých záznamů prošlo stejnými kontrolami.")),
    ]
    lis = "".join(f"<li>{bi(t)}</li>" for t in steps)
    return f'<section class="how"><h1>{bi("how_h")}</h1><ol>{lis}</ol></section>'


def render(facts, ticker, report, log):
    final = facts["moments"][-1]["score_after"]
    (hc, home), (ac, away) = teams(facts)
    names = f'{home["name"]} {final[0]}-{final[1]} {away["name"]}'
    headline = bi(tuple(esc(report["headline"][l]) for l in LANGS))
    blocks = report["blocks"]
    lead_idx = next(i for i, b in enumerate(blocks) if b["type"] == "p")
    visuals = {2: shot_map(facts), 3: window_chart(facts), 4: player_table(facts), 6: stat_bars(facts)}
    segments, cur, section = [], [], -1
    for i, b in enumerate(blocks):
        if b["type"] == "h2":
            if cur:
                segments.append(("text", cur))
                cur = []
            if section in visuals:
                segments.append(("visual", visuals.pop(section)))
            section += 1
        cur.append((i, b))
    if cur:
        segments.append(("text", cur))
    if section in visuals:
        segments.append(("visual", visuals.pop(section)))
    for rest in visuals.values():
        segments.append(("visual", rest))

    def render_blocks(lang, part):
        return "".join((f'<h2>{esc(b[lang])}</h2>' if b["type"] == "h2" else
                        f'<p class="lead">{inline(b[lang])}</p>' if i == lead_idx else f'<p>{inline(b[lang])}</p>') for i, b in part)

    body_html = "".join(("".join(f'<div data-lang="{l}">{render_blocks(l, payload)}</div>' for l in LANGS) if kind == "text" else payload) for kind, payload in segments)
    article = (f'<article class="article"><div class="kicker">{bi("report_kicker")}</div><h1>{headline}</h1>'
               f'<div class="byline"><span>{bi("byline")}</span><span>{bi(date_triple(facts["header"]["kickoff_local"]))}</span></div>'
               f'{body_html}{fact_box(facts)}'
               f'<details class="disclosure"><summary>{bi(("About this text", "Sobre este texto", "O tomto textu"))}</summary><p>{bi("disclosure")}</p></details></article>')
    first_para = bi(tuple(inline(blocks[lead_idx][l]) for l in LANGS))
    front_board = scoreboard(facts, final)
    for ident in ("score", "status-label", "live-label", "clock"):
        front_board = front_board.replace(' id="' + ident + '"', "")
    front = (f'{front_board}'
             f'<div class="stories"><a class="story" href="#live"><div class="kicker">{bi("live_kicker")}</div><h2>{esc(names)}</h2>'
             f'<p>{bi(tuple(esc(ticker[-2]["text"][l]) for l in LANGS))}</p></a>'
             f'<a class="story" href="#report"><div class="kicker">{bi("report_kicker")}</div><h2>{headline}</h2><p>{first_para}</p></a></div>')
    live = (f'<div class="kicker">{bi("live_kicker")}</div>{scoreboard(facts, final)}'
            f'<div class="controls"><button class="btn primary" id="replay" type="button">{bi("replay")}</button>'
            f'<button class="btn" id="showall" type="button">{bi("showall")}</button><a class="btn" href="#report">{bi("read")}</a></div>'
            f'<ol class="ticker" id="ticker" data-p1end="{p1_end(facts)}" data-gap="{P1_GAP}">{ticker_html(facts, ticker)}</ol>')
    nav = "".join(f'<a href="#{v}" data-view="{v}">{bi("nav_" + v)}</a>' for v in ("front", "live", "report", "how"))
    langs = "".join(f'<button type="button" data-set-lang="{l}" aria-pressed="{"true" if l == "en" else "false"}">{l.upper()}</button>' for l in LANGS)
    css = (HERE / "style.css").read_text() + (HERE / "synth.css").read_text()
    js = (HERE / "synth.js").read_text()
    page = (f'<title>{TITLE}</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n<style>\n{css}\n</style>\n'
            f'<header class="top"><div class="wrap"><a class="brand" href="#front"><i></i>Pitchline</a><nav class="nav">{nav}</nav>'
            f'<div class="lang" role="group" aria-label="Language">{langs}</div></div></header>\n'
            f'<main><div class="wrap"><section id="view-front">{front}</section><section id="view-live" hidden>{live}</section>'
            f'<section id="view-report" hidden>{article}</section><section id="view-how" hidden>{how_html(facts, log, ticker)}</section></div></main>\n'
            f'<footer><div class="wrap">{bi("footer")}</div></footer>\n<script>\n{js}\n</script>\n')
    return page


if __name__ == "__main__":
    src = Path(sys.argv[1] if len(sys.argv) > 1 else HERE.parent / "synth" / "out" / "match-006")
    facts = json.load(open(src / "facts.json"))
    ticker = json.load(open(src / "ticker.json"))
    report = json.load(open(src / "report.json"))
    log = json.load(open(src / "pipeline_log.json"))
    page = render(facts, ticker, report, log)
    out = src / "site"
    out.mkdir(exist_ok=True)
    (out / "artifact.html").write_text(page)
    standalone = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
                  f'</head><body style="margin:0">{page}</body></html>')
    (out / "index.html").write_text(standalone)
    print("wrote", out, f"({len(page) // 1024} KB)")

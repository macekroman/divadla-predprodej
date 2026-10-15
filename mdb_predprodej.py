"""Vygeneruje HTML přehled představení MDB s proklikem přímo na mapu sálu.

Použití:
    python mdb_predprodej.py            # všechna budoucí představení, která už jsou v programu
    python mdb_predprodej.py 2026-12    # jen prosinec 2026
    python mdb_predprodej.py 2026-11 2026-12

Výstup: mdb_predprodej.html vedle skriptu (jinou cestu jde zadat proměnnou MDB_OUT). Adresy sálů (token je pro představení
stálý) se ukládají do hall_urls.json, takže další běhy se ptají jen na nová představení.
"""
import html
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

WEB = "https://www.mdb.cz"
SERVER = "https://server.mdb.cz"
UA = "Mozilla/5.0 (mdb-predprodej)"
OUT = Path(os.environ.get("MDB_OUT") or Path(__file__).with_name("mdb_predprodej.html"))
CACHE = Path(__file__).with_name("hall_urls.json")
PRICES = Path(__file__).with_name("prices.json")


def month_range(ym):
    y, m = map(int, ym.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, end


def get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_events(start, end=None):
    """Projde stránkované API webu a vrátí představení v rozsahu [start, end), bez end až do konce programu."""
    params = {"start[after]": start.isoformat()}
    if end:
        params["start[before]"] = end.isoformat()
    events = {}
    for page in range(1, 200):
        q = urllib.parse.urlencode({**params, "page": page})
        batch = get_json(f"{WEB}/api/event/events?{q}")
        new = [e for e in batch if e["id"] not in events]
        if not new:
            break
        for e in new:
            events[e["id"]] = e
    return [e for e in events.values()
            if start.isoformat() <= e["start"][:10] and (not end or e["start"][:10] < end.isoformat())]


def hall_info(colosseum_id, url=None):
    """Projde vstupem /hall (jako tlačítko na webu), od PrepareDetail získá adresu sálu
    (pokud ji ještě neznáme) a z legendy sálu přečte ceny. Vrací (url, ceny)."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    data = urllib.parse.urlencode({"mrsid": 1, "eventid": colosseum_id, "language": "cs", "currency": "CZK"}).encode()
    opener.open(f"{SERVER}/hall", data, timeout=15).read()
    if not url:
        path = opener.open(f"{SERVER}/mdb/standard/Hall/PrepareDetail", timeout=15).read().decode().strip()
        if not path.startswith("/mdb/"):
            return None, None
        url = SERVER + path
    page = opener.open(url, timeout=15).read().decode("utf-8", "replace")
    # Legenda cenových kategorií: <div class="isLegenda is_seat ckt_N ..."> … 980,00 Kč
    prices = {int(re.sub(r"\s", "", m.group(1)))
              for m in re.finditer(r'isLegenda is_seat ckt_\d+[^"]*".{0,600}?([\d\s]+),\d\d\s*K', page, re.S)}
    return url, sorted(prices)


def safe_hall_info(cid, url=None, attempts=4):
    for attempt in range(attempts):
        try:
            return hall_info(cid, url)
        except Exception as ex:  # server.mdb.cz občas přestane odpovídat, zkusíme to znovu
            if attempt == attempts - 1:
                print(f"  {cid}: {ex}", flush=True)
                return url, None
            time.sleep(3 * (attempt + 1))


WEEKDAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]
MONTHS = ["leden", "únor", "březen", "duben", "květen", "červen",
          "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]


GENRES = {"Drama": "Činohra", "Musical": "Muzikál", "Concert": "Koncert", "Opera": "Opera",
          "Ballet": "Balet", "Dance": "Tanec", "Show": "Show"}
DARK = "--bg:#111418; --card:#1a1e24; --fg:#e8eaed; --muted:#9aa3ad; --line:#2b313a; --accent:#ff5c8a; --ok:#4ade80; --low:#facc15; --zero:#f87171;"


def genre_label(e):
    g = e["production"].get("genre") or ""
    return GENRES.get(g, g)


def month_label(ym):
    y, m = map(int, ym.split("-"))
    return f"{MONTHS[m - 1].capitalize()} {y}"


def price_label(p):
    if not p:
        return '<span class="muted">–</span>'
    lo, hi = p[0], p[-1]
    return f"{lo} Kč" if lo == hi else f"{lo}–{hi}&nbsp;Kč"


def render(events, urls, prices, months):
    generated = datetime.now().strftime("%d. %m. %Y %H:%M")
    stages = sorted({(e.get("stage") or {}).get("title") or "" for e in events} - {""})
    genres = sorted({genre_label(e) for e in events} - {""}, key=lambda g: list(GENRES.values()).index(g) if g in GENRES.values() else 99)
    trs = []
    for e in events:
        dt = datetime.fromisoformat(e["start"])
        title = html.escape(e["production"]["title"])
        prod_url = WEB + e["production"]["url"]
        stage = html.escape((e.get("stage") or {}).get("title") or "")
        sale = e.get("saleStartAt")
        sale_txt = datetime.fromisoformat(sale).strftime("%d. %m. %H:%M") if sale else "–"
        cid = e.get("colosseumId")
        url = urls.get(str(cid)) if cid else None
        if not cid or e.get("canceled"):
            btn = '<span class="muted">bez prodeje</span>'
        elif not url:
            btn = '<span class="muted">sál nenačten</span>'
        else:
            btn = f'<button onclick="openHall({cid}, {html.escape(json.dumps(url))})">Sál</button>'
        cap = e.get("availableCapacity")  # počet volných míst, jak ho uvádí web mdb.cz
        if cap is None:
            free_html = '<span class="muted">–</span>'
        else:
            free_cls = "zero" if cap == 0 else ("low" if cap < 20 else "ok")
            free_html = f'<span class="free {free_cls}">{cap}</span>'
        trs.append(f"""<tr data-title="{title.lower()}" data-month="{dt:%Y-%m}" data-genre="{html.escape(genre_label(e))}" data-stage="{stage}" data-start="{e['start']}" data-free="{cap if cap is not None else -1}">
  <td class="date"><b>{dt.day}. {dt.month}.</b> {WEEKDAYS[dt.weekday()]}<br><span class="muted">{dt:%H:%M}</span></td>
  <td><a href="{prod_url}" target="_blank" rel="noopener">{title}</a><br><span class="muted">{" · ".join(x for x in (html.escape(genre_label(e)), stage) if x)}</span></td>
  <td class="num">{free_html}</td>
  <td class="num">{price_label(prices.get(str(cid)))}</td>
  <td class="num">{sale_txt}</td>
  <td>{btn}</td>
</tr>""")

    return f"""<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MDB předprodej</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --fg:#1b1f24; --muted:#6b7280; --line:#e5e7eb; --accent:#b4003c;
        --ok:#15803d; --low:#a16207; --zero:#b91c1c; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme=light]) {{ {DARK} }} }}
:root[data-theme=dark] {{ {DARK} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.4 system-ui,-apple-system,Segoe UI,sans-serif; }}
main {{ max-width:900px; margin:0 auto; padding:24px 16px; }}
h1 {{ margin:0 0 4px; font-size:22px }}
.muted {{ color:var(--muted); font-size:13px }}
.bar {{ margin:16px 0; display:flex; flex-direction:column; gap:10px; }}
.tabs {{ display:flex; flex-wrap:wrap; gap:6px; }}
.tabs button {{ background:var(--card); color:var(--fg); border:1px solid var(--line); font-weight:500; }}
.tabs.small button {{ padding:4px 10px; font-size:13px; }}
.top {{ display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }}
#theme {{ background:var(--card); color:var(--fg); border:1px solid var(--line); font-weight:500; padding:5px 10px; font-size:13px; white-space:nowrap; }}
.tabs button.active {{ background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }}
.empty {{ padding:24px 12px; text-align:center; color:var(--muted); }}
input[type=search] {{ padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--fg); width:100%; max-width:320px }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border-radius:10px; overflow:hidden; }}
th, td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top }}
th {{ font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted) }}
td.num, td.date {{ white-space:nowrap }}
a {{ color:inherit; text-decoration-color:var(--line) }} a:hover {{ color:var(--accent) }}
button {{ background:var(--accent); color:#fff; border:0; border-radius:8px; padding:7px 14px; font-weight:600; cursor:pointer }}
.note {{ font-size:13px; color:var(--muted); margin-top:16px }}
.free {{ font-weight:700; font-size:17px }} .free.ok {{ color:var(--ok) }} .free.low {{ color:var(--low) }} .free.zero {{ color:var(--zero) }}
.filters {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; }}
@media (max-width:560px) {{ th:nth-child(5), td:nth-child(5) {{ display:none }} th, td {{ padding:10px 8px }} }}
</style></head><body><main>
<div class="top"><h1>MDB – sály představení</h1><button id="theme" onclick="cycleTheme()"></button></div>
<div class="muted">Seznam a volná místa k {generated} · neoficiální rozcestník, nákup probíhá přímo na <a href="{WEB}" target="_blank" rel="noopener">mdb.cz</a></div>
<div class="bar">
  <div class="tabs" id="tabs">{"".join(f'<button data-month="{m}">{month_label(m)}</button>' for m in months)}<button data-month="all">Vše</button></div>
  <div class="tabs small" id="genres"><button data-genre="" class="active">Všechny žánry</button>{"".join(f'<button data-genre="{html.escape(g)}">{html.escape(g)}</button>' for g in genres)}</div>
  <div class="tabs small" id="stages"><button data-stage="" class="active">Všechny scény</button>{"".join(f'<button data-stage="{html.escape(st)}">{html.escape(st)}</button>' for st in stages)}</div>
  <div class="filters">
    <input type="search" id="q" placeholder="Hledat představení…" oninput="filter()">
    <label><input type="checkbox" id="onlyFree" onchange="filter()"> jen s volnými místy</label>
  </div>
</div>
<table><thead><tr><th>Datum</th><th>Představení</th><th>Volno</th><th>Cena</th><th>Předprodej od</th><th></th></tr></thead>
<tbody>
{chr(10).join(trs)}
</tbody></table>
<div class="empty" id="empty" hidden>Žádná představení.</div>
<p class="note">„Sál“ otevře novou záložku, v ní nejdřív otevře představení na server.mdb.cz a po 2,5 s přejde na aktuální mapu sálu.
Pokud zůstane na hlášce „Na tuto akci není možné provádět rezervace“, klikni na „Sál“ znovu.
Před začátkem předprodeje jsou místa vidět, ale nejdou vybrat.
„Volno“ je počet volných míst, jak ho uvádí web mdb.cz, aktualizovaný zhruba každou hodinu; přesný stav ukáže mapa sálu.</p>
</main>
<script>
function openHall(id, url) {{
  const name = 'mdb_' + id + '_' + Date.now();
  const w = window.open('about:blank', name);
  const f = document.createElement('form');
  f.method = 'POST'; f.action = '{SERVER}/hall'; f.target = name;
  for (const [k, v] of Object.entries({{mrsid: 1, eventid: id, language: 'cs', currency: 'CZK'}})) {{
    const i = document.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.appendChild(i);
  }}
  document.body.appendChild(f); f.submit(); f.remove();
  setTimeout(() => {{ if (w) w.location.href = url; }}, 2500);
}}
const fold = t => t.normalize('NFD').replace(/\\p{{Diacritic}}/gu, '').toLowerCase();  // bez diakritiky
const tabs = [...document.querySelectorAll('#tabs button')];
let month = '';
function setMonth(m) {{
  if (!tabs.some(b => b.dataset.month === m)) m = tabs[tabs.length - 2].dataset.month;  // výchozí: nejnovější měsíc
  month = m;
  for (const b of tabs) b.classList.toggle('active', b.dataset.month === m);
  history.replaceState(null, '', '#' + m);
  filter();
}}
function filter() {{
  const q = fold(document.getElementById('q').value.trim());
  const onlyFree = document.getElementById('onlyFree').checked;
  const genre = document.querySelector('#genres button.active').dataset.genre;
  const stage = document.querySelector('#stages button.active').dataset.stage;
  const now = new Date();
  let shown = 0;
  for (const tr of document.querySelectorAll('tbody tr')) {{
    const show = fold(tr.dataset.title).includes(q)
      && (month === 'all' || tr.dataset.month === month)
      && (!onlyFree || +tr.dataset.free > 0)
      && (!genre || tr.dataset.genre === genre)
      && (!stage || tr.dataset.stage === stage)
      && new Date(tr.dataset.start) > now;  // proběhlá představení skrýt
    tr.style.display = show ? '' : 'none';
    shown += show;
  }}
  document.getElementById('empty').hidden = shown > 0;
}}
for (const b of tabs) b.onclick = () => setMonth(b.dataset.month);
for (const id of ['genres', 'stages']) {{
  const group = document.querySelectorAll('#' + id + ' button');
  for (const b of group) b.onclick = () => {{
    for (const o of group) o.classList.toggle('active', o === b);
    filter();
  }};
}}
const THEMES = {{auto: 'Motiv: auto', light: 'Motiv: světlý', dark: 'Motiv: tmavý'}};
function applyTheme(t) {{
  if (t === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.dataset.theme = t;
  document.getElementById('theme').textContent = THEMES[t];
  try {{ localStorage.setItem('theme', t); }} catch (e) {{}}
}}
function cycleTheme() {{
  const order = Object.keys(THEMES);
  const cur = document.documentElement.dataset.theme || 'auto';
  applyTheme(order[(order.indexOf(cur) + 1) % order.length]);
}}
let savedTheme = 'auto';
try {{ savedTheme = localStorage.getItem('theme') || 'auto'; }} catch (e) {{}}
applyTheme(THEMES[savedTheme] ? savedTheme : 'auto');
window.onhashchange = () => setMonth(location.hash.slice(1));
setMonth(location.hash.slice(1));
</script></body></html>"""


def main():
    events = []
    if sys.argv[1:]:
        for ym in sys.argv[1:]:
            events += fetch_events(*month_range(ym))
    else:
        events = fetch_events(date.today())
    events.sort(key=lambda e: e["start"])
    months = sorted({e["start"][:7] for e in events})

    urls = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    prices = json.loads(PRICES.read_text(encoding="utf-8")) if PRICES.exists() else {}
    ids = [str(e["colosseumId"]) for e in events if e.get("colosseumId") and not e.get("canceled")]
    missing = [cid for cid in ids if cid not in urls or cid not in prices]
    if os.environ.get("MDB_CACHE_ONLY"):  # rychlé nasazení jen z uložených dat, bez dotazů na server.mdb.cz
        missing = []
    print(f"Představení: {len(events)}, dohledávám sály/ceny: {len(missing)}", flush=True)
    # Po jednom a s pauzou – při souběžných dotazech server.mdb.cz přestane odpovídat.
    for cid in missing:
        url, p = safe_hall_info(cid, urls.get(cid))
        if url:
            urls[cid] = url
            CACHE.write_text(json.dumps(urls, indent=1), encoding="utf-8")
        if p is not None:
            prices[cid] = p
            PRICES.write_text(json.dumps(prices, indent=1), encoding="utf-8")
        time.sleep(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(events, urls, prices, months), encoding="utf-8")
    print(f"Hotovo: {OUT}")


if __name__ == "__main__":
    main()

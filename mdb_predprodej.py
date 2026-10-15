"""Vygeneruje HTML přehled představení MDB s proklikem přímo na mapu sálu.

Použití:
    python mdb_predprodej.py            # aktuální a dva další měsíce
    python mdb_predprodej.py 2026-12    # jen prosinec 2026
    python mdb_predprodej.py 2026-11 2026-12

Výstup: mdb_predprodej.html vedle skriptu (jinou cestu jde zadat proměnnou MDB_OUT). Adresy sálů (token je pro představení
stálý) se ukládají do hall_urls.json, takže další běhy se ptají jen na nová představení.
"""
import html
import http.cookiejar
import json
import os
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


def month_range(ym):
    y, m = map(int, ym.split("-"))
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, end


def get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_events(start, end):
    """Projde stránkované API webu a vrátí představení v rozsahu [start, end)."""
    events = {}
    for page in range(1, 50):
        q = urllib.parse.urlencode({"start[after]": start.isoformat(), "start[before]": end.isoformat(), "page": page})
        batch = get_json(f"{WEB}/api/event/events?{q}")
        new = [e for e in batch if e["id"] not in events]
        if not new:
            break
        for e in new:
            events[e["id"]] = e
    return [e for e in events.values() if start.isoformat() <= e["start"][:10] < end.isoformat()]


def hall_url(colosseum_id):
    """Projde vstupem /hall (jako tlačítko na webu) a od PrepareDetail získá adresu sálu."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", UA)]
    data = urllib.parse.urlencode({"mrsid": 1, "eventid": colosseum_id, "language": "cs", "currency": "CZK"}).encode()
    opener.open(f"{SERVER}/hall", data, timeout=15).read()
    path = opener.open(f"{SERVER}/mdb/standard/Hall/PrepareDetail", timeout=15).read().decode().strip()
    return SERVER + path if path.startswith("/mdb/") else None


def safe_hall_url(cid, attempts=4):
    for attempt in range(attempts):
        try:
            return hall_url(cid)
        except Exception as ex:  # server.mdb.cz občas přestane odpovídat, zkusíme to znovu
            if attempt == attempts - 1:
                print(f"  {cid}: {ex}", flush=True)
                return None
            time.sleep(3 * (attempt + 1))


WEEKDAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]


def render(events, urls, months):
    generated = datetime.now().strftime("%d. %m. %Y %H:%M")
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
        trs.append(f"""<tr data-title="{title.lower()}">
  <td class="date"><b>{dt.day}. {dt.month}.</b> {WEEKDAYS[dt.weekday()]}<br><span class="muted">{dt:%H:%M}</span></td>
  <td><a href="{prod_url}" target="_blank" rel="noopener">{title}</a><br><span class="muted">{stage} · ID {cid or '–'}</span></td>
  <td class="num">{sale_txt}</td>
  <td>{btn}</td>
</tr>""")

    return f"""<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MDB předprodej</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --fg:#1b1f24; --muted:#6b7280; --line:#e5e7eb; --accent:#b4003c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111418; --card:#1a1e24; --fg:#e8eaed; --muted:#9aa3ad;
        --line:#2b313a; --accent:#ff5c8a; }} }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:15px/1.4 system-ui,-apple-system,Segoe UI,sans-serif; }}
main {{ max-width:900px; margin:0 auto; padding:24px 16px; }}
h1 {{ margin:0 0 4px; font-size:22px }}
.muted {{ color:var(--muted); font-size:13px }}
.bar {{ margin:16px 0; }}
input[type=search] {{ padding:8px 10px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--fg); width:100%; max-width:320px }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border-radius:10px; overflow:hidden; }}
th, td {{ padding:10px 12px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top }}
th {{ font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted) }}
td.num, td.date {{ white-space:nowrap }}
a {{ color:inherit; text-decoration-color:var(--line) }} a:hover {{ color:var(--accent) }}
button {{ background:var(--accent); color:#fff; border:0; border-radius:8px; padding:7px 14px; font-weight:600; cursor:pointer }}
.note {{ font-size:13px; color:var(--muted); margin-top:16px }}
@media (max-width:560px) {{ th:nth-child(3), td:nth-child(3) {{ display:none }} }}
</style></head><body><main>
<h1>MDB – sály představení</h1>
<div class="muted">{', '.join(months)} · seznam k {generated} · neoficiální rozcestník, nákup probíhá přímo na <a href="{WEB}" target="_blank" rel="noopener">mdb.cz</a></div>
<div class="bar"><input type="search" id="q" placeholder="Hledat představení…" oninput="filter()"></div>
<table><thead><tr><th>Datum</th><th>Představení</th><th>Předprodej od</th><th></th></tr></thead>
<tbody>
{chr(10).join(trs)}
</tbody></table>
<p class="note">„Sál“ otevře novou záložku, v ní nejdřív otevře představení na server.mdb.cz a po 2,5 s přejde na aktuální mapu sálu.
Pokud zůstane na hlášce „Na tuto akci není možné provádět rezervace“, klikni na „Sál“ znovu.
Před začátkem předprodeje jsou místa vidět, ale nejdou vybrat.</p>
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
function filter() {{
  const q = document.getElementById('q').value.trim().toLowerCase();
  for (const tr of document.querySelectorAll('tbody tr')) tr.style.display = tr.dataset.title.includes(q) ? '' : 'none';
}}
</script></body></html>"""


def main():
    months = sys.argv[1:]
    if not months:
        t = date.today()
        months = [f"{t.year + (t.month + i - 1) // 12}-{(t.month + i - 1) % 12 + 1:02d}" for i in range(3)]
    events = []
    for ym in months:
        events += fetch_events(*month_range(ym))
    events.sort(key=lambda e: e["start"])

    urls = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    missing = [str(e["colosseumId"]) for e in events if e.get("colosseumId") and str(e["colosseumId"]) not in urls]
    if os.environ.get("MDB_CACHE_ONLY"):  # rychlé nasazení jen z uložených adres, bez dotazů na server.mdb.cz
        missing = []
    print(f"Představení: {len(events)}, dohledávám sály: {len(missing)}", flush=True)
    # Po jednom a s pauzou – při souběžných dotazech server.mdb.cz přestane odpovídat.
    for cid in missing:
        url = safe_hall_url(cid)
        if url:
            urls[cid] = url
            CACHE.write_text(json.dumps(urls, indent=1), encoding="utf-8")
        time.sleep(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(events, urls, months), encoding="utf-8")
    print(f"Hotovo: {OUT}")


if __name__ == "__main__":
    main()

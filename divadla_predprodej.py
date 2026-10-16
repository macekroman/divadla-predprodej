"""Vygeneruje HTML přehled představení brněnských divadel s proklikem přímo na mapu sálu.

Divadla: Městské divadlo Brno (API webu) a Národní divadlo Brno (program z HTML webu).
Obě prodávají přes systém Colosseum, proto stejný postup pro adresu sálu i volná místa.

Použití:
    python divadla_predprodej.py            # všechna budoucí představení, která už jsou v programu
    python divadla_predprodej.py 2026-12    # jen prosinec 2026
    python divadla_predprodej.py 2026-11 2026-12

Výstup: divadla_predprodej.html vedle skriptu (jinou cestu jde zadat proměnnou OUT).
S proměnnou CACHE_ONLY=1 se nic nenačítá z prodejních systémů, použijí se jen uložená data.

    python divadla_predprodej.py --ndb-program SOUBOR   # jen stáhne program NdB do souboru
S proměnnou NDB_PROGRAM=SOUBOR se program NdB převezme ze souboru (když neexistuje, bere se jako
nedostupný). Web NdB totiž část serverů GitHub Actions blokuje, takže ho workflow stahuje
na několika serverech souběžně a hlavní běh použije první úspěšný výsledek.
Adresy sálů (token je pro představení stálý) jsou v hall_urls.json, volná místa podle cen v seats.json.
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
from datetime import date, datetime, timedelta
from pathlib import Path

UA = "Mozilla/5.0 (divadla-predprodej)"
OUT = Path(os.environ.get("OUT") or Path(__file__).with_name("divadla_predprodej.html"))
CACHE = Path(__file__).with_name("hall_urls.json")
SEATS = Path(__file__).with_name("seats.json")
PROGRAMS = Path(__file__).with_name("programs.json")  # poslední úspěšně načtený program každého divadla

# Pole "form" odpovídají formuláři, který posílá tlačítko „Koupit vstupenky“ na webu divadla.
THEATRES = {
    "mdb": {"name": "Městské divadlo Brno", "short": "MDB", "web": "https://www.mdb.cz",
            "server": "https://server.mdb.cz", "prefix": "mdb",
            "form": {"mrsid": 1, "language": "cs", "currency": "CZK"}},
    "ndb": {"name": "Národní divadlo Brno", "short": "NdB", "web": "https://www.ndbrno.cz",
            "server": "https://online.colosseum.eu", "prefix": "ndbrno",
            "form": {"mrsid": 83, "language": "cs-CZ"}},
}
DEFAULT_THEATRE = "mdb"  # předvybrané divadlo ve filtru
NDB_REFRESH = timedelta(hours=6)  # NdB nemá počet volných míst v API, mapu sálu obnovujeme podle stáří
NDB_REFRESH_PER_RUN = 60


def key(e):
    """Klíč do hall_urls.json / seats.json; u MDB holé ID kvůli zpětné kompatibilitě."""
    return e["cid"] if e["theatre"] == "mdb" else f'{e["theatre"]}:{e["cid"]}'


def opener():
    o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    o.addheaders = [("User-Agent", UA)]
    return o


def get_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


# --- Městské divadlo Brno: JSON API webu ---

MDB_GENRES = {"Drama": "Činohra", "Musical": "Muzikál", "Concert": "Koncert", "Opera": "Opera",
              "Ballet": "Balet", "Dance": "Tanec", "Show": "Show"}


def fetch_mdb():
    web = THEATRES["mdb"]["web"]
    raw = {}
    for page in range(1, 200):
        q = urllib.parse.urlencode({"start[after]": date.today().isoformat(), "page": page})
        new = [e for e in get_json(f"{web}/api/event/events?{q}") if e["id"] not in raw]
        if not new:
            break
        raw.update((e["id"], e) for e in new)
    events = []
    for e in raw.values():
        g = e["production"].get("genre") or ""
        cid = e.get("colosseumId")
        events.append({
            "theatre": "mdb", "cid": str(cid) if cid else None, "start": e["start"],
            "title": e["production"]["title"], "url": web + e["production"]["url"],
            "stage": (e.get("stage") or {}).get("title") or "", "genre": MDB_GENRES.get(g, g),
            "sale": e.get("saleStartAt"), "cap": e.get("availableCapacity"),
            "note": "zrušeno" if e.get("canceled") else (None if cid else "bez prodeje"),
        })
    return events


# --- Národní divadlo Brno: program z HTML webu, po měsících ---

def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def fetch_ndb():
    web = THEATRES["ndb"]["web"]
    o = opener()
    first = o.open(f"{web}/program/", timeout=30).read().decode("utf-8", "replace")
    # Přepínač měsíců: <a href="" data-month="11" data-year="2026">
    months = re.findall(r'data-month="(\d+)" data-year="(\d+)"', first) or [(str(date.today().month), str(date.today().year))]
    events = {}
    for m, y in months:
        page = o.open(f"{web}/program/?month={m}&years={y}", timeout=30).read().decode("utf-8", "replace")
        for block in re.split(r'<div class="cl-k col', page)[1:]:
            e = parse_ndb_block(block)
            if e:
                events[(e["cid"], e["start"]) if e["cid"] else (e["title"], e["start"])] = e
        time.sleep(1)
    return list(events.values())


def parse_ndb_block(b):
    when = re.search(r"<li>(\d\d)/(\d\d)/(\d{4})</li>\s*<li>(\d\d):(\d\d)", b)
    title = re.search(r'<h3 class="etzar">(.*?)</h3>', b, re.S)
    if not when or not title:
        return None  # bez času: zájezdy apod.
    cid = re.search(r'value="83" name="mrsid">\s*<input type="hidden" name="eventid" value="(\d+)"', b)
    sold_out = "view-oversell" in b
    if not cid and not sold_out:
        return None  # zadaná představení pro školy a firmy, pronájmy, akce bez vstupenek
    d, mo, y, hh, mm = when.groups()
    url = re.search(r'<a href="([^"]+)" class="screen"', b)
    stage = re.search(r'/budova/[^"]*"><strong>(.*?)</strong>', b)
    genre = re.search(r'href="[^"]*/(?:opery|cinohry|balety)/">([^<]+)</a>', b)
    stage_txt = text(stage.group(1)) if stage else ""
    return {
        "theatre": "ndb", "cid": cid.group(1) if cid else None, "start": f"{y}-{mo}-{d}T{hh}:{mm}:00",
        "title": text(title.group(1)), "url": url.group(1) if url else THEATRES["ndb"]["web"],
        "stage": stage_txt[:1].upper() + stage_txt[1:], "genre": text(genre.group(1)) if genre else "",
        "sale": None, "cap": 0 if sold_out else None, "note": "vyprodáno" if sold_out else None,
    }


# --- Colosseum: adresa sálu a mapa míst ---

def hall_info(theatre, cid, url=None):
    """Projde vstupem /hall (jako tlačítko na webu), od PrepareDetail získá adresu sálu (pokud ji
    ještě neznáme) a z mapy sálu spočítá místa v cenových kategoriích.
    Vrací (url, {"cats": {cena: [míst celkem, volných]}, "on_sale": bool})."""
    t = THEATRES[theatre]
    server, base = t["server"], f'{t["server"]}/{t["prefix"]}/standard/Hall'
    o = opener()
    o.open(f"{server}/hall", urllib.parse.urlencode({**t["form"], "eventid": cid}).encode(), timeout=15).read()
    if not url:
        path = o.open(f"{base}/PrepareDetail", timeout=15).read().decode().strip()
        if not path.startswith(f'/{t["prefix"]}/'):
            return None, None
        url = server + path
    # Stránku sálu je potřeba načíst i kvůli ShowSeats – bez ní vrátí prázdnou mapu.
    page = o.open(url, timeout=15).read().decode("utf-8", "replace")
    # Legenda: <input type="hidden" id='PriceCategory_Price_N' value="980" />
    ckt_price = dict(re.findall(r"PriceCategory_Price_(\d+)' value=\"(\d+)\"", page))
    section = re.search(r'id="HallSectionId" name="sectionid" value="([-0-9]+)"', page)
    currency = re.search(r'id="HallCurrencyId" name="currencyid" value="(\d+)"', page)
    q = urllib.parse.urlencode({"eventid": cid, "sectionid": section.group(1) if section else "-2147483648",
                                "currencyid": currency.group(1) if currency else 1,
                                "x": 0, "y": 0, "containerWidth": 1200, "ignoreMe": 1})
    seats = o.open(f"{base}/ShowSeats?{q}", timeout=15).read().decode("utf-8", "replace")
    # Místo: class='position-absolute is_seat ckt_N cktIdx_M free|restricted|occupied'
    cats = {}
    for ckt, state in re.findall(r"class='[^']*is_seat ckt_(\d+)([^']*)'", seats):
        price = ckt_price.get(ckt)
        if not price:
            continue
        total_free = cats.setdefault(price, [0, 0])
        total_free[0] += 1
        total_free[1] += "occupied" not in state
    return url, {"cats": cats, "on_sale": "Akce není v prodeji" not in page}


def safe_hall_info(theatre, cid, url=None, attempts=4):
    for attempt in range(attempts):
        try:
            return hall_info(theatre, cid, url)
        except Exception as ex:  # server občas přestane odpovídat, zkusíme to znovu
            if attempt == attempts - 1:
                print(f"  {theatre} {cid}: {ex}", flush=True)
                return url, None
            time.sleep(3 * (attempt + 1))


# --- HTML ---

WEEKDAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]
MONTHS = ["leden", "únor", "březen", "duben", "květen", "červen",
          "červenec", "srpen", "září", "říjen", "listopad", "prosinec"]
GENRE_ORDER = ["Činohra", "Muzikál", "Opera", "Balet", "Koncert"]
DARK = "--bg:#111418; --card:#1a1e24; --fg:#e8eaed; --muted:#9aa3ad; --line:#2b313a; --accent:#ff5c8a; --ok:#86efac; --ok-bg:#14532d; --low:#fde047; --low-bg:#713f12; --zero:#fca5a5; --zero-bg:#7f1d1d;"


def month_label(ym):
    y, m = map(int, ym.split("-"))
    return f"{MONTHS[m - 1].capitalize()} {y}"


def month_button(ym):
    """Tlačítko měsíce: plný popisek, na mobilu zkrácený („Led 27“)."""
    y, m = map(int, ym.split("-"))
    short = f"{MONTHS[m - 1][:3].capitalize()} {y % 100}"
    return f'<button data-month="{ym}"><span class="long">{month_label(ym)}</span><span class="short">{short}</span></button>'


def price_range(prices):
    lo, hi = min(prices), max(prices)
    return f"{lo}&nbsp;Kč" if lo == hi else f"{lo}–{hi}&nbsp;Kč"


def price_label(info):
    """Rozsah cen, za které jsou ještě volná místa, s rozbalitelným rozpadem po kategoriích."""
    cats = (info or {}).get("cats")
    if not cats:
        return '<span class="muted">–</span>'
    free = [int(p) for p, (_, f) in cats.items() if f]
    summary = price_range(free) if free else '<span class="muted">nic volného</span>'
    rows = "".join(f"<div>{p}&nbsp;Kč: <b>{f}</b> / {t}</div>"
                   for p, (t, f) in sorted(cats.items(), key=lambda c: -int(c[0])))
    return f'<details><summary>{summary}</summary><div class="cats">{rows}<div class="muted">volná / celkem</div></div></details>'


def free_count(e, info):
    """MDB: číslo z API webu. NdB: součet volných míst z mapy sálu."""
    if e["theatre"] == "mdb" or e["cap"] is not None:
        return e["cap"]
    cats = (info or {}).get("cats")
    return sum(f for _, f in cats.values()) if cats else None


def select(group, all_label, options, default=""):
    """Rozbalovací filtr; options jsou dvojice (hodnota, popisek), nebo (skupina, [dvojice]) pro <optgroup>."""
    def opts(items):
        return "".join(f'<option value="{html.escape(v)}"{" selected" if v == default else ""}>{html.escape(label)}</option>'
                       for v, label in items)
    body = "".join(f'<optgroup label="{html.escape(o[0])}" data-theatre="{html.escape(o[2])}">{opts(o[1])}</optgroup>'
                   if isinstance(o[1], list) else opts([o]) for o in options)
    return f'<select data-filter="{group}" onchange="filter()"><option value="">{all_label}</option>{body}</select>'


def render(events, urls, seats, months, stale=None):
    """stale: {divadlo: kdy byl program naposledy načten} pro divadla, jejichž web teď nebyl dostupný."""
    generated = datetime.now().strftime("%d. %m. %Y %H:%M")
    stale_note = "".join(f' · program {THEATRES[k]["short"]} z {datetime.fromisoformat(ts):%d. %m. %H:%M} (web divadla teď nedostupný)'
                         for k, ts in (stale or {}).items())
    theatres = [(k, t["name"]) for k, t in THEATRES.items() if any(e["theatre"] == k for e in events)]
    # Scény seskupené podle divadla; hodnota nese i divadlo („mdb|Hudební scéna“), aby se nepletly.
    stages = [(name, [(f"{k}|{st}", st) for st in sorted({e["stage"] for e in events if e["theatre"] == k} - {""})], k)
              for k, name in theatres]
    genres = sorted({e["genre"] for e in events} - {""},
                    key=lambda g: (GENRE_ORDER.index(g) if g in GENRE_ORDER else 99, g))
    trs = []
    for e in events:
        dt = datetime.fromisoformat(e["start"])
        t = THEATRES[e["theatre"]]
        title = html.escape(e["title"])
        stage = html.escape(e["stage"])
        sale_txt = datetime.fromisoformat(e["sale"]).strftime("%d. %m. %H:%M") if e["sale"] else "–"
        info = seats.get(key(e)) if e["cid"] else None
        url = urls.get(key(e)) if e["cid"] else None
        if e["note"]:
            btn = f'<span class="muted">{e["note"]}</span>'
        elif not url:
            btn = '<span class="muted">odkaz zatím nenačten</span>'
        else:
            # Je-li představení v prodeji, dovede na sál oficiální postup sám (viz openHall).
            on_sale = (info or {}).get("on_sale")
            args = ", ".join(json.dumps(a) for a in (e["theatre"], e["cid"], url, on_sale, e["sale"]))
            btn = f'<button onclick="openHall({html.escape(args)})">Vstupenky</button>'
        cap = free_count(e, info)
        if cap is None:
            free_html = '<span class="muted">–</span>'
        else:
            free_cls = "zero" if cap == 0 else ("low" if cap < 20 else "ok")
            free_html = f'<span class="free {free_cls}">{cap}</span>'
        meta = " · ".join(x for x in (t["short"], html.escape(e["genre"]), stage) if x)
        trs.append(f"""<tr data-title="{title.lower()}" data-month="{dt:%Y-%m}" data-theatre="{e['theatre']}" data-genre="{html.escape(e['genre'])}" data-stage="{e['theatre']}|{stage}" data-start="{e['start']}" data-free="{cap if cap is not None else -1}">
  <td class="date"><b>{dt.day}. {dt.month}.</b> {WEEKDAYS[dt.weekday()]}<br><span class="muted">{dt:%H:%M}</span></td>
  <td><a class="detail" href="{html.escape(e['url'])}" target="_blank" rel="noopener" title="Popis představení na webu divadla">{title}<span class="ext" aria-hidden="true">↗</span></a><br><span class="muted">{meta}</span></td>
  <td class="num">{free_html}</td>
  <td class="num">{price_label(info)}</td>
  <td class="num">{sale_txt}</td>
  <td>{btn}</td>
</tr>""")

    config = {k: {"server": t["server"], "form": t["form"]} for k, t in THEATRES.items()}
    links = " a ".join(f'<a href="{t["web"]}" target="_blank" rel="noopener">{t["short"]}</a>' for t in THEATRES.values())
    return f"""<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brněnská divadla – sály</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --fg:#1b1f24; --muted:#6b7280; --line:#e5e7eb; --accent:#b4003c;
        --ok:#166534; --ok-bg:#dcfce7; --low:#854d0e; --low-bg:#fef08a; --zero:#991b1b; --zero-bg:#fecaca; }}
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
.selects {{ display:flex; flex-wrap:wrap; gap:8px; }}
select {{ padding:7px 10px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--fg); font:inherit; font-size:14px; max-width:100%; }}
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
a.detail {{ font-weight:600; text-decoration-color:var(--muted); text-underline-offset:3px }}
a.detail .ext {{ font-size:12px; margin-left:3px; color:var(--muted); text-decoration:none; display:inline-block }}
button {{ background:var(--accent); color:#fff; border:0; border-radius:8px; padding:7px 14px; font-weight:600; cursor:pointer }}
.note {{ font-size:13px; color:var(--muted); margin-top:16px }}
.free {{ display:inline-block; min-width:2.6em; text-align:center; font-weight:700; padding:2px 8px; border-radius:6px }}
.free.ok {{ color:var(--ok); background:var(--ok-bg) }} .free.low {{ color:var(--low); background:var(--low-bg) }}
.free.zero {{ color:var(--zero); background:var(--zero-bg) }}
details summary {{ cursor:pointer; white-space:nowrap }}
details .cats {{ margin-top:4px; font-size:13px; line-height:1.5 }}
.filters {{ display:flex; flex-wrap:wrap; gap:12px; align-items:center; }}
.tabs .short {{ display:none }}
/* Mobil: měsíce v mřížce, filtry pod sebou a z tabulky karty – bez vodorovného posouvání. */
@media (max-width:560px) {{
  main {{ padding:16px 12px; }}
  h1 {{ font-size:18px; }}
  #months {{ display:grid; grid-template-columns:repeat(4, 1fr); }}
  #months button {{ padding:7px 4px; }}
  .tabs .long {{ display:none }} .tabs .short {{ display:inline }}
  .selects {{ display:grid; grid-template-columns:1fr 1fr; }}
  .selects select:first-child {{ grid-column:1 / -1; }}
  .selects select {{ width:100%; min-width:0; }}
  .filters {{ display:grid; gap:8px; }}
  input[type=search] {{ max-width:none; }}
  thead {{ display:none; }}
  table, tbody {{ display:block; }}
  tbody tr {{ display:grid; grid-template-columns:4.7em minmax(0, 1fr) auto; grid-template-areas:"date title title" "free price btn";
              gap:8px 12px; align-items:center; padding:12px; border-bottom:1px solid var(--line); }}
  tbody td {{ display:block; padding:0; border:0; min-width:0; }}
  tbody td:nth-child(1) {{ grid-area:date; align-self:start; }}
  tbody td:nth-child(2) {{ grid-area:title; }}
  tbody td:nth-child(3) {{ grid-area:free; }}
  tbody td:nth-child(4) {{ grid-area:price; }}
  tbody td:nth-child(5) {{ display:none; }}
  tbody td:nth-child(6) {{ grid-area:btn; }}
}}
</style></head><body><main>
<div class="top"><h1>Brněnská divadla – sály a volná místa</h1><button id="theme" onclick="cycleTheme()"></button></div>
<div class="muted">Seznam a volná místa k {generated}{stale_note} · neoficiální rozcestník, nákup probíhá přímo na webu {links}</div>
<div class="bar">
  <div class="tabs" id="months">{"".join(month_button(m) for m in months)}<button data-month="all">Vše</button></div>
  <div class="selects">
    {select("theatre", "Všechna divadla", theatres, default=DEFAULT_THEATRE)}
    {select("genre", "Všechny žánry", [(g, g) for g in genres])}
    {select("stage", "Všechny scény", stages)}
  </div>
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
<p class="note">„Vstupenky“ otevře novou záložku s aktuální mapou sálu v prodejním systému divadla (nejdřív v ní na okamžik otevře představení, pak hned přejde na sál).
Pokud zůstane na hlášce „Na tuto akci není možné provádět rezervace“, klikni na „Vstupenky“ znovu.
Před začátkem předprodeje jsou místa vidět, ale nejdou vybrat.
„Volno“ u MDB je počet volných míst, jak ho uvádí web mdb.cz (obnovuje se každou hodinu), u NdB součet volných míst z mapy sálu (obnovuje se zhruba každých 6 hodin).
Ceny jsou základní ceny cenových kategorií, ve kterých jsou ještě volná místa; po rozkliknutí rozpad po kategoriích.</p>
</main>
<script>
const THEATRES = {json.dumps(config)};
function openHall(theatre, id, url, onSale, saleStart) {{
  const t = THEATRES[theatre];
  const name = 'hall_' + id + '_' + Date.now();
  const w = window.open('about:blank', name);
  const f = document.createElement('form');
  f.method = 'POST'; f.action = t.server + '/hall'; f.target = name;
  for (const [k, v] of Object.entries({{...t.form, eventid: id}})) {{
    const i = document.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.appendChild(i);
  }}
  document.body.appendChild(f); f.submit(); f.remove();
  // V prodeji: čekací stránka divadla na sál přesměruje sama, další přesměrování by ho jen načetlo znovu.
  if (onSale || (saleStart && new Date(saleStart) <= new Date())) return;
  if (!w) return;
  // Dokud je záložka about:blank, vidíme do ní. Jakmile se v ní načte prodejní systém (po všech
  // přesměrováních, takže cookie session už je nastavená), přístup vyhodí výjimku – pak přepneme na sál.
  const started = Date.now();
  const timer = setInterval(() => {{
    let ready;
    try {{ ready = w.location.href !== 'about:blank'; }} catch (e) {{ ready = true; }}
    if (ready || Date.now() - started > 5000) {{
      clearInterval(timer);
      if (!w.closed) w.location.href = url;
    }}
  }}, 50);
}}
const fold = t => t.normalize('NFD').replace(/\\p{{Diacritic}}/gu, '').toLowerCase();  // bez diakritiky
const monthTabs = [...document.querySelectorAll('#months button')];
let month = '';
function setMonth(m) {{
  if (!monthTabs.some(b => b.dataset.month === m)) m = monthTabs[0].dataset.month;  // výchozí: aktuální měsíc
  month = m;
  for (const b of monthTabs) b.classList.toggle('active', b.dataset.month === m);
  history.replaceState(null, '', '#' + m);
  filter();
}}
function filter() {{
  const q = fold(document.getElementById('q').value.trim());
  const onlyFree = document.getElementById('onlyFree').checked;
  const sel = {{}};
  for (const g of document.querySelectorAll('[data-filter]')) sel[g.dataset.filter] = g.value;
  const now = new Date();
  let shown = 0;
  for (const tr of document.querySelectorAll('tbody tr')) {{
    const show = fold(tr.dataset.title).includes(q)
      && (month === 'all' || tr.dataset.month === month)
      && (!onlyFree || +tr.dataset.free > 0)
      && Object.entries(sel).every(([k, v]) => !v || tr.dataset[k] === v)
      && new Date(tr.dataset.start) > now;  // proběhlá představení skrýt
    tr.style.display = show ? '' : 'none';
    shown += show;
  }}
  document.getElementById('empty').hidden = shown > 0;
}}
for (const b of monthTabs) b.onclick = () => setMonth(b.dataset.month);
// Po výběru divadla nabízet jen jeho scény.
const theatreSelect = document.querySelector('[data-filter=theatre]');
theatreSelect.addEventListener('change', () => {{
  const theatre = theatreSelect.value, stage = document.querySelector('[data-filter=stage]');
  for (const g of stage.querySelectorAll('optgroup')) g.hidden = g.disabled = !!theatre && g.dataset.theatre !== theatre;
  if (stage.value && theatre && !stage.value.startsWith(theatre + '|')) {{ stage.value = ''; filter(); }}
}});
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
theatreSelect.dispatchEvent(new Event('change'));  // skrýt scény ostatních divadel i pro výchozí volbu
window.onhashchange = () => setMonth(location.hash.slice(1));
setMonth(location.hash.slice(1));
</script></body></html>"""


# --- hlavní běh ---

def todo_list(events, urls, seats):
    """Představení, u kterých je potřeba načíst sál: nová, u MDB se změnou počtu volných míst podle API,
    u NdB s mapou starší než NDB_REFRESH (nejstarší napřed, nejvýš NDB_REFRESH_PER_RUN)."""
    now = datetime.now()
    todo, stale = [], []
    for e in events:
        if not e["cid"] or e["note"]:
            continue
        k = key(e)
        info = seats.get(k)
        if k not in urls or not info:
            todo.append(e)
        elif e["theatre"] == "mdb":
            if info.get("cap") != e["cap"]:
                todo.append(e)
        elif now - datetime.fromisoformat(info.get("ts", "2000-01-01T00:00:00")) > NDB_REFRESH:
            stale.append(e)
    stale.sort(key=lambda e: seats[key(e)].get("ts", ""))
    return todo + stale[:NDB_REFRESH_PER_RUN]


def fetch_ndb_or_file():
    """Program NdB ze souboru NDB_PROGRAM (připravený souběžnými úlohami ve workflow), jinak z webu."""
    path = os.environ.get("NDB_PROGRAM")
    if path is None:
        return fetch_ndb()
    if not Path(path).is_file():
        raise RuntimeError("žádná z úloh program NdB nestáhla (web NdB blokuje část serverů GitHubu)")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    events, stale = [], {}
    programs = json.loads(PROGRAMS.read_text(encoding="utf-8")) if PROGRAMS.exists() else {}
    for theatre, fetch in (("mdb", fetch_mdb), ("ndb", fetch_ndb_or_file)):
        name = THEATRES[theatre]["short"]
        try:
            found = fetch()
            print(f"{name}: {len(found)} představení", flush=True)
            programs[theatre] = {"ts": datetime.now().isoformat(timespec="seconds"), "events": found}
        except Exception as ex:  # nedostupný web jednoho divadla nemá shodit celou stránku
            saved = programs.get(theatre)
            print(f"{name}: nepodařilo se načíst program ({ex}), "
                  + (f"použije se uložený z {saved['ts']}" if saved else "uložený není"), flush=True)
            if not saved:
                continue
            found, stale[theatre] = saved["events"], saved["ts"]
        events += found
    PROGRAMS.write_text(json.dumps(programs, ensure_ascii=False, indent=1), encoding="utf-8")
    today = date.today().isoformat()
    events = [e for e in events if e["start"][:10] >= today]
    if sys.argv[1:]:
        events = [e for e in events if e["start"][:7] in sys.argv[1:]]
    events.sort(key=lambda e: (e["start"][:16], e["theatre"]))
    months = sorted({e["start"][:7] for e in events})

    urls = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    seats = json.loads(SEATS.read_text(encoding="utf-8")) if SEATS.exists() else {}
    todo = [] if os.environ.get("CACHE_ONLY") else todo_list(events, urls, seats)  # CACHE_ONLY: bez dotazů na prodejní systémy
    print(f"Načítám sály: {len(todo)}", flush=True)
    # Po jednom a s pauzou – při souběžných dotazech prodejní systém přestane odpovídat.
    for e in todo:
        k = key(e)
        url, hall = safe_hall_info(e["theatre"], e["cid"], urls.get(k))
        if url:
            urls[k] = url
            CACHE.write_text(json.dumps(urls, indent=1), encoding="utf-8")
        if hall is not None:
            seats[k] = {"cap": e["cap"], **hall, "ts": datetime.now().isoformat(timespec="seconds")}
            SEATS.write_text(json.dumps(seats, indent=1), encoding="utf-8")
        time.sleep(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(events, urls, seats, months, stale), encoding="utf-8")
    print(f"Hotovo: {OUT}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--ndb-program"]:
        found = fetch_ndb()
        Path(sys.argv[2]).write_text(json.dumps(found, ensure_ascii=False), encoding="utf-8")
        print(f"NdB: {len(found)} představení", flush=True)
    else:
        main()

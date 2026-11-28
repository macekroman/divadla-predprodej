"""Vygeneruje HTML přehled představení divadel s proklikem přímo na mapu sálu.

Divadla: Městské divadlo Brno a Hudební divadlo Karlín (API webu), Národní divadlo Brno, Slovácké divadlo
Uherské Hradiště, Jihočeské divadlo, Národní divadlo moravskoslezské, Divadlo Hybernia a Slezské divadlo Opava
(program z HTML webu) prodávají přes systém Colosseum, proto stejný postup
pro adresu sálu i volná místa. Divadlo J. K. Tyla Plzeň prodává přes novější verzi Colossea (Plzeňská vstupenka),
kde má každé představení stálou adresu a mapa sálu se načítá jinak. Divadlo Bolka Polívky, Husa na provázku
a HaDivadlo prodávají přes GoOut (program i mapa sálu z API GoOut). Moravské divadlo Olomouc prodává přes Webticket
vložený do stránky představení na webu divadla (místa z dat Webticketu).

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
            "server": "https://server.mdb.cz", "prefix": "mdb", "map_every_run": True,
            "form": {"mrsid": 1, "language": "cs", "currency": "CZK"}},
    "ndb": {"name": "Národní divadlo Brno", "short": "NdB", "web": "https://www.ndbrno.cz",
            "server": "https://online.colosseum.eu", "prefix": "ndbrno",
            "form": {"mrsid": 83, "language": "cs-CZ"}},
    "sd": {"name": "Slovácké divadlo", "short": "SD UH", "web": "https://www.slovackedivadlo.cz",
           "server": "https://evstupenky.slovackedivadlo.cz", "prefix": "divadlo", "cap_on_web": True,
           "form": {"mrsid": 1, "language": "cs-CZ", "currency": "CZK"}},
    "jd": {"name": "Jihočeské divadlo", "short": "JD", "web": "https://www.jihoceskedivadlo.cz",
           "server": "https://vstupenky.cbsystem.cz", "prefix": "jihoceske-divadlo",
           "form": {"mrsid": 4, "language": "cs-CZ"}},
    "hdk": {"name": "Hudební divadlo Karlín", "short": "HDK", "web": "https://www.hdk.cz",
            "server": "https://vstupenky.hdk.cz", "prefix": "hudebnidivadlokarlin", "cap_on_web": True,
            "form": {"mrsid": 256, "language": "cs-CZ"}},
    # Plzeňská vstupenka: představení má stálou adresu Hall/Event, mapa sálu z Hall/GetHall (viz websale_hall_info).
    "djkt": {"name": "Divadlo J. K. Tyla", "short": "DJKT", "web": "https://www.djkt.eu",
             "websale": "https://rezervace.plzenskavstupenka.cz", "mrsid": 6},
    "ndm": {"name": "Národní divadlo moravskoslezské", "short": "NDM", "web": "https://www.ndm.cz",
            "server": "https://prodej.ndm.cz", "prefix": "ndm", "form": {"mrsid": 114, "language": "cs-CZ"}},
    "hybernia": {"name": "Divadlo Hybernia", "short": "Hybernia", "web": "https://www.hybernia.eu",
                 "server": "https://booking.hybernia.eu", "prefix": "hybernia", "form": {"mrsid": 294, "language": "cs-CZ"}},
    # Webticket: prodej je ve stránce představení na webu divadla, místa z JSONP dat Webticketu (viz webticket_hall_info).
    "mdo": {"name": "Moravské divadlo Olomouc", "short": "MDO", "web": "https://moravskedivadlo.cz", "webticket": True},
    "sdo": {"name": "Slezské divadlo Opava", "short": "SDO", "web": "https://www.slezskedivadlo.cz",
            "server": "https://divadlo-opava.colosseum.eu", "prefix": "divadlo%20opava", "form": {"mrsid": 1, "language": "cs-CZ"}},
    # Prodávají přes GoOut místo Colossea; "goout" je ID pořadatele, "venues" jeho místa patřící divadlu.
    "dbp": {"name": "Divadlo Bolka Polívky", "short": "DBP", "web": "https://divadlobolkapolivky.cz", "goout": 164},
    "husa": {"name": "Divadlo Husa na provázku", "short": "Husa", "web": "https://www.provazek.cz", "goout": 121,
             "venues": {"Divadlo Husa na provázku"}},
    "hadivadlo": {"name": "HaDivadlo", "short": "HaDivadlo", "web": "https://www.hadivadlo.cz", "goout": 121,
                  "venues": {"HaDivadlo"}},
}
DEFAULT_THEATRE = "mdb"  # předvybrané divadlo ve filtru
# cap_on_web: počet volných míst uvádí web divadla, mapu sálu stačí načíst při jeho změně.
# map_every_run: číslo z webu se s mapou sálu rozchází (MDB), platí mapa a načítá se při každém běhu.
# Ostatním (NdB, JD) mapu sálu obnovujeme podle stáří.
NDB_REFRESH = timedelta(hours=6)
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


# --- Slovácké divadlo: celý program na jedné stránce, po měsících ---

def fetch_sd():
    web = THEATRES["sd"]["web"]
    page = opener().open(f"{web}/program", timeout=30).read().decode("utf-8", "replace")
    events, year = [], None
    for row in re.split(r'<tr class="program-', page)[1:]:
        if row.startswith("month"):  # <strong>Listopad 2026</strong>
            m = re.search(r"<strong>\s*(\S+)\s+(\d{4})", row)
            year = m.group(2) if m and m.group(1).lower() in MONTHS else None
        elif year:
            e = parse_sd_row(row, year)
            if e:
                events.append(e)
    return events


def parse_sd_row(b, year):
    when = re.search(r"<span>(\d\d)/(\d\d)</span>", b)
    hhmm = re.search(r'class="item-time"[^>]*>\s*(\d\d)\.(\d\d)', b)
    title = re.search(r'class="item-title">\s*(?:<a href="([^"]*)"[^>]*>)?(.*?)</(?:a|div)>', b, re.S)
    if not when or not hhmm or not title:
        return None
    cid = re.search(r'colosseum-buy-form.*?name="eventid" value="(\d+)"', b, re.S)
    sold_out = "Vyprodáno" in b
    if not cid and not sold_out:
        return None  # předplatné skupiny, prodej jinde (odkaz na cizí web), akce bez vstupenek
    # <span class="item-time" title="Zbývá 37 vstupenek z 382 (Prodáno: 345 = 90 %)">
    left = re.search(r'title="Zbývá (\d+) vstup', b)
    place = re.search(r'class="item-place">([^<]*)', b)
    d, mo = when.groups()
    href = title.group(1)
    stage = text(place.group(1)) if place else ""
    if stage == "Slovácké divadlo":  # program tak uvádí hlavní scénu, jinde na webu je „Hlavní scéna“
        stage = "Hlavní scéna"
    return {
        "theatre": "sd", "cid": cid.group(1) if cid else None, "start": f"{year}-{mo}-{d}T{hhmm.group(1)}:{hhmm.group(2)}:00",
        "title": text(title.group(2)), "url": urllib.parse.urljoin(THEATRES["sd"]["web"] + "/", href) if href else THEATRES["sd"]["web"],
        "stage": stage, "genre": "",
        "sale": None, "cap": 0 if sold_out else (int(left.group(1)) if left else None),
        "note": "vyprodáno" if sold_out else None,
    }


# --- Jihočeské divadlo: celý program je v kalendáři na hlavní stránce ---

JD_GENRES = {"ballet": "Balet", "drama": "Činohra", "opera": "Opera"}


def fetch_jd():
    page = opener().open(THEATRES["jd"]["web"], timeout=60).read().decode("utf-8", "replace")
    events = {}
    # Každý soubor má v kalendáři svůj řádek, představení jsou v něm jako vyskakovací okna.
    for row in re.split(r'<tr class="min_calendar-', page)[1:]:
        genre = JD_GENRES.get(row[:row.find('"')], "")
        for block in re.split(r'(?=<div class="min_calendar_modal"\s)', row)[1:]:
            e = parse_jd_block(block, genre)
            if e:
                events[e["cid"]] = e
    return list(events.values())


def parse_jd_block(b, genre):
    cid = re.search(r'name="eventid" value="(\d+)"', b)
    when = re.search(r'class="time">(\d{1,2})\.(\d{1,2})\.\s*(\d\d):(\d\d)', b)
    title = re.search(r'min_calendar_modal-name"><strong>(.*?)</strong>', b, re.S)
    if not cid or not when or not title:
        return None  # kurzy, prohlídky a představení jen pro školy
    d, mo, hh, mm = when.groups()
    # Kalendář uvádí datum bez roku a sahá necelý rok dopředu.
    recent = date.today() - timedelta(days=7)
    year = recent.year + ((int(mo), int(d)) < (recent.month, recent.day))
    url = re.search(r'href="([^"?]*/porad/[^"?]+)', b)
    stage = re.search(r'class="location">(.*?)</span>', b, re.S)
    sold_out = "buy_ticket-a watchdog" in b  # místo Koupit nabízí Hlídacího psa
    return {
        "theatre": "jd", "cid": cid.group(1), "start": f"{year}-{int(mo):02}-{int(d):02}T{hh}:{mm}:00",
        "title": text(title.group(1)), "url": url.group(1) if url else THEATRES["jd"]["web"],
        "stage": text(stage.group(1)) if stage else "", "genre": genre,
        "sale": None, "cap": 0 if sold_out else None, "note": "vyprodáno" if sold_out else None,
    }


# --- Hudební divadlo Karlín: JSON API webu (bez hlavičky Referer odpoví 403) ---

def fetch_hdk():
    web = THEATRES["hdk"]["web"]
    req = urllib.request.Request(f"{web}/api/performance-schedule", headers={
        "Accept": "application/json", "User-Agent": UA, "Referer": f"{web}/program-a-vstupenky",
        "X-Requested-With": "XMLHttpRequest"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = json.load(r)["events"]
    events = []
    for e in raw:
        p = e["performance"]
        # Web místo tlačítka Vstupenky ukazuje „Vyprodáno“, když je available 0.
        events.append({
            "theatre": "hdk", "cid": str(e["prdid"]), "start": e["start"].replace(" ", "T"),
            "title": p["name"].strip(), "url": p.get("performance_url") or web,
            "stage": e["venue"]["name"], "genre": "",
            "sale": None, "cap": e["available"], "note": None if e["available"] else "vyprodáno",
        })
    return events


# --- Divadlo J. K. Tyla Plzeň: celý program na jedné stránce, po měsících ---

DJKT_GENRES = {"muzikal": "Muzikál", "cinohra": "Činohra", "opera": "Opera", "balet": "Balet"}


def fetch_djkt():
    page = opener().open(f'{THEATRES["djkt"]["web"]}/program', timeout=60).read().decode("utf-8", "replace")
    events = {}
    # Měsíce: <… id="month-2026-11">, v nich představení <div class="row ensemble-muzikal" >
    for ym, part in re.findall(r'id="month-(\d{4}-\d\d)"(.*?)(?=id="month-\d{4}-\d\d"|$)', page, re.S):
        for block in re.split(r'<div class="row ensemble-', part)[1:]:
            e = parse_djkt_block(block, ym[:4])
            if e:
                events[e["cid"] or (e["title"], e["start"])] = e
    return list(events.values())


def parse_djkt_block(b, year):
    when = re.search(r'class="date">(\d{1,2})\. (\d{1,2})\.', b)
    title = re.search(r"<h3>(.*?)</h3>", b, re.S)
    hhmm = re.search(r"(\d\d):(\d\d)(?:&ndash;\d\d:\d\d)?\s*<strong>(.*?)</strong>", b, re.S)
    if not when or not title or not hhmm:
        return None
    cid = re.search(r"/Hall/Event\?eventId=(\d+)&(?:amp;)?mrsid=6", b)
    tickets = re.search(r'class="tickets[^>]*>(.*?)</div>', b, re.S)
    tickets = text(tickets.group(1)) if tickets else ""
    # Před začátkem prodeje: „Vstupenky v prodeji od 7. 12. 2026 10:00“ (ID akce na webu ještě není).
    sale = re.search(r"v&nbsp;prodeji\s*<nobr>od (\d{1,2})\. (\d{1,2})\. (\d{4}) (\d\d):(\d\d)", b)
    sold_out = tickets == "vyprodáno"
    if not cid and not sold_out and not sale:
        return None  # zadaná představení, lektorské úvody, prohlídky, akce bez vstupenek
    d, mo = when.groups()
    # „Posledních 12 vstupenek“, „Poslední vstupenka“, „0 volných, 2 rezervace“; jinak web počet neuvádí.
    left = re.match(r"(?:Posledn(?:í|ích) (\d+) vstup|(0) volných|(Poslední vstupenka))", tickets)
    cap = 0 if sold_out else (int(left.group(1) or left.group(2) or 1) if left else None)
    genre = re.match(r"([a-z]+)", b)
    url = re.search(r'href="([^"]+)"', title.group(1))
    return {
        "theatre": "djkt", "cid": cid.group(1) if cid else None,
        "start": f"{year}-{int(mo):02}-{int(d):02}T{hhmm.group(1)}:{hhmm.group(2)}:00",
        "title": text(title.group(1)), "url": urllib.parse.urljoin(THEATRES["djkt"]["web"] + "/", url.group(1)) if url else THEATRES["djkt"]["web"],
        "stage": text(hhmm.group(3)), "genre": DJKT_GENRES.get(genre.group(1) if genre else "", ""),
        "sale": "{2}-{1:0>2}-{0:0>2}T{3}:{4}:00".format(*sale.groups()) if sale else None, "cap": cap,
        "note": "vyprodáno" if sold_out else (None if cid else "prodej zatím nezačal"),
    }


# --- Národní divadlo moravskoslezské: celá zveřejněná část sezóny na jedné stránce ---
# Scéna v programu není, doplní se z mapy sálu (viz hall_info).

NDM_GENRES = {"Činohra": "Činohra", "Muzikál": "Muzikál", "Opera": "Opera", "Balet": "Balet",
              "Opereta / Muzikál": "Opereta / Muzikál"}


def fetch_ndm():
    page = opener().open(f'{THEATRES["ndm"]["web"]}/cz/program/aktualni-mesic/', timeout=60).read().decode("utf-8", "replace")
    events = {}
    # Stránka má program dvakrát (dva výpisy), proto podle ID akce.
    for row in re.split(r'<div class="program-row">', page)[1:]:
        day = re.search(r'class="program-date" id="(\d{4}-\d\d-\d\d)"', row)
        if not day:
            continue
        for item in re.split(r'<div class="program-item ', row)[1:]:
            e = parse_ndm_item(item, day.group(1))
            if e:
                events[e["cid"] or (e["title"], e["start"])] = e
    return list(events.values())


def parse_ndm_item(b, day):
    title = re.search(r'class="program-item-title"><a href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
    hhmm = re.search(r'class="program-item-time">\s*(\d{1,2}):(\d\d)', b)
    if not title or not hhmm:
        return None
    # Každé představení má dva formuláře: Vstupenky (mrsid 114) a Moje ABO (168, abonentní systém).
    cid = re.search(r'name="mrsid" value="114" />\s*<input type="hidden" name="eventid" value="(\d+)"', b)
    sold_out = b.startswith("program-vyprodano")
    cancelled = b.startswith("program-zruseno")
    not_yet = "PRODEJ VSTUPENEK NEZAH" in b
    if not cid and not (sold_out or cancelled or not_yet):
        return None  # zadaná představení, prohlídky, akce bez vstupenek
    genre = re.search(r'class="program-item-type">(.*?)</div>', b, re.S)
    return {
        "theatre": "ndm", "cid": cid.group(1) if cid else None, "start": f"{day}T{int(hhmm.group(1)):02}:{hhmm.group(2)}:00",
        "title": text(title.group(2)), "url": urllib.parse.urljoin(THEATRES["ndm"]["web"], title.group(1)),
        "stage": "", "genre": NDM_GENRES.get(text(genre.group(1)) if genre else "", ""),
        "sale": None, "cap": 0 if sold_out else None,
        "note": "zrušeno" if cancelled else "vyprodáno" if sold_out else None if cid else "prodej zatím nezačal",
    }


# --- Divadlo Hybernia: celý program (i proběhlý) na jedné stránce, po dnech ---

HYBERNIA_GENRES = ["Muzikál", "Činohra", "Opera", "Balet", "Koncert", "Tanec", "Show"]  # podle štítků, první shoda


def fetch_hybernia():
    page = opener().open(f'{THEATRES["hybernia"]["web"]}/program/', timeout=60).read().decode("utf-8", "replace")
    recent = (date.today() - timedelta(days=1)).isoformat()
    events = {}
    # <div class="perf-day" id="perf-day-2026-12-1"> … <div class="performance-card program">
    for day in re.split(r'<div class="perf-day" ', page)[1:]:
        d = re.match(r'id="perf-day-(\d{4})-(\d{1,2})-(\d{1,2})"', day)
        if not d:
            continue
        ymd = f"{d.group(1)}-{int(d.group(2)):02}-{int(d.group(3)):02}"
        if ymd < recent:
            continue
        for card in re.split(r'<div class="performance-card', day)[1:]:
            e = parse_hybernia_card(card, ymd)
            if e:
                events[e["cid"]] = e
    return list(events.values())


def parse_hybernia_card(b, ymd):
    cid = re.search(r'name="eventid" value="(\d+)"', b)
    hhmm = re.search(r'class="term-date">(\d{1,2}):(\d\d)', b)
    title = re.search(r'class="term-title"><a href="([^"]+)">(.*?)</a>', b, re.S)
    if not cid or not hhmm or not title:
        return None  # hostující představení s prodejem jinde („Více informací“)
    tags = re.findall(r'perf-tag">([^<]*)', b)
    sold_out = re.search(r'<span class="desktop">Vyprodáno', b)
    return {
        "theatre": "hybernia", "cid": cid.group(1), "start": f"{ymd}T{int(hhmm.group(1)):02}:{hhmm.group(2)}:00",
        "title": text(title.group(2)), "url": title.group(1), "stage": "",
        "genre": next((g for g in HYBERNIA_GENRES if g in tags), ""),
        "sale": None, "cap": 0 if sold_out else None, "note": "vyprodáno" if sold_out else None,
    }


# --- Moravské divadlo Olomouc: program po stránkách z AJAXu webu, prodej přes Webticket ---

MDO_GENRES = {"cinohra": "Činohra", "opera": "Opera", "balet": "Balet"}


def fetch_mdo():
    web = THEATRES["mdo"]["web"]
    content = []
    for page in range(100):  # {"content": "<article …>…", "page": 1, "remainder": 88}
        req = urllib.request.Request(f"{web}/cs/_ajax/filtered/{page}/list",
                                     headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        content.append(d["content"])
        if not d.get("remainder"):
            break
        time.sleep(1)
    events = {}
    for article in re.split(r'<article class="show', "".join(content))[1:]:
        e = parse_mdo_article(article)
        if e:
            events[e["cid"] or (e["title"], e["start"])] = e
    return list(events.values())


def parse_mdo_article(b):
    when = re.search(r'class="date"><a[^>]*>\s*\S+ (\d{1,2})\. (\d{1,2})\.(?:&nbsp;|\s)*<span class="time">(\d{1,2}):(\d\d)', b)
    title = re.search(r'<h2 class="title[^"]*"><a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
    tickets = re.search(r'<div class="tickets">(.*?)</div>', b, re.S)
    if not when or not title or not tickets:
        return None
    # <a href="/cs/cinohra/inscenace/chvilky/vstupenky/1510" class="tickets button">Vstupenky</a>, nebo „Vyprodáno“
    buy = re.search(r'href="([^"]+/vstupenky/(\d+))"', tickets.group(1))
    sold_out = "Vyprodáno" in tickets.group(1)
    if not buy and not sold_out:
        return None  # akce bez prodeje (jen „O představení“)
    d, mo, hh, mm = when.groups()
    # Program uvádí datum bez roku a sahá zhruba čtvrt roku dopředu.
    recent = date.today() - timedelta(days=7)
    year = recent.year + ((int(mo), int(d)) < (recent.month, recent.day))
    place = re.search(r'class="auditorium">([^<]*)', b)
    ensembles = re.findall(r'class="en_([a-z-]+)"', b)
    web = THEATRES["mdo"]["web"]
    return {
        "theatre": "mdo", "cid": buy.group(2) if buy else None, "start": f"{year}-{int(mo):02}-{int(d):02}T{int(hh):02}:{mm}:00",
        "title": text(title.group(2)), "url": web + title.group(1),
        # „Sedmička, Sokolská 7, Ol.“ → „Sedmička“
        "stage": text(place.group(1)).split(",")[0] if place else "",
        "genre": next((MDO_GENRES[x] for x in ensembles if x in MDO_GENRES), ""),
        "sale": None, "cap": 0 if sold_out else None, "note": "vyprodáno" if sold_out else None,
        "tickets": web + buy.group(1) if buy else None,
    }


# --- Slezské divadlo Opava: zveřejněný program na jedné stránce ---

SDO_GENRES = {"opera": "Opera", "cinohra": "Činohra"}


def fetch_sdo():
    page = opener().open(f'{THEATRES["sdo"]["web"]}/program', timeout=60).read().decode("utf-8", "replace")
    events = {}
    for row in re.split(r'<tr class="c-Table-row c-Table-row--', page)[1:]:
        e = parse_sdo_row(row.split("</tr>")[0])
        if e:
            events[e["cid"] or (e["title"], e["start"])] = e
    return list(events.values())


def parse_sdo_row(b):
    when = re.search(r'<time datetime="(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)', b)
    title = re.search(r'<a\s+href="([^"]+)"\s+class="c-Table-link"\s*>(.*?)</a>', b, re.S)
    if not when or not title:
        return None
    cid = re.search(r'name="eventid" value="(\d+)"', b)
    sold_out = "Vyprodáno" in b
    if not cid and not sold_out:
        return None  # zájezdy, zadaná představení
    # Před začátkem prodeje: „Prodej od 14. 12. 2026 9:00“ (mapa sálu už jde otevřít)
    sale = re.search(r"Prodej od (\d{1,2})\. (\d{1,2})\. (\d{4}) (\d{1,2}):(\d\d)", b)
    return {
        "theatre": "sdo", "cid": cid.group(1) if cid else None, "start": when.group(1),
        "title": text(title.group(2)), "url": urllib.parse.urljoin(THEATRES["sdo"]["web"], title.group(1)),
        "stage": "", "genre": SDO_GENRES.get(b[:b.find('"')], ""),
        "sale": "{2}-{1:0>2}-{0:0>2}T{3:0>2}:{4}:00".format(*sale.groups()) if sale else None,
        "cap": 0 if sold_out else None, "note": "vyprodáno" if sold_out else None,
    }


# --- Divadla na GoOut: program a místa z API GoOut (volají ho i weby divadel a prodejní formulář) ---

GOOUT = "https://goout.net/services"
GOOUT_GENRES = {"play": "Činohra", "concerts": "Koncert", "for_children": "Pro děti"}


def fetch_goout(theatre):
    """Představení pořadatele t["goout"]; sdílí-li pořadatele víc divadel, rozliší je t["venues"]."""
    t = THEATRES[theatre]
    params = [("contactIds[]", t["goout"]), ("languages[]", "cs"), ("hasSale", "true"),
              ("included", "events,sales,venues")]
    schedules, included, scroll = [], {}, None
    while True:
        more = [("scrollId", scroll)] if scroll else []
        d = get_json(f"{GOOUT}/entities/v2/schedules?" + urllib.parse.urlencode(params + more))
        schedules += d["data"]
        included.update(((x["type"], x["id"]), x) for x in d["included"])
        scroll = d["meta"].get("nextScrollId")
        if not d["data"] or not scroll:
            break
    # DBP nemá v GoOut odkazy na svůj web (sourceUrls), dohledáme je z jeho programu.
    web_urls = dbp_web_urls() if theatre == "dbp" else {}
    events = []
    for s in schedules:
        a, rel = s["attributes"], s["relationships"]
        sale = included.get(("sales", ((rel.get("sale") or {}).get("data") or {}).get("id")))
        state = a["ticketingState"]
        if not sale or not a["hasTime"] or state in ("hidden", "ended"):
            continue  # bez prodeje, poukázky, skryté a skončené prodeje
        event = included.get(("events", rel["event"]["data"]["id"]))
        venue = included.get(("venues", rel["venue"]["data"]["id"]))
        venue_name = venue["attributes"]["locales"]["cs"]["name"] if venue else ""
        if "venues" in t and venue_name not in t["venues"]:
            continue  # jiné divadlo stejného pořadatele
        # Scéna: „Divadlo Bolka Polívky – Bílý dům“ → „Bílý dům“, samotné divadlo bez scény.
        stage = "" if venue_name == t["name"] else venue_name.removeprefix(t["name"] + " – ")
        events.append({
            "theatre": theatre, "cid": sale["id"], "start": a["startAt"],
            "title": event["attributes"]["locales"]["cs"]["name"] if event else "",
            "url": web_urls.get(a["startAt"][:16]) or next(iter(a["sourceUrls"]), None) or a["locales"]["cs"]["siteUrl"],
            "stage": stage, "genre": GOOUT_GENRES.get(event["attributes"]["mainCategory"], "") if event else "",
            "sale": sale["attributes"]["startAt"], "cap": 0 if state == "sold_out" else None,
            "note": {"sold_out": "vyprodáno", "cancelled": "zrušeno"}.get(state),
        })
    if theatre == "husa":  # scény (provázek.sál, provázek.sklep…) má v GoOut jen málokteré představení
        stages = husa_stages(sorted({e["start"][:7] for e in events}))
        for e in events:
            e["stage"] = stages.get(e["start"][:16], "")
    return events


def husa_stages(months):
    """Scény představení z programu na webu Husy podle začátku (bez představení, která začínají současně).
    Web je v Next.js, program měsíce je ve stránce jako data: … "date":"2026-11-02" … "stage":[{"_key":"cs",
    "value":"provázek.sál"}],"time":"18:30"."""
    found = {}
    for ym in months:
        try:
            page = opener().open(f'{THEATRES["husa"]["web"]}/program/{ym}', timeout=30).read().decode("utf-8", "replace")
        except Exception as ex:  # scény pak zůstanou prázdné
            print(f"  Husa: program {ym} na webu nedostupný ({ex})", flush=True)
            continue
        page = page.replace('\\"', '"')
        days = [(m.start(), m.group(1)) for m in re.finditer(r'"date":"(\d{4}-\d\d-\d\d)"', page)]
        for m in re.finditer(r'"stage":\[\{"_key":"cs","value":"([^"]*)"\}[^\]]*\],"time":"(\d\d:\d\d)"', page):
            day = next((d for pos, d in reversed(days) if pos < m.start()), None)  # datum termínu je před scénou
            if day:
                found.setdefault(f"{day}T{m.group(2)}", set()).add(m.group(1))
        time.sleep(1)
    return {k: v.pop() for k, v in found.items() if len(v) == 1}


def dbp_web_urls():
    """Stránky představení na webu divadla podle začátku (bez představení, která začínají současně)."""
    try:
        page = opener().open(f'{THEATRES["dbp"]["web"]}/program/', timeout=30).read().decode("utf-8", "replace")
    except Exception as ex:  # odkazy pak povedou na GoOut
        print(f"  DBP: web divadla nedostupný ({ex})", flush=True)
        return {}
    found = {}
    # <div class="events-item" data-date="2026-10-21 19:00:00"> … <div class="events-title"><a href="…">
    for day, hhmm, url in re.findall(r'data-date="([-\d]+) (\d\d:\d\d):\d\d".*?class="events-title">\s*<a href="([^"]+)"', page, re.S):
        found.setdefault(f"{day}T{hhmm}", set()).add(url)
    return {k: v.pop() for k, v in found.items() if len(v) == 1}


def goout_halls(events):
    """Prodeje GoOut po 20 najednou. Vrací {id prodeje: (adresa prodeje, místa jako u hall_info)}.
    U volného sezení (bez mapy sálu) volná místa spočítat nejde, GoOut uvádí jen limit na objednávku –
    pak jsou místo "cats" jen ceny "prices"."""
    found = {}
    for i in range(0, len(events), 20):
        q = urllib.parse.urlencode({"saleIds": ",".join(e["cid"] for e in events[i:i + 20]), "language": "cs"})
        for sid, s in get_json(f"{GOOUT}/feeder/v3/sales?{q}")["sales"].items():
            # Skryté kategorie (přístavky, blokace) se koupit nedají.
            prices = {d["id"]: str(d["priceCents"] // 100) for d in s["deals"].values() if d["active"] and not d["hidden"]}
            cats = {}
            for seat in (x for h in s["halls"] for x in h["seats"]):
                price = prices.get(seat["dealId"])
                if price:
                    total_free = cats.setdefault(price, [0, 0])
                    total_free[0] += 1
                    total_free[1] += bool(seat["available"])
            # Bez mapy sálu jsou kategorie druhy vstupenek (student, senior, mecenášská…) – stačí základní.
            basic = [d["priceCents"] // 100 for d in s["deals"].values()
                     if d["id"] in prices and d["name"].startswith("Základní")]
            found[sid] = (s["url"], {"cats": cats, "on_sale": s["state"] == "ACTIVE",
                                     **({} if cats else {"prices": sorted(set(basic) or {int(p) for p in prices.values()})})})
        time.sleep(1)
    return found


# --- Colosseum: adresa sálu a mapa míst ---

def hall_info(theatre, cid, url=None):
    """Projde vstupem /hall (jako tlačítko na webu), od PrepareDetail získá adresu sálu (pokud ji
    ještě neznáme) a z mapy sálu spočítá místa v cenových kategoriích.
    Vrací (url, {"cats": {cena: [míst celkem, volných]}, "on_sale": bool})."""
    t = THEATRES[theatre]
    if "websale" in t:
        return websale_hall_info(t, cid)
    if t.get("webticket"):
        return webticket_hall_info(url)
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
    # Scéna z hlavičky sálu – pro divadla, jejichž program ji neuvádí (NDM, Hybernia).
    venue = re.search(r'class="hall-title-venue[^"]*">.*?</i>(.*?)</div>', page, re.S)
    # Před začátkem prodeje: „Akce není v prodeji“ (MDB), „Na tuto akci je možné provádět rezervace od …“ (SDO).
    on_sale = "Akce není v prodeji" not in page and "možné provádět rezervace od" not in page
    return url, {"cats": cats, "on_sale": on_sale,
                 **({"venue": text(venue.group(1))} if venue else {})}


def websale_hall_info(t, cid):
    """Plzeňská vstupenka: adresa představení je stálá (otevře ji i odkaz), mapu sálu vrací Hall/GetHall
    v rámci session založené touto stránkou. Velký sál může být rozdělený na sektory (načtou se po jednom),
    malé sály bývají bez místenek – pak jsou jen ceny jako u volného sezení na GoOut."""
    url = f'{t["websale"]}/Hall/Event?eventId={cid}&mrsid={t["mrsid"]}'
    o = opener()
    page = o.open(url, timeout=15).read().decode("utf-8", "replace")
    on_sale = not re.search(r'id="HallReadOnly"[^>]*value="true"', page)

    def get_hall(section=""):
        req = urllib.request.Request(f'{t["websale"]}/Hall/GetHall?eventId={cid}&sectionId={section}&venueId=0',
                                     headers={"X-Requested-With": "XMLHttpRequest"})
        return o.open(req, timeout=15).read().decode("utf-8", "replace")

    hall = get_hall()
    # Sektory: <g class="section" data-section-id="105681" data-section-type="STD" …>; NON je na stání.
    sections = re.findall(r'<g class="section" data-section-id="([-\d]+)" data-section-type="STD"', hall)
    halls = [hall] if not sections else [get_hall(s) for s in sections]
    # Místo: <g class="seat free ckt_6 cktIdx_8" … data-full-price="280,0" data-ckt-id="6"> nebo
    # <g class="seat unavailable" data-ticket-id="…" data-ckt-id="7"> – cenu nese jen volné místo.
    seats = [(state, dict(re.findall(r'data-(ckt-id|full-price)="([^"]*)"', attrs)))
             for h in halls for state, attrs in re.findall(r'<g class="seat (\w+)[^"]*"([^>]*)>', h)]
    price = {s["ckt-id"]: s["full-price"].split(",")[0] for _, s in seats if "full-price" in s and "ckt-id" in s}
    cats = {}
    for state, s in seats:
        p = price.get(s.get("ckt-id"))
        if p:  # kategorie bez jediného volného místa nemají známou cenu, vynechají se
            total_free = cats.setdefault(p, [0, 0])
            total_free[0] += 1
            total_free[1] += state == "free"
    if not seats and not sections:  # bez místenek: <span class="tour-row__price"> 50,00 Kč</span>
        prices = {int(p) for p in re.findall(r'tour-row__price">\s*(\d+)', hall)}
        return url, {"cats": {}, "on_sale": on_sale, **({"prices": sorted(prices)} if prices else {})}
    return url, {"cats": cats, "on_sale": on_sale}


WEBTICKET = "https://www.webticket.cz/api/1.t"


def webticket_hall_info(url):
    """Webticket: stránka představení na webu divadla (url) vloží prodej s ID akce – wt3Akce({id : 82692, …}).
    Data akce (JSONP) mají v "akced" jen místa, která nejsou prodaná: st 0 volné, 2 rezervované, -1 mimo prodej.
    Prodaná místa v datech chybí i s cenou, proto jen volná místa po cenách, bez počtu míst celkem."""
    page = opener().open(url, timeout=15).read().decode("utf-8", "replace")
    wid = re.search(r"wt3Akce\(\{\s*id\s*:\s*(\d+)", page)
    if not wid:
        return url, {"cats": {}, "on_sale": False}  # prodej na stránce zatím není
    with opener().open(f"{WEBTICKET}/data/akce.jsonp?idAkce={wid.group(1)}&callback=cb", timeout=15) as r:
        raw = r.read().decode("utf-8", "replace")
    d = json.loads(raw[raw.find("(") + 1:raw.rfind(")")])
    cats = {}
    for seat in (d.get("akced") or {}).values():
        if seat.get("st") == 0:
            total_free = cats.setdefault(str(seat["ce"]), [0, 0])
            total_free[0] += 1
            total_free[1] += 1
    return url, {"cats": cats, "free_only": True, "on_sale": bool(d.get("prodej_ok"))}


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
    if not cats:  # volné sezení na GoOut: jen ceny, bez počtu míst
        prices = (info or {}).get("prices")
        return price_range(prices) if prices else '<span class="muted">–</span>'
    free =[int(p) for p, (_, f) in cats.items() if f]
    summary = price_range(free) if free else '<span class="muted">nic volného</span>'
    free_only = info.get("free_only")  # Webticket: počet míst celkem neznáme
    rows = "".join(f"<div>{p}&nbsp;Kč: <b>{f}</b>{'' if free_only else f' / {t}'}</div>"
                   for p, (t, f) in sorted(cats.items(), key=lambda c: -int(c[0])))
    legend = "volná" if free_only else "volná / celkem"
    return f'<details><summary>{summary}</summary><div class="cats">{rows}<div class="muted">{legend}</div></div></details>'


def free_count(e, info):
    """Číslo z programu (SD UH, vyprodáno), jinak součet volných míst z mapy sálu. U MDB má přednost mapa,
    kromě představení mimo prodej – těm se mapa neobnovuje."""
    if e["cap"] is not None and (e["note"] or not THEATRES[e["theatre"]].get("map_every_run")):
        return e["cap"]
    cats = (info or {}).get("cats")
    return sum(f for _, f in cats.values()) if cats else e["cap"]


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
    stages = [s for s in stages if s[1]]  # divadla bez scén (SDO) ve výběru vynechat
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
        elif t.get("goout") or t.get("websale") or t.get("webticket"):  # tyto prodeje ukazují mapu sálu rovnou
            btn = f'<a class="button" href="{html.escape(url)}" target="_blank" rel="noopener">Vstupenky</a>'
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

    config = {k: {"server": t["server"], "form": t["form"]} for k, t in THEATRES.items() if "server" in t}
    links = ", ".join(f'<a href="{t["web"]}" target="_blank" rel="noopener">{t["short"]}</a>' for t in THEATRES.values())
    return f"""<!doctype html>
<html lang="cs"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Divadla – sály</title>
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
button, a.button {{ background:var(--accent); color:#fff; border:0; border-radius:8px; padding:7px 14px; font-weight:600; cursor:pointer }}
a.button {{ display:inline-block; text-decoration:none }} a.button:hover {{ color:#fff }}
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
<div class="top"><h1>Divadla – sály a volná místa</h1><button id="theme" onclick="cycleTheme()"></button></div>
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
U DJKT otevře přímo představení v prodeji Plzeňské vstupenky (u představení, jejichž předprodej ještě nezačal, odkaz web divadla zatím nemá), u MDO stránku představení s prodejem na webu divadla, u DBP, Husy na provázku a HaDivadla přímo prodej na GoOut.
„Volno“ u SD UH a HDK je počet volných míst, jak ho uvádí web divadla, u MDB a DBP součet volných míst z mapy sálu (obnovuje se při každé aktualizaci stránky), u NdB, JD, DJKT, NDM, Hybernie, MDO a SDO součet volných míst z mapy sálu (obnovuje se zhruba každých 6 hodin; u DJKT má přednost „Posledních N vstupenek“ z webu). MDO neuvádí, kolik míst má cenová kategorie celkem, proto jen volná místa. Husa na provázku a HaDivadlo nemají místenky, GoOut u nich počet volných míst neuvádí.
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
    """Představení, u kterých je potřeba načíst sál: nová, u MDB všechna, u SD UH se změnou počtu volných míst podle webu,
    u NdB s mapou starší než NDB_REFRESH (nejstarší napřed, nejvýš NDB_REFRESH_PER_RUN)."""
    now = datetime.now()
    todo, stale = [], []
    for e in events:
        if not e["cid"] or e["note"] or THEATRES[e["theatre"]].get("goout"):
            continue  # GoOut: viz goout_halls
        k = key(e)
        info = seats.get(k)
        if k not in urls or not info or THEATRES[e["theatre"]].get("map_every_run"):
            todo.append(e)
        elif THEATRES[e["theatre"]].get("cap_on_web"):
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
    fetchers = [("mdb", fetch_mdb), ("ndb", fetch_ndb_or_file), ("sd", fetch_sd), ("jd", fetch_jd),
                ("hdk", fetch_hdk), ("djkt", fetch_djkt), ("ndm", fetch_ndm), ("hybernia", fetch_hybernia),
                ("mdo", fetch_mdo), ("sdo", fetch_sdo)]
    fetchers += [(k, lambda k=k: fetch_goout(k)) for k, t in THEATRES.items() if "goout" in t]
    for theatre, fetch in fetchers:
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
        url, hall = safe_hall_info(e["theatre"], e["cid"], urls.get(k) or e.get("tickets"))
        if url:
            urls[k] = url
            CACHE.write_text(json.dumps(urls, indent=1), encoding="utf-8")
        if hall is not None:
            seats[k] = {"cap": e["cap"], **hall, "ts": datetime.now().isoformat(timespec="seconds")}
            SEATS.write_text(json.dumps(seats, indent=1), encoding="utf-8")
        time.sleep(1)

    # GoOut vrátí místa pro víc prodejů jedním dotazem, proto pokaždé všechna představení.
    goout = [e for e in events if THEATRES[e["theatre"]].get("goout") and e["cid"] and not e["note"]]
    if goout and not os.environ.get("CACHE_ONLY"):
        try:
            found = goout_halls(goout)
        except Exception as ex:  # zůstanou naposledy uložená data
            print(f"  GoOut: {ex}", flush=True)
            found = {}
        now = datetime.now().isoformat(timespec="seconds")
        for e in goout:
            if e["cid"] in found:
                urls[key(e)], hall = found[e["cid"]]
                seats[key(e)] = {"cap": e["cap"], **hall, "ts": now}
        CACHE.write_text(json.dumps(urls, indent=1), encoding="utf-8")
        SEATS.write_text(json.dumps(seats, indent=1), encoding="utf-8")

    for e in events:  # scéna z mapy sálu, když ji program neuvádí: „Divadlo Hybernia (hlavní sál)“ → „Hlavní sál“
        venue = (seats.get(key(e)) or {}).get("venue") if e["cid"] and not e["stage"] else None
        if venue and venue != THEATRES[e["theatre"]]["name"]:  # SDO uvádí jen název divadla
            inner = re.fullmatch(re.escape(THEATRES[e["theatre"]]["name"]) + r" \((.+)\)", venue)
            e["stage"] = inner.group(1)[:1].upper() + inner.group(1)[1:] if inner else venue

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

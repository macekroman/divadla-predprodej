# Divadla – sály a volná místa

Neoficiální rozcestník: seznam představení Městského divadla Brno, Národního divadla Brno,
Slováckého divadla Uherské Hradiště, Jihočeského divadla, Hudebního divadla Karlín a Divadla J. K. Tyla Plzeň
s počtem volných míst, cenami a tlačítkem, které otevře mapu sálu v prodejním systému Colosseum –
i u představení, jejichž předprodej ještě nezačal (kromě DJKT). Divadlo Bolka Polívky, Divadlo Husa na provázku
a HaDivadlo prodávají přes GoOut, tlačítko tam otevře jeho prodejní formulář. Nákup probíhá výhradně na webech divadel a GoOut.

## Jak to funguje

- MDB: seznam představení se bere z API webu `https://www.mdb.cz/api/event/events`. Volná místa se počítají
  z mapy sálu, která se načítá při každém běhu – `availableCapacity` z API se s mapou rozchází (i o desítky míst).
- NdB: program se čte z HTML stránek `https://www.ndbrno.cz/program/?month=M&years=R`;
  z formuláře „Vstupenky“ se bere `eventid` (prodejní systém `online.colosseum.eu`, `mrsid=83`).
- Slovácké divadlo: celý program je na stránce `https://www.slovackedivadlo.cz/program` (rok z nadpisů
  měsíců, počet volných míst z popisku „Zbývá N vstupenek z M“); prodejní systém
  `evstupenky.slovackedivadlo.cz` (`mrsid=1`, cesta `/divadlo/standard/Hall/...`).
- Jihočeské divadlo: celý program je v kalendáři na hlavní stránce `https://www.jihoceskedivadlo.cz`
  (datum bez roku, tlačítko Hlídací pes znamená vyprodáno); prodejní systém `vstupenky.cbsystem.cz`
  (`mrsid=4`, cesta `/jihoceske-divadlo/standard/Hall/...`).
- Hudební divadlo Karlín: program z API webu `https://www.hdk.cz/api/performance-schedule` (bez hlavičky
  `Referer` odpoví 403); `prdid` je `eventid` v Colosseu, `available` počet volných míst, jak ho ukazuje web
  (mapa sálu se proto načítá jen při jeho změně). Prodejní systém `vstupenky.hdk.cz` (`mrsid=256`, cesta
  `/hudebnidivadlokarlin/standard/Hall/...`).
- Divadlo J. K. Tyla Plzeň: celý program je na stránce `https://www.djkt.eu/program` (měsíce `id="month-RRRR-MM"`,
  soubor ze třídy `ensemble-…`, „Posledních N vstupenek“ jako počet volných míst). Prodává přes novější verzi
  Colossea (Plzeňská vstupenka, `rezervace.plzenskavstupenka.cz`, `mrsid=6`): představení má stálou adresu
  `/Hall/Event?eventId=…&mrsid=6`, na kterou vede tlačítko přímo, a mapu sálu vrací `/Hall/GetHall?eventId=…`
  (s hlavičkou `X-Requested-With`, ve stejné session). Cenu nese jen volné místo, kategorie bez volných míst
  proto v rozpadu cen chybí. Velké sály mohou být rozdělené na sektory (načítají se po jednom), foyer bývá
  bez místenek (jen ceny). Představení před začátkem předprodeje nemají na webu ID akce, takže u nich odkaz chybí.
- Divadlo Bolka Polívky (GoOut, pořadatel 164): program z `https://goout.net/services/entities/v2/schedules`
  (stejné API volá web divadla), místa podle cenových kategorií z `https://goout.net/services/feeder/v3/sales`
  (u každého místa `dealId` a `available`, až 20 prodejů jedním dotazem – proto se obnovují každou hodinu
  všechna). Skryté kategorie (přístavky, blokace) se nepočítají. Odkaz na popis vede na stránku
  představení na webu divadla, dohledanou podle data a času.
- Divadlo Husa na provázku a HaDivadlo (GoOut, společný pořadatel CED 121, rozlišené podle místa;
  Terén téhož pořadatele vynechán): stejné API jako DBP, odkaz na popis z `sourceUrls`. Prodávají bez
  místenek, takže GoOut počet volných míst neuvádí – jen vyprodáno a základní vstupné. Scény Husy
  (provázek.sál, provázek.sklep…) jsou z programu na webu `https://www.provazek.cz/program/RRRR-MM`
  (data Next.js ve stránce), spárované podle data a času.
- Tlačítko „Koupit vstupenky“ na webu posílá POST na `https://server.mdb.cz/hall` (`mrsid=1`, `eventid`).
  Session si pak pamatuje představení a `/mdb/standard/Hall/PrepareDetail` vrátí adresu sálu
  `Hall/Index/<id>/<token>`. Token je pro představení stálý, proto se ukládá do `hall_urls.json`.
- Tlačítko „Vstupenky“ na stránce v prohlížeči návštěvníka odešle stejný POST do nové záložky
  a po 2,5 s ji přepne na adresu sálu.

## Spuštění lokálně

```
python divadla_predprodej.py            # všechna budoucí představení v programu
python divadla_predprodej.py 2026-12    # konkrétní měsíc
```

Uložená data (`hall_urls.json`, `seats.json`, `programs.json`) jsou na domácím serveru
v `~/divadla-predprodej`; bez nich skript načte všechny sály znovu.

## Zveřejnění

Stránku každou hodinu přegeneruje domácí server: cron spouští `aktualizace.sh`, který stáhne
nový kód z `main`, spustí skript a hotovou stránku nahraje do větve `gh-pages` (jediný commit,
který se pokaždé přepíše). GitHub Pages zveřejňuje přímo tuto větev. Na serveru web NdB
neblokuje dotazy jako u GitHub Actions a data mezi běhy zůstávají na disku.

Ručně se běh spustí na serveru příkazem `~/divadla-predprodej/aktualizace.sh`. Výstup posledního
běhu je v `~/divadla-predprodej.log`, výsledek hlídá Healthchecks (adresa v `~/.hc-divadla`).

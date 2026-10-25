# Divadla – sály a volná místa

Neoficiální rozcestník: seznam představení Městského divadla Brno, Národního divadla Brno
a Slováckého divadla Uherské Hradiště s počtem volných míst, cenami a tlačítkem, které otevře mapu sálu v prodejním systému Colosseum –
i u představení, jejichž předprodej ještě nezačal. Divadlo Bolka Polívky, Divadlo Husa na provázku
a HaDivadlo prodávají přes GoOut, tlačítko tam otevře jeho prodejní formulář. Nákup probíhá výhradně na webech divadel a GoOut.

## Jak to funguje

- MDB: seznam představení se bere z API webu `https://www.mdb.cz/api/event/events`
  (včetně počtu volných míst `availableCapacity`).
- NdB: program se čte z HTML stránek `https://www.ndbrno.cz/program/?month=M&years=R`;
  z formuláře „Vstupenky“ se bere `eventid` (prodejní systém `online.colosseum.eu`, `mrsid=83`).
- Slovácké divadlo: celý program je na stránce `https://www.slovackedivadlo.cz/program` (rok z nadpisů
  měsíců, počet volných míst z popisku „Zbývá N vstupenek z M“); prodejní systém
  `evstupenky.slovackedivadlo.cz` (`mrsid=1`, cesta `/divadlo/standard/Hall/...`).
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

Uložená data jsou ve větvi `data`; bez nich skript načte všechny sály znovu. Stáhnout jdou takto:

```
git fetch origin data && git checkout origin/data -- . && git restore --staged .
```

## Zveřejnění

GitHub Actions (`.github/workflows/pages.yml`) stránku každou hodinu přegeneruje (včetně počtu volných míst z API webu), uloží nové
adresy sálů, volná místa a program do větve `data` (jediný commit, který se pokaždé přepíše,
ať nezanáší historii `main`) a nasadí ji na GitHub Pages. Spustit ručně jde přes záložku Actions
→ „Aktualizace stránky“ → Run workflow.

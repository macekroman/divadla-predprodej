# Brněnská divadla – sály a volná místa

Neoficiální rozcestník: seznam představení Městského divadla Brno a Národního divadla Brno
s počtem volných míst, cenami a tlačítkem, které otevře mapu sálu v prodejním systému Colosseum –
i u představení, jejichž předprodej ještě nezačal. Nákup probíhá výhradně na webech divadel.

## Jak to funguje

- MDB: seznam představení se bere z API webu `https://www.mdb.cz/api/event/events`
  (včetně počtu volných míst `availableCapacity`).
- NdB: program se čte z HTML stránek `https://www.ndbrno.cz/program/?month=M&years=R`;
  z formuláře „Vstupenky“ se bere `eventid` (prodejní systém `online.colosseum.eu`, `mrsid=83`).
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

## Zveřejnění

GitHub Actions (`.github/workflows/pages.yml`) stránku každou hodinu přegeneruje (včetně počtu volných míst z API webu), uloží nové
adresy sálů do repozitáře a nasadí ji na GitHub Pages. Spustit ručně jde přes záložku Actions
→ „Aktualizace stránky“ → Run workflow.

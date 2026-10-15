# MDB – sály představení

Neoficiální rozcestník: seznam představení Městského divadla Brno s tlačítkem, které otevře
mapu sálu v prodejním systému (server.mdb.cz) – i u představení, jejichž předprodej ještě nezačal.
Nákup probíhá výhradně na webu divadla.

## Jak to funguje

- Seznam představení se bere z API webu `https://www.mdb.cz/api/event/events`.
- Tlačítko „Koupit vstupenky“ na webu posílá POST na `https://server.mdb.cz/hall` (`mrsid=1`, `eventid`).
  Session si pak pamatuje představení a `/mdb/standard/Hall/PrepareDetail` vrátí adresu sálu
  `Hall/Index/<id>/<token>`. Token je pro představení stálý, proto se ukládá do `hall_urls.json`.
- Tlačítko „Sál“ na stránce v prohlížeči návštěvníka odešle stejný POST do nové záložky
  a po 2,5 s ji přepne na adresu sálu.

## Spuštění lokálně

```
python mdb_predprodej.py            # všechna budoucí představení v programu
python mdb_predprodej.py 2026-12    # konkrétní měsíc
```

## Zveřejnění

GitHub Actions (`.github/workflows/pages.yml`) stránku dvakrát denně přegeneruje, uloží nové
adresy sálů do repozitáře a nasadí ji na GitHub Pages. Spustit ručně jde přes záložku Actions
→ „Aktualizace stránky“ → Run workflow.

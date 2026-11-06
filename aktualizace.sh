#!/bin/sh
# Spouští ho cron na domácím serveru: stáhne nový kód, přegeneruje stránku a nahraje ji do větve
# gh-pages, odkud ji zveřejní GitHub Pages. Větev má jediný commit, který se pokaždé přepíše,
# ať historie nenarůstá. Adresu kontroly v Healthchecks čte z ~/.hc-divadla (HC_URL=...).
set -u
cd "$(dirname "$0")"

# Běhy se nesmí překrývat (dlouhé načítání sálů by se zdvojilo).
exec 9>.aktualizace.lock
flock -n 9 || { echo "Předchozí běh ještě neskončil."; exit 0; }

HC_URL=""
[ -f "$HOME/.hc-divadla" ] && . "$HOME/.hc-divadla"
hc() { [ -z "$HC_URL" ] || curl -fsS -m 10 --retry 3 -o /dev/null "$HC_URL$1" || true; }
hc /start

date "+Začátek: %Y-%m-%d %H:%M"
git pull --ff-only -q || echo "git pull selhal, běží stávající kód"

status=0
OUT=site/index.html TZ=Europe/Prague python3 -u divadla_predprodej.py || status=$?

if [ "$status" -eq 0 ]; then
    tmp=$(mktemp -d)
    cp site/index.html "$tmp/"
    touch "$tmp/.nojekyll"  # Pages stránku nemá zpracovávat přes Jekyll
    git -C "$tmp" init -q -b gh-pages
    git -C "$tmp" add -A
    git -C "$tmp" -c user.name="divadla-predprodej (server)" -c user.email="server@divadla-predprodej" \
        commit -q -m "Stránka z $(date '+%Y-%m-%d %H:%M')"
    git -C "$tmp" push -q --force "$(git remote get-url origin)" gh-pages || status=$?
    rm -rf "$tmp"
fi

hc "/$status"
date "+Konec: %Y-%m-%d %H:%M, stav $status"
exit "$status"

#!/bin/sh
set -eu
mkdir -p /config /config/backups /projects /library /releases /temp
# Legacy relative paths remain application-owned; container roots are the mounted targets.
ln -sfn /config /app/Data
ln -sfn /projects /app/Projects
ln -sfn /library /app/Library
ln -sfn /releases /app/Releases
ln -sfn /temp /app/Temp
db=/config/catalog.sqlite3
head=$(alembic -c /app/alembic.ini heads | awk '{print $1}')
current=""
if [ -f "$db" ]; then current=$(alembic -c /app/alembic.ini current 2>/dev/null | awk 'NR==1 {print $1}' || true); fi
if [ -f "$db" ] && [ "$current" != "$head" ]; then
  backup=/config/backups/catalog-$(date -u +%Y%m%dT%H%M%SZ).sqlite3
  cp "$db" "$backup"
  sqlite3 "$backup" 'PRAGMA quick_check;' | grep -qx ok
fi
alembic -c /app/alembic.ini upgrade head
exec "$@"

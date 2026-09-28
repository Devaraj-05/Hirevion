#!/bin/sh
# Creates the extra local databases and the extensions every Hirevion database needs.
set -eu

for db in "$POSTGRES_DB" hirevion_test glitchtip; do
  exists=$(psql -tA --username "$POSTGRES_USER" --dbname postgres \
    -c "SELECT 1 FROM pg_database WHERE datname = '$db'")
  if [ "$exists" != "1" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres -c "CREATE DATABASE \"$db\""
  fi
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<'SQL'
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
SQL
done

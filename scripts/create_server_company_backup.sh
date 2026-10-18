#!/usr/bin/env bash
set -Eeuo pipefail

project_root="${1:-/var/www/finora/supermaxi}"
output_file="${2:-}"

if [[ ! "$project_root" =~ ^/[A-Za-z0-9._/-]+$ ]]; then
  echo "Invalid project path" >&2
  exit 2
fi
if [[ ! "$output_file" =~ ^/tmp/finora-company-backup-[a-f0-9]+\.tar\.zst$ ]]; then
  echo "Invalid output path" >&2
  exit 2
fi

cd "$project_root"
if [[ ! -f .env ]]; then
  echo ".env not found" >&2
  exit 3
fi

set -a
# shellcheck disable=SC1091
. ./.env
set +a

stage="$(mktemp -d /tmp/finora-company-stage-XXXXXXXX)"
trap 'rm -rf -- "$stage"' EXIT
mkdir -p "$stage/companies" "$stage/external-uploads"

pg_dump \
  --format=custom \
  --compress=6 \
  --no-owner \
  --no-privileges \
  --file="$stage/central-postgres.dump" \
  "$DATABASE_URL"
pg_restore --list "$stage/central-postgres.dump" >/dev/null

mapfile -t tenant_slugs < <(
  psql "$DATABASE_URL" -Atc \
    "SELECT slug FROM tenants WHERE slug ~ '^[a-z0-9][a-z0-9_-]{0,63}$' ORDER BY slug"
)

copied_count=0
for slug in "${tenant_slugs[@]}"; do
  source_db="$project_root/tenants/$slug.db"
  if [[ ! -f "$source_db" ]]; then
    printf 'WARNING missing tenant database: %s\n' "$slug" >&2
    continue
  fi
  destination_db="$stage/companies/$slug.db"
  sqlite3 "$source_db" ".timeout 30000" ".backup '$destination_db'"
  integrity="$(sqlite3 "$destination_db" 'PRAGMA quick_check;')"
  if [[ "$integrity" != "ok" ]]; then
    echo "SQLite verification failed for $slug" >&2
    exit 4
  fi
  copied_count=$((copied_count + 1))
done

if [[ -d /var/www/finora/uploads ]]; then
  cp -a /var/www/finora/uploads/. "$stage/external-uploads/"
fi

{
  printf 'created_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'tenant_databases=%s\n' "$copied_count"
  printf 'includes=central-postgres,tenant-sqlite,static-uploads,project-uploads,external-uploads\n'
  printf 'tenant_slugs=' 
  printf '%s ' "${tenant_slugs[@]}"
  printf '\n'
} >"$stage/MANIFEST.txt"

tar_args=(
  --zstd -cf "$output_file"
  -C "$stage" MANIFEST.txt central-postgres.dump companies external-uploads
)
if [[ -d "$project_root/static/uploads" ]]; then
  tar_args+=( -C "$project_root" static/uploads )
fi
if [[ -d "$project_root/uploads" ]]; then
  tar_args+=( -C "$project_root" uploads )
fi
tar "${tar_args[@]}"
tar --zstd -tf "$output_file" >/dev/null
test -s "$output_file"

printf 'COMPANY_BACKUP_OK tenants=%s size=%s\n' "$copied_count" "$(stat -c %s "$output_file")"


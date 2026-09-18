# Step 2: verify the migrations and the root compose.yaml from a cold start.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
# Its own compose project and port, so a stack started with `docker compose up` is untouched
$env:COMPOSE_PROJECT_NAME = 'am-step2'
$env:DB_PORT = '55432'

function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } }
function Psql([string]$Db, [string]$Sql) {
    docker compose exec -T db psql -U postgres -d $Db -X -c $Sql 2>&1 | ForEach-Object { "$_" }
}

"=== 1. cold start: down -v, then up -d (db and migrate start together)"
Dc down -v
Dc up -d
$st = ''
for ($i = 0; $i -lt 60; $i++) {
    $st = docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" albert-marketplace-migrate-1 2>$null
    if ($st -like 'exited*') { break }
    Start-Sleep -Seconds 2
}
"migrate container: $st"
Dc logs --no-color migrate
Dc ps -a --format "table {{.Service}}\t{{.State}}\t{{.Status}}"

"=== 2. run migrate again: nothing to apply"
Dc run --rm migrate
Dc run --rm migrate status

"=== 3. behaviour checks"
Dc cp "$S\step2_checks.sql" db:/tmp/step2_checks.sql
docker compose exec -T db sh -c "psql -U postgres -d marketplace -X -f /tmp/step2_checks.sql 2>&1"

"=== 4. baseline against the original scripts (HEAD:db/*.sql), schema-only dumps"
# db_creation.sql, Triggers.sql and Procedures.sql live only in the import commit now
foreach ($name in 'db_creation', 'Triggers', 'Procedures') {
    if (-not (Test-Path "$S\legacy_$($name).sql")) {
        git -C $repo show "ee9fbf7:db/$($name).sql" | Out-File -Encoding ascii "$S\legacy_$($name).sql"
    }
}
docker compose exec -T db createdb -U postgres legacy
foreach ($name in 'db_creation', 'Triggers', 'Procedures') {
    Dc cp "$S\legacy_$($name).sql" "db:/tmp/legacy_$($name).sql"
}
docker compose exec -T db sh -c "for f in db_creation Triggers Procedures; do psql -U postgres -d legacy -X -q -v ON_ERROR_STOP=1 -f /tmp/legacy_`$f.sql || exit 1; done; echo legacy scripts loaded"
docker compose exec -T db sh -c "pg_dump -U postgres -s -O -x --restrict-key=step2 legacy > /tmp/legacy.sql && pg_dump -U postgres -s -O -x --restrict-key=step2 marketplace > /tmp/migrated.sql && diff -u /tmp/legacy.sql /tmp/migrated.sql; echo diff-exit=`$?"

"=== 5. round trip: roll back both migrations, migrate up again, compare schemas"
docker compose exec -T db sh -c "pg_dump -U postgres -s -O -x --restrict-key=step2 marketplace > /tmp/before.sql"
Dc run --rm migrate rollback
Dc run --rm migrate rollback
Psql marketplace "SELECT coalesce(string_agg(table_name, ', '), '(none)') AS tables_left FROM information_schema.tables WHERE table_schema = 'public'"
Psql marketplace "SELECT count(*) AS routines_left FROM information_schema.routines WHERE routine_schema = 'public'"
Dc run --rm migrate
docker compose exec -T db sh -c "pg_dump -U postgres -s -O -x --restrict-key=step2 marketplace > /tmp/after.sql && diff -u /tmp/before.sql /tmp/after.sql && echo round-trip: schema identical"

"=== 6. storefront models and checkout on the migrated schema"
docker compose run --rm -v "${S}:/scratch:ro" --entrypoint python storefront-api /scratch/step2_storefront.py 2>&1 | ForEach-Object { "$_" }

"=== 7. footprint"
docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}" 2>&1 | Select-String 'albert-marketplace'
docker image inspect ghcr.io/amacneil/dbmate:2.35.1 --format "dbmate image {{.Size}} bytes"

# Step 6: build and run the reconciled storefront from scratch on the generated database, in its own project.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:COMPOSE_PROJECT_NAME = 'am-step6'
$env:DB_PORT = '55432'
$env:API_PORT = '18100'
$env:UI_PORT = '18510'
if (-not $env:LEGACY_CSV_DIR) { $env:LEGACY_CSV_DIR = 'C:/Users/charl/Documents/Work/ALBERT_SCHOOL/TANGOAI_EDUCATION_assets/datasets/Amazon/Amazon_tx_database_files' }
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Stopping|Stopped|Removing|Removed|Recreate|Recreated)|(Volume|Network) .* (Creating|Created|Removing|Removed)|^\s*$'
function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }
function SchemaDump([string]$Out) {
    docker compose exec -T db pg_dump -U postgres -s -O -x --restrict-key=step6 marketplace 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 $Out
}

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    "Docker Desktop is not running: starting it"
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 90; $i++) { Start-Sleep -Seconds 3; docker info --format "{{.ServerVersion}}" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { break } }
}
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { "ABORT: Docker is still not reachable"; exit 1 }

"=== 0. no storefront/.env; compose services"
"storefront/.env exists: " + (Test-Path storefront\.env)
"default services: " + ((docker compose config --services 2>&1) -join ', ')

"=== 1. build the images from scratch (no cache)"
Dc --profile build down -v --rmi local
$t = Measure-Command { docker compose build --no-cache storefront-api storefront-ui 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 "$S\build6.log" }
"build exit=$LASTEXITCODE in $([int]$t.TotalSeconds) s"
Select-String -Path "$S\build6.log" -Pattern 'ERROR|error:|WARN' | Select-Object -Last 10 | ForEach-Object { "  " + $_.Line }
docker image ls --format "{{.Repository}}:{{.Tag}}  {{.Size}}" | Select-String 'am-step6'

"=== 2. database and migrations; schema before the storefront starts"
Dc up -d db migrate
$st = ''
for ($i = 0; $i -lt 60; $i++) {
    $st = docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" am-step6-migrate-1 2>$null
    if ($st -like 'exited*') { break }
    Start-Sleep -Seconds 2
}
"migrate: $st"
if ($st -ne 'exited exit=0') { "ABORT: migrations did not complete"; exit 1 }

"=== 3. generate the history (seed 7, end 2026-09-15)"
$t = Measure-Command { docker compose --profile build run --rm generate-history --seed 7 --end-date 2026-09-15 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 "$S\gen6.log" }
"generate exit=$LASTEXITCODE in $([int]$t.TotalSeconds) s"
Get-Content "$S\gen6.log" | Select-String -Pattern '^(seed|orders|customers)' | ForEach-Object { "  $_" }
SchemaDump "$S\schema_before.sql"

"=== 4. storefront up (db and migrations already done)"
Dc up -d
$health = ''
for ($i = 0; $i -lt 60; $i++) {
    $health = docker inspect -f "{{.State.Health.Status}}" am-step6-storefront-api-1 2>$null
    if ($health -eq 'healthy') { break }
    Start-Sleep -Seconds 2
}
"storefront-api health: $health"
Dc ps -a --format "table {{.Service}}\t{{.State}}\t{{.Status}}"
"restarts: api " + (docker inspect -f "{{.RestartCount}}" am-step6-storefront-api-1) + ", ui " + (docker inspect -f "{{.RestartCount}}" am-step6-storefront-ui-1)
for ($i = 0; $i -lt 30; $i++) {
    try { $r = Invoke-WebRequest -UseBasicParsing "http://localhost:18510/_stcore/health" -TimeoutSec 5; break } catch { Start-Sleep -Seconds 2 }
}
"UI health: " + $(if ($r) { "$($r.StatusCode) $($r.Content)" } else { 'no answer' })
SchemaDump "$S\schema_after.sql"
"schema unchanged by the storefront starting: " + ((Get-FileHash "$S\schema_before.sql").Hash -eq (Get-FileHash "$S\schema_after.sql").Hash)

"=== 5. models against the migrated schema"
Dc cp "$S\step6_models_check.py" storefront-api:/tmp/step6_models_check.py
docker compose exec -T storefront-api python /tmp/step6_models_check.py 2>&1 | ForEach-Object { "$_" }

"=== 6. API"
$env:PYTHONIOENCODING = 'utf-8'
python "$S\step6_api_test.py" "http://localhost:18100"

"=== 7. UI flow (headless)"
$uiBuyer = docker compose exec -T db psql -U postgres -d marketplace -XAt -c "SELECT buyer_id FROM buyer ORDER BY buyer_id OFFSET 1 LIMIT 1"
Dc cp "$S\step6_ui_test.py" storefront-ui:/tmp/step6_ui_test.py
docker compose exec -T storefront-ui python /tmp/step6_ui_test.py $uiBuyer 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch 'Thread .MainThread.: missing ScriptRunContext|^\s*$'

"=== 8. logs"
"api log lines with ERROR, Traceback or Warning: " + @(docker compose logs --no-color storefront-api 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern 'ERROR|Traceback|Warning').Count
docker compose logs --no-color storefront-api 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern 'ERROR|Traceback|Warning' | Select-Object -First 5 | ForEach-Object { "  $_" }
"api responses by status: " + ((docker compose logs --no-color storefront-api 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern 'HTTP/1.1" (\d{3})' | ForEach-Object { $_.Matches[0].Groups[1].Value } | Group-Object | Sort-Object Name | ForEach-Object { "$($_.Name)x$($_.Count)" }) -join ' ')

"=== 9. footprint"
docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}" | Select-String 'am-step6'

"=== 10. tear down"
Dc --profile build down -v

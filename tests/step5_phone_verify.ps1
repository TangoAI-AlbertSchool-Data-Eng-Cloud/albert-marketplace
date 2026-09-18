# Step 5 (phones): verify the VARCHAR(15) migration in its own compose project.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
$csvDir = 'C:/Users/charl/Documents/Work/ALBERT_SCHOOL/TANGOAI_EDUCATION_assets/datasets/Amazon/Amazon_tx_database_files'
Set-Location $repo
$env:COMPOSE_PROJECT_NAME = 'am-step5'
$env:DB_PORT = '55432'
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Stopping|Stopped|Removing|Removed|Recreate|Recreated)|(Volume|Network) .* (Creating|Created|Removing|Removed)|^\s*$'
function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }
function Sql([string]$Query) { docker compose exec -T db psql -U postgres -d marketplace -X -c $Query 2>&1 | ForEach-Object { "$_" } }

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    "Docker Desktop is not running: starting it"
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 90; $i++) { Start-Sleep -Seconds 3; docker info --format "{{.ServerVersion}}" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { break } }
}
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { "ABORT: Docker is still not reachable"; exit 1 }

"=== 1. cold start: three migrations"
Dc down -v
Dc up -d
$st = ''
for ($i = 0; $i -lt 60; $i++) {
    $st = docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" am-step5-migrate-1 2>$null
    if ($st -like 'exited*') { break }
    Start-Sleep -Seconds 2
}
"migrate: $st"
if ($st -ne 'exited exit=0') { "ABORT: migrations did not complete"; Dc logs --no-color migrate; exit 1 }
Dc logs --no-color migrate
Sql "SELECT table_name, column_name, data_type, character_maximum_length FROM information_schema.columns WHERE column_name = 'phone' ORDER BY table_name"

"=== 2. legacy load: phones unchanged"
$env:LEGACY_CSV_DIR = $csvDir
docker compose --profile build run --rm load-legacy 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern 'ERROR|error|customer |shipping_details ' | ForEach-Object { "  $_" }
"load exit=$LASTEXITCODE"
Remove-Item Env:LEGACY_CSV_DIR
Sql "SELECT 'customer' AS t, count(*), min(length(phone)), max(length(phone)), count(*) FILTER (WHERE phone LIKE '% ') AS trailing_spaces FROM customer UNION ALL SELECT 'shipping_details', count(*), min(length(phone)), max(length(phone)), count(*) FILTER (WHERE phone LIKE '% ') FROM shipping_details"
$env:PYTHONIOENCODING = 'utf-8'
python "$S\step3_fidelity.py" $csvDir

"=== 3. a 12-digit German mobile fits; 16 digits do not"
Sql "INSERT INTO customer (c_id, fname, lname, phone, email, pwd) VALUES ('de-check-1', 'Test', 'Mobil', '015112345678', 'de-check-1@example.com', 'x') RETURNING phone, length(phone)"
Sql "INSERT INTO customer (c_id, fname, lname, phone, email, pwd) VALUES ('de-check-2', 'Test', 'Zu lang', '0151123456789012', 'de-check-2@example.com', 'x')"

"=== 4. rolling the migration back refuses while a longer phone exists, then works once it is gone"
Dc run --rm migrate rollback
Dc run --rm migrate status
Sql "DELETE FROM customer WHERE c_id = 'de-check-1'"
Dc run --rm migrate rollback
Sql "SELECT table_name, data_type, character_maximum_length FROM information_schema.columns WHERE column_name = 'phone' ORDER BY table_name"
Dc run --rm migrate
Dc run --rm migrate status

"=== 5. storefront models and checkout on this schema"
docker compose run --rm -v "${S}:/scratch:ro" --entrypoint python storefront-api /scratch/step2_storefront.py 2>&1 | ForEach-Object { "$_" }

"=== 6. tear down"
Dc down -v

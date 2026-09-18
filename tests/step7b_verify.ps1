# Step 7, part B: restart, SIMULATION on and off, step 6 regression, footprint, tear down.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:COMPOSE_PROJECT_NAME = 'am-step7'
$env:DB_PORT = '55432'; $env:API_PORT = '18100'; $env:UI_PORT = '18510'
$env:KAFKA_PORT = '39092'; $env:KAFKA_DOCKER_PORT = '39093'
if (-not $env:LEGACY_CSV_DIR) { $env:LEGACY_CSV_DIR = 'C:/Users/charl/Documents/Work/ALBERT_SCHOOL/TANGOAI_EDUCATION_assets/datasets/Amazon/Amazon_tx_database_files' }
$env:CLOCK_ACCELERATION = '720'
$env:ORDERS_PER_DAY = '50'
$env:PYTHONIOENCODING = 'utf-8'
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Stopping|Stopped|Removing|Removed|Recreate|Recreated)|(Volume|Network) .* (Creating|Created|Removing|Removed)|^\s*$'
function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }
function Q([string]$Sql) { docker compose exec -T db psql -U postgres -d marketplace -XAt -c $Sql 2>&1 | ForEach-Object { "$_" } }
function WaitApi {
    for ($i = 0; $i -lt 60; $i++) { if ((docker inspect -f "{{.State.Health.Status}}" am-step7-storefront-api-1 2>$null) -eq 'healthy') { return 'healthy' }; Start-Sleep -Seconds 2 }
    return 'NOT healthy'
}

"=== 8. restart: the clock resumes where the data ends"
$maxOrder = Q "SELECT max(order_id) FROM orders"
$maxPaid = Q "SELECT max(created_at) FROM payment"
"before restart: last order $maxOrder, last payment $maxPaid"
Dc start load-generator
Start-Sleep -Seconds 60
Dc stop load-generator
docker compose logs --no-color load-generator 2>&1 | ForEach-Object { "$_" } | Select-String 'simulated clock starts at' | ForEach-Object { "  $_" }
"new orders after the restart, and whether all are later than the last payment: " + (Q "SELECT count(*) || ' orders, all later: ' || coalesce(bool_and(p.created_at > TIMESTAMP '$maxPaid'), false) FROM payment p WHERE p.order_id > $maxOrder")

"=== 9. SIMULATION off, then on again"
$env:SIMULATION = 'false'
Dc up -d storefront-api
"api: " + (WaitApi)
python "$S\step7_header_test.py" "http://localhost:18100" off
Remove-Item Env:SIMULATION
Dc up -d storefront-api
"api: " + (WaitApi)
python "$S\step7_header_test.py" "http://localhost:18100" on

"=== 10. the step 6 API tests still pass"
python "$S\step6_api_test.py" "http://localhost:18100" | Select-String -Pattern 'FAIL|failed'

"=== 11. footprint"
Dc start load-generator
Start-Sleep -Seconds 30
docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}" | Select-String 'am-step7' | ForEach-Object { "  $_" }
docker image ls --format "{{.Repository}}  {{.Size}}" | Select-String 'am-step7' | ForEach-Object { "  $_" }

"=== 12. tear down"
Dc --profile build down -v

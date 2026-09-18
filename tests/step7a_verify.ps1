# Step 7, part A: live traffic at high speed on the generated history; every event against the database.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:COMPOSE_PROJECT_NAME = 'am-step7'
$env:DB_PORT = '55432'; $env:API_PORT = '18100'; $env:UI_PORT = '18510'
$env:KAFKA_PORT = '39092'; $env:KAFKA_DOCKER_PORT = '39093'
if (-not $env:LEGACY_CSV_DIR) { $env:LEGACY_CSV_DIR = 'C:/Users/charl/Documents/Work/ALBERT_SCHOOL/TANGOAI_EDUCATION_assets/datasets/Amazon/Amazon_tx_database_files' }
$env:CLOCK_ACCELERATION = '720'   # a simulated day every two real minutes
$env:ORDERS_PER_DAY = '50'
$RUN_SECONDS = 330
# Seed 7 and end date 2026-09-15, from the verified step 5 run
$HISTORY = @{
    'customer' = 'd7baa1547b05fa76667a83f13ef1964f'; 'shipping_details' = '7c5ceda374c4d58132535200c1fdccda'
    'payment_details' = 'ee81df9117485430df93db917e172977'; 'orders' = 'e32489b4cb3402408f3805b605807a87'
    'order_items' = 'd60c31ed4dbe90e438a11a30173f3101'; 'payment' = '274263691c7b793d69f627376669ea43'
    'shipment' = '9add676db367490257494e8cc3a688b9'
}
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Stopping|Stopped|Removing|Removed|Recreate|Recreated)|(Volume|Network) .* (Creating|Created|Removing|Removed)|^\s*$'
function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }
function Q([string]$Sql) { docker compose exec -T db psql -U postgres -d marketplace -XAt -c $Sql 2>&1 | ForEach-Object { "$_" } }
function WaitExited([string]$Container) {
    for ($i = 0; $i -lt 90; $i++) {
        $st = docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" $Container 2>$null
        if ($st -like 'exited*') { return $st }
        Start-Sleep -Seconds 2
    }
    return "still $st"
}

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { "ABORT: Docker is not running"; exit 1 }

"=== 0. the lock matches pyproject.toml"
Dc --profile build down -v
docker compose --profile build run --rm calibrate uv lock --locked 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "  $_" }
"uv lock --locked exit=$LASTEXITCODE"

"=== 1. build"
$t = Measure-Command { docker compose build storefront-api storefront-ui load-generator 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 "$S\build7.log" }
"build exit=$LASTEXITCODE in $([int]$t.TotalSeconds) s"
Select-String -Path "$S\build7.log" -Pattern 'ERROR|error:' | Select-Object -Last 5 | ForEach-Object { "  " + $_.Line }
docker image ls --format "{{.Repository}}  {{.Size}}" | Select-String 'am-step7'

"=== 2. database, migrations and history (seed 7, end 2026-09-15)"
Dc up -d db migrate
"migrate: " + (WaitExited 'am-step7-migrate-1')
$t = Measure-Command { docker compose --profile build run --rm generate-history --seed 7 --end-date 2026-09-15 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 "$S\gen7.log" }
"generate exit=$LASTEXITCODE in $([int]$t.TotalSeconds) s"
Dc cp "$S\step3_fingerprint.sql" db:/tmp/fp.sql
$fp = docker compose exec -T db psql -U postgres -d marketplace -XAt -f /tmp/fp.sql 2>&1 | ForEach-Object { "$_" }
foreach ($table in $HISTORY.Keys | Sort-Object) {
    $md5 = (($fp | Where-Object { $_ -like "$table|*" }) -split '\|')[2]
    "  $table unchanged by the shared europe.py: " + $(if ($md5 -eq $HISTORY[$table]) { 'yes' } else { "NO ($md5)" })
}
Q "SELECT json_build_object('latest', max(created_at), 'products_below_5', (SELECT count(*) FROM product WHERE qty < 5), 'shipments', (SELECT json_object_agg(status, n) FROM (SELECT status, count(*) AS n FROM shipment GROUP BY status) s)) FROM payment" | Out-File -Encoding utf8 "$S\baseline7.json"
"baseline: " + (Get-Content "$S\baseline7.json")

"=== 3. everything up; traffic for $RUN_SECONDS s at $($env:CLOCK_ACCELERATION)x, $($env:ORDERS_PER_DAY) orders per simulated day"
Dc up -d
"kafka-init: " + (WaitExited 'am-step7-kafka-init-1')
for ($i = 0; $i -lt 60; $i++) { if ((docker inspect -f "{{.State.Health.Status}}" am-step7-storefront-api-1 2>$null) -eq 'healthy') { break }; Start-Sleep -Seconds 2 }
Dc ps -a --format "table {{.Service}}\t{{.State}}\t{{.Status}}"
Start-Sleep -Seconds 100
"generator log after 100 s:"
docker compose logs --no-color load-generator 2>&1 | ForEach-Object { "$_" } | Select-Object -Last 3 | ForEach-Object { "  $_" }
"memory under traffic:"
docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}" | Select-String 'am-step7' | ForEach-Object { "  $_" }
Start-Sleep -Seconds ($RUN_SECONDS - 100)

"=== 4. stop the generator"
Dc stop load-generator
docker compose logs --no-color load-generator 2>&1 | ForEach-Object { "$_" } | Select-Object -Last 4 | ForEach-Object { "  $_" }

"=== 5. read every event from Kafka"
docker compose exec -T kafka bash -c "/opt/kafka/bin/kafka-console-consumer.sh --bootstrap-server kafka:9092 --topic clickstream --from-beginning --timeout-ms 20000 --formatter-property print.key=true --formatter-property key.separator='|' > /tmp/events.txt 2>/dev/null; wc -l < /tmp/events.txt"
Dc cp kafka:/tmp/events.txt "$S\events7.txt"

"=== 6. validate"
$env:PYTHONIOENCODING = 'utf-8'
python "$S\step7_validate.py" "$S\events7.txt" "$S\baseline7.json" $env:CLOCK_ACCELERATION $env:ORDERS_PER_DAY

"=== 7. API responses"
"storefront-api responses by status: " + ((docker compose logs --no-color storefront-api 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern 'HTTP/1.1" (\d{3})' | ForEach-Object { $_.Matches[0].Groups[1].Value } | Group-Object | Sort-Object Name | ForEach-Object { "$($_.Name)x$($_.Count)" }) -join ' ')
"api tracebacks: " + @(docker compose logs --no-color storefront-api 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern 'Traceback').Count
"(stack left running for part B)"

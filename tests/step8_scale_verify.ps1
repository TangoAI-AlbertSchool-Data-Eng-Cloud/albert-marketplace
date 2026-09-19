# Step 8: --scale. Scale 1.0 must reproduce the released dataset exactly, and a
# scaled copy must keep every rule the full one keeps. Its own compose project.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:COMPOSE_PROJECT_NAME = 'am-scale'
$env:DB_PORT = '55440'
$env:SEED_URL = ''
if (-not $env:LEGACY_CSV_DIR) { $env:LEGACY_CSV_DIR = 'C:/Users/charl/Documents/Work/ALBERT_SCHOOL/TANGOAI_EDUCATION_assets/datasets/Amazon/Amazon_tx_database_files' }
$END = '2026-09-15'
$REVIEWS = 111322
# Seed 7, end date 2026-09-15: the released v1.0.0 history (tests/step5_verify.ps1)
$HISTORY = @{
    'carrier'     = '8e2337035c873956873605d9bdb532e5'
    'order_items' = 'd60c31ed4dbe90e438a11a30173f3101'
    'orders'      = 'e32489b4cb3402408f3805b605807a87'
    'payment'     = '274263691c7b793d69f627376669ea43'
    'shipment'    = '9add676db367490257494e8cc3a688b9'
}
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Stopping|Stopped|Removing|Removed|Recreate|Recreated)|(Volume|Network) .* (Creating|Created|Removing|Removed)|^\s*$'
function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }
function Psql([string]$sql) { (docker compose exec -T db psql -U postgres -d marketplace -At -c $sql 2>&1 | ForEach-Object { "$_" }) -join "`n" }
function Generate([string]$Log, [string[]]$GenArgs) {
    $t = Measure-Command { docker compose --profile build run --rm generate-history @GenArgs 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 $Log }
    $code = $LASTEXITCODE
    "generate $($GenArgs -join ' ') -> exit=$code in $([int]$t.TotalSeconds) s"
    Get-Content $Log | Select-String -Pattern '^(seed|orders|shipment status|customers)' | ForEach-Object { "  $_" }
    if ($code -ne 0) {
        Get-Content $Log | Select-Object -Last 15 | ForEach-Object { "  $_" }
        "ABORT: generation failed"; Dc --profile build down -v; exit 1
    }
}
function Fingerprint([string]$Out) {
    docker compose exec -T db psql -U postgres -d marketplace -XAt -f /tmp/fp.sql 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 $Out
    @(Get-Content $Out | Where-Object { $_ -match '^\w+\|\d+\|[0-9a-f]{32}$' }).Count
}
function Md5([string]$File, [string]$Table) {
    $line = Get-Content $File | Where-Object { $_ -like "$Table|*" } | Select-Object -First 1
    if ($line) { ($line -split '\|')[2] } else { 'missing' }
}
function Rules([string]$scale, [int]$expectedPairs) {
    "  scale $scale"
    "  orders {0}, expected {1}" -f (Psql "SELECT count(*) FROM orders"), (2 * $expectedPairs)
    "  payments = orders: " + (Psql "SELECT (SELECT count(*) FROM payment) = (SELECT count(*) FROM orders)")
    "  every order has lines: " + (Psql "SELECT (SELECT count(DISTINCT order_id) FROM order_items) = (SELECT count(*) FROM orders)")
    "  shipments = order lines: " + (Psql "SELECT (SELECT count(*) FROM shipment) = (SELECT count(*) FROM order_items)")
    "  every line set appears an even number of times per buyer (the twin defect): " +
        (Psql "SELECT count(*) = 0 FROM (
                   SELECT buyer_id, lines FROM (
                       SELECT o.order_id, o.buyer_id, string_agg(i.p_id || ':' || i.qty, ',' ORDER BY i.p_id) AS lines
                       FROM orders o JOIN order_items i USING (order_id)
                       GROUP BY o.order_id, o.buyer_id
                   ) per_order
                   GROUP BY buyer_id, lines HAVING count(*) % 2 <> 0
               ) odd")
    "  every order keeps its buyer and a real card: " +
        (Psql "SELECT count(*) = 0 FROM orders o LEFT JOIN buyer b USING (buyer_id)
               LEFT JOIN payment_details p USING (payment_id) WHERE b.buyer_id IS NULL OR p.payment_id IS NULL")
    "  dates: " + (Psql "SELECT min(order_date) || ' to ' || max(order_date) FROM orders")
    "  sequence at the highest order id: " +
        (Psql "SELECT last_value = (SELECT max(order_id) FROM orders) FROM orders_order_id_seq")
    "  revenue: " + (Psql "SELECT round(sum(amount)) FROM payment")
    "  stock: " + (Psql "SELECT sum(qty) FROM product") + ", products " + (Psql "SELECT count(*) FROM product") +
        ", customers " + (Psql "SELECT count(*) FROM customer") + ", reviews " + (Psql "SELECT count(*) FROM review")
}

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    "Docker Desktop is not running: starting it"
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 90; $i++) { Start-Sleep -Seconds 3; docker info --format "{{.ServerVersion}}" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { break } }
}
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { "ABORT: Docker is still not reachable"; exit 1 }

"=== 0. a fresh database and migrations"
Dc --profile build down -v
Dc up -d db migrate | ForEach-Object { "  $_" }
for ($i = 0; $i -lt 60; $i++) { if ((docker inspect -f "{{.State.Status}}" am-scale-migrate-1 2>$null) -eq 'exited') { break }; Start-Sleep -Seconds 2 }
"  migrate: " + (docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" am-scale-migrate-1 2>$null)
Dc cp "$S\step3_fingerprint.sql" db:/tmp/fp.sql

"=== 1. no --scale: the released history"
Generate "$S\scale_none.log" @('--seed', '7', '--end-date', $END)
"tables fingerprinted: " + (Fingerprint "$S\fp_none.txt")
foreach ($t in $HISTORY.Keys | Sort-Object) {
    "  $t matches the released dataset: " + $(if ((Md5 "$S\fp_none.txt" $t) -eq $HISTORY[$t]) { 'yes' } else { 'NO -> ' + (Md5 "$S\fp_none.txt" $t) })
}

"=== 2. --scale 1: byte for byte the same"
Generate "$S\scale_one.log" @('--seed', '7', '--end-date', $END, '--scale', '1')
Fingerprint "$S\fp_one.txt" | Out-Null
"  fingerprint identical to the run without --scale: " +
    $(if ((Get-FileHash "$S\fp_none.txt").Hash -eq (Get-FileHash "$S\fp_one.txt").Hash) { 'yes' } else { 'NO' })

"=== 3. --scale 0.1: a tenth of the orders"
Generate "$S\scale_small.log" @('--seed', '7', '--end-date', $END, '--scale', '0.1')
Fingerprint "$S\fp_small.txt" | Out-Null
Rules '0.1' ([int][Math]::Round($REVIEWS * 0.1))
"  the catalogue and the people are untouched:"
foreach ($t in 'product', 'review', 'customer', 'shipping_details', 'payment_details', 'buyer') {
    "    $t " + $(if ((Md5 "$S\fp_small.txt" $t) -eq (Md5 "$S\fp_none.txt" $t)) { 'identical to the full run' } else { 'CHANGED' })
}

"=== 4. --scale 0.1 again: the same database"
Generate "$S\scale_small2.log" @('--seed', '7', '--end-date', $END, '--scale', '0.1')
Fingerprint "$S\fp_small2.txt" | Out-Null
"  two runs at the same scale: " +
    $(if ((Get-FileHash "$S\fp_small.txt").Hash -eq (Get-FileHash "$S\fp_small2.txt").Hash) { 'identical' } else { 'DIFFERENT' })

"=== 5. --scale 2: twice the orders"
Generate "$S\scale_big.log" @('--seed', '7', '--end-date', $END, '--scale', '2')
Fingerprint "$S\fp_big.txt" | Out-Null
Rules '2' ($REVIEWS * 2)
"  order ids are contiguous from 1: " +
    (Psql "SELECT count(*) = max(order_id) AND min(order_id) = 1 FROM orders")
"  the catalogue and the people are untouched:"
foreach ($t in 'product', 'review', 'customer', 'shipping_details') {
    "    $t " + $(if ((Md5 "$S\fp_big.txt" $t) -eq (Md5 "$S\fp_none.txt" $t)) { 'identical to the full run' } else { 'CHANGED' })
}

"=== 6. the storefront checks out on a scaled database"
Dc up -d storefront-api | ForEach-Object { "  $_" }
$health = ''
for ($i = 0; $i -lt 60; $i++) {
    $health = docker inspect -f "{{.State.Health.Status}}" am-scale-storefront-api-1 2>$null
    if ($health -eq 'healthy') { break }
    Start-Sleep -Seconds 2
}
"  api health: $health"
"  next order id: " + (Psql "SELECT last_value + 1 FROM orders_order_id_seq")

"=== 7. a bad scale is refused"
docker compose --profile build run --rm generate-history --seed 7 --end-date $END --scale 0 2>&1 |
    ForEach-Object { "$_" } | Select-String -Pattern 'scale must' | ForEach-Object { "  $_" }

"=== 8. tear down"
Dc --profile build down -v
"done"

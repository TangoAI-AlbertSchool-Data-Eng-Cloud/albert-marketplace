# Step 8: the release. Packages the assets, then starts a stack from scratch that
# seeds itself from them, in its own project. Needs data/release built first:
#   docker compose --profile build run --rm release
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:COMPOSE_PROJECT_NAME = 'am-step8'
$env:DB_PORT = '55438'
$env:API_PORT = '18108'
$env:UI_PORT = '18518'
$env:SEED_URL = ''                      # never download: the local build is the asset
$env:RELEASE_DIR = "$repo\data\release"
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Stopping|Stopped|Removing|Removed|Recreate|Recreated)|(Volume|Network) .* (Creating|Created|Removing|Removed)|^\s*$'
function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }
function Psql([string]$sql) { (docker compose exec -T db psql -U postgres -d marketplace -At -c $sql 2>&1 | ForEach-Object { "$_" }) -join "`n" }

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    "Docker Desktop is not running: starting it"
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 90; $i++) { Start-Sleep -Seconds 3; docker info --format "{{.ServerVersion}}" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { break } }
}
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { "ABORT: Docker is still not reachable"; exit 1 }
if (-not (Test-Path "$env:RELEASE_DIR\marketplace.dump")) { "ABORT: no release in $env:RELEASE_DIR"; exit 1 }

"=== 0. the release assets"
Get-ChildItem $env:RELEASE_DIR | ForEach-Object { "  {0,-20} {1,10:N0} bytes" -f $_.Name, $_.Length }
$manifest = Get-Content "$env:RELEASE_DIR\MANIFEST.json" -Raw | ConvertFrom-Json
"  version $($manifest.version), seed $($manifest.seed), end date $($manifest.end_date), built $($manifest.built_at)"
"  GitHub's limit is 2 GiB per asset; largest here: {0:N0} MB" -f ((Get-ChildItem $env:RELEASE_DIR | Measure-Object Length -Maximum).Maximum / 1MB)

"=== 1. CHECKSUMS match the files"
docker run --rm -v "${env:RELEASE_DIR}:/r:ro" -w /r postgres:17.11 sha256sum --check CHECKSUMS 2>&1 | ForEach-Object { "  $_" }

"=== 2. cold start: an empty volume seeds itself from the release"
Dc --profile build down -v
$t = Measure-Command { Dc up -d db seed migrate storefront-api storefront-ui | ForEach-Object { "  $_" } }
"  up took $([int]$t.TotalSeconds) s"
"  seed:    " + (docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" am-step8-seed-1 2>$null)
"  migrate: " + (docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" am-step8-migrate-1 2>$null)
(docker logs am-step8-seed-1 2>&1 | ForEach-Object { "$_" }) | Select-Object -Last 3 | ForEach-Object { "  seed says: $_" }

"=== 3. every table holds what MANIFEST.json says"
$bad = 0
foreach ($p in $manifest.rows.PSObject.Properties) {
    $n = [int](Psql "SELECT count(*) FROM $($p.Name)")
    if ($n -ne $p.Value) { "  MISMATCH {0}: {1} restored, {2} in the manifest" -f $p.Name, $n, $p.Value; $bad++ }
}
"  {0} tables checked, {1} mismatched" -f @($manifest.rows.PSObject.Properties).Count, $bad
"  revenue: " + (Psql "SELECT sum(amount) FROM payment") + " (manifest $($manifest.revenue_eur))"
"  orders:  " + (Psql "SELECT min(order_date) || ' to ' || max(order_date) FROM orders") +
    " (manifest $($manifest.first_order_date) to $($manifest.last_order_date))"

"=== 4. the restore did not fire the stock trigger"
"  stock units: " + (Psql "SELECT sum(qty) FROM product") + " (manifest $($manifest.stock_units))"
"  trigger enabled again: " + (Psql "SELECT tgenabled FROM pg_trigger WHERE tgname = 'trg_update_inventory'")

"=== 5. the migrations are recorded as applied, and add nothing"
"  schema_migrations: " + ((Psql "SELECT version FROM schema_migrations ORDER BY version") -replace "`n", ', ')
"  identity sequence, next order id: " + (Psql "SELECT last_value + 1 FROM orders_order_id_seq")
$again = (Dc run --rm migrate) -join "`n"
"  a second dbmate run: " + ($again -replace "`n", ' | ')

"=== 6. the storefront runs on the restored data"
$health = ''
for ($i = 0; $i -lt 60; $i++) {
    $health = docker inspect -f "{{.State.Health.Status}}" am-step8-storefront-api-1 2>$null
    if ($health -eq 'healthy') { break }
    Start-Sleep -Seconds 2
}
"  api health: $health"
$buyer = Psql "SELECT buyer_id FROM orders ORDER BY order_id DESC LIMIT 1"
try {
    $products = Invoke-RestMethod "http://localhost:$($env:API_PORT)/products?limit=3"
    "  GET /products: $($products.Count) products, first '$($products[0].p_name)' at EUR $($products[0].price)"
    $history = Invoke-RestMethod "http://localhost:$($env:API_PORT)/orders/$buyer"
    "  GET /orders/{buyer}: $($history.Count) orders, latest EUR $($history[0].payment.amount) by $($history[0].payment.method)"
} catch { "  API FAILED: $($_.Exception.Message)" }

"=== 7. a restart seeds nothing and changes nothing"
$before = Psql "SELECT count(*) FROM orders"
Dc up -d --force-recreate seed | ForEach-Object { "  $_" }
for ($i = 0; $i -lt 30; $i++) { if ((docker inspect -f "{{.State.Status}}" am-step8-seed-1 2>$null) -eq 'exited') { break }; Start-Sleep -Seconds 2 }
(docker logs am-step8-seed-1 2>&1 | ForEach-Object { "$_" }) | Select-Object -Last 2 | ForEach-Object { "  seed says: $_" }
"  orders before $before, after " + (Psql "SELECT count(*) FROM orders")

"=== 8. the CSV export: the index column, the row counts, the phone defect"
$csv = "$S\csvcheck"
Remove-Item -Recurse -Force $csv -ErrorAction SilentlyContinue
New-Item -ItemType Directory $csv | Out-Null
docker run --rm -v "${env:RELEASE_DIR}:/r:ro" -v "${csv}:/out" postgres:17.11 `
    bash -c 'tar -xzf /r/legacy_csv.tar.gz -C /out --strip-components=1 legacy_csv/customer.csv legacy_csv/product.csv legacy_csv/orders.csv legacy_csv/order_items.csv legacy_csv/payment_details.csv' 2>&1 | ForEach-Object { "  $_" }
foreach ($f in 'customer', 'product', 'orders', 'order_items', 'payment_details') {
    $head = (Get-Content "$csv\$f.csv" -TotalCount 1)
    $rows = (Get-Content "$csv\$f.csv" | Measure-Object -Line).Lines - 1   # text fields hold newlines: only a lower bound
    "  {0,-16} header '{1}'" -f $f, ($head.Substring(0, [Math]::Min(60, $head.Length)))
}
$customers = Get-Content "$csv\customer.csv" | Select-Object -Skip 1 |
    ConvertFrom-Csv -Header 'idx', 'c_id', 'fname', 'lname', 'phone', 'email', 'pwd'
"  customer.csv: {0} rows, index column 0..{1}" -f $customers.Count, $customers[-1].idx
"  phones starting with 0, in the CSV {0}, in the database {1} (France, Germany, the Netherlands, Belgium)" -f
    ($customers | Where-Object { $_.phone -like '0*' }).Count, (Psql "SELECT count(*) FROM customer WHERE phone LIKE '0%'")
"  every phone is text of 9 to 12 characters: " + (($customers | Where-Object { $_.phone.Length -lt 9 -or $_.phone.Length -gt 12 }).Count -eq 0)
"  pandas' read_csv defaults would read them as integers and drop that zero (the defect)"
"  passwords in plain text: " + ($customers | Where-Object { $_.pwd } ).Count
$cards = Get-Content "$csv\payment_details.csv" | Select-Object -Skip 1 |
    ConvertFrom-Csv -Header 'idx', 'payment_id', 'card_no', 'cvv', 'expiry_date', 'billing_address'
"  CVVs in the export: {0}, of which {1} have fewer than 3 digits (the dropped zeros)" -f
    $cards.Count, ($cards | Where-Object { $_.cvv.Length -lt 3 }).Count

"=== 9. the CSV export is byte-identical on a second build"
$second = "$S\release2"
Remove-Item -Recurse -Force $second -ErrorAction SilentlyContinue
New-Item -ItemType Directory $second | Out-Null
$env:RELEASE_DIR = $second
Dc --profile build run --rm release | Select-String -Pattern 'release v|^Checksums' | ForEach-Object { "  $_" }
$env:RELEASE_DIR = "$repo\data\release"
$a = (Get-Content "$repo\data\release\CHECKSUMS") -replace '\s+.*', ''
$b = (Get-Content "$second\CHECKSUMS") -replace '\s+.*', ''
$names = (Get-Content "$repo\data\release\CHECKSUMS") -replace '^\S+\s+', ''
for ($i = 0; $i -lt $names.Count; $i++) {
    "  {0,-20} {1}" -f $names[$i], $(if ($a[$i] -eq $b[$i]) { 'identical' } else { 'differs' })
}
"  (marketplace.dump and MANIFEST.json differ on purpose: both record when they were made)"

"=== 10. without a dump, the stack still starts, empty"
$env:COMPOSE_PROJECT_NAME = 'am-step8b'
$env:DB_PORT = '55439'; $env:API_PORT = '18109'; $env:UI_PORT = '18519'
$empty = "$S\noseed"
Remove-Item -Recurse -Force $empty -ErrorAction SilentlyContinue
New-Item -ItemType Directory $empty | Out-Null
$env:RELEASE_DIR = $empty
Dc --profile build down -v
Dc up -d db seed migrate storefront-api | ForEach-Object { "  $_" }
(docker logs am-step8b-seed-1 2>&1 | ForEach-Object { "$_" }) | Select-Object -Last 3 | ForEach-Object { "  seed says: $_" }
"  migrate: " + (docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" am-step8b-migrate-1 2>$null)
"  tables created: " + (Psql "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
"  orders: " + (Psql "SELECT count(*) FROM orders")
$health = ''
for ($i = 0; $i -lt 60; $i++) {
    $health = docker inspect -f "{{.State.Health.Status}}" am-step8b-storefront-api-1 2>$null
    if ($health -eq 'healthy') { break }
    Start-Sleep -Seconds 2
}
"  api health on an empty database: $health"

"=== 11. tear down"
Dc --profile build down -v
$env:COMPOSE_PROJECT_NAME = 'am-step8'
$env:RELEASE_DIR = "$repo\data\release"
Dc --profile build down -v
Remove-Item -Recurse -Force $csv, $second, $empty -ErrorAction SilentlyContinue
"done"

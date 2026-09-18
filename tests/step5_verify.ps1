# Step 5: verify the history generator, with localisation, in its own compose project.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:COMPOSE_PROJECT_NAME = 'am-step5'
$env:DB_PORT = '55432'
if (-not $env:LEGACY_CSV_DIR) { $env:LEGACY_CSV_DIR = 'C:/Users/charl/Documents/Work/ALBERT_SCHOOL/TANGOAI_EDUCATION_assets/datasets/Amazon/Amazon_tx_database_files' }
$END = '2026-09-15'
# Seed 7 and this end date, before localisation (previous verified run)
$HISTORY = @{
    'carrier'     = '8e2337035c873956873605d9bdb532e5'
    'order_items' = 'd60c31ed4dbe90e438a11a30173f3101'
    'orders'      = 'e32489b4cb3402408f3805b605807a87'
    'payment'     = '274263691c7b793d69f627376669ea43'
    'shipment'    = '9add676db367490257494e8cc3a688b9'
}
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Stopping|Stopped|Removing|Removed|Recreate|Recreated)|(Volume|Network) .* (Creating|Created|Removing|Removed)|^\s*$'
function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }
function Generate([string]$Log, [string[]]$GenArgs) {
    $t = Measure-Command { docker compose --profile build run --rm generate-history @GenArgs 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 $Log }
    $code = $LASTEXITCODE
    "generate $($GenArgs -join ' ') -> exit=$code in $([int]$t.TotalSeconds) s"
    Get-Content $Log | Select-String -NotMatch $noise | Select-String -NotMatch 'Using CPython|virtual environment|Installed \d+ packages|Download' | ForEach-Object { "  $_" }
    if ($code -ne 0) {
        "ABORT: generation failed. load-legacy log:"
        docker compose logs --no-color load-legacy 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern 'ERROR|error|DETAIL|HINT' | Select-Object -Last 10 | ForEach-Object { "  $_" }
        Dc --profile build down -v
        exit 1
    }
}
function Fingerprint([string]$Out) {
    docker compose exec -T db psql -U postgres -d marketplace -XAt -f /tmp/fp.sql 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 $Out
    $lines = @(Get-Content $Out | Where-Object { $_ -match '^\w+\|\d+\|[0-9a-f]{32}$' })
    "fingerprint: $($lines.Count) tables -> " + (Get-FileHash $Out).Hash.Substring(0, 16)
}
function Same([string]$A, [string]$B) {
    $la = @(Get-Content $A | Where-Object { $_ -match '^\w+\|\d+\|[0-9a-f]{32}$' }).Count
    if ($la -lt 27) { return "FAILED: incomplete fingerprint ($la tables)" }
    if ((Get-FileHash $A).Hash -eq (Get-FileHash $B).Hash) { return "identical" }
    return "different: " + ((Compare-Object (Get-Content $A) (Get-Content $B) | Where-Object SideIndicator -eq '=>' | ForEach-Object { ($_.InputObject -split '\|')[0] }) -join ', ')
}

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    "Docker Desktop is not running: starting it"
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 90; $i++) { Start-Sleep -Seconds 3; docker info --format "{{.ServerVersion}}" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { break } }
}
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { "ABORT: Docker is still not reachable"; exit 1 }

"=== 0. build the GeoNames snapshot"
$t = Measure-Command { docker compose --profile build run --rm fetch-places 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 "$S\places.log" }
"fetch-places exit=$LASTEXITCODE in $([int]$t.TotalSeconds) s"
Get-Content "$S\places.log" | Select-String -NotMatch $noise | Select-String -NotMatch 'Using CPython|virtual environment|Installed \d+ packages|Download' | ForEach-Object { "  $_" }
if (-not (Test-Path generators\history\places.json)) { "ABORT: no places.json"; exit 1 }
"places.json: " + (Get-Item generators\history\places.json).Length + " bytes, " + (Get-Content generators\history\places.json).Count + " lines"

"=== 1. cold start"
Dc --profile build down -v
Dc up -d
$st = ''
for ($i = 0; $i -lt 60; $i++) {
    $st = docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" am-step5-migrate-1 2>$null
    if ($st -like 'exited*') { break }
    Start-Sleep -Seconds 2
}
"migrate: $st"
if ($st -ne 'exited exit=0') { "ABORT: migrations did not complete"; Dc logs --no-color migrate; exit 1 }
Dc cp "$S\step3_fingerprint.sql" db:/tmp/fp.sql

"=== 2. generate (seed 7, end $END), twice"
Generate "$S\gen1.log" @('--seed', '7', '--end-date', $END)
Fingerprint "$S\gen1.txt"
Generate "$S\gen2.log" @('--seed', '7', '--end-date', $END)
Fingerprint "$S\gen2.txt"
"same seed and end date: " + (Same "$S\gen1.txt" "$S\gen2.txt")
foreach ($table in $HISTORY.Keys | Sort-Object) {
    $line = Get-Content "$S\gen1.txt" | Where-Object { $_ -like "$table|*" }
    $md5 = ($line -split '\|')[2]
    "  $table unchanged by localisation: " + $(if ($md5 -eq $HISTORY[$table]) { 'yes' } else { "NO ($md5)" })
}
Get-Content "$S\gen1.txt" | Select-String '^(customer|shipping_details|payment_details|customer_shipping|customer_payment)\|' | ForEach-Object { "  $_" }

"=== 3. history checks"
Dc cp "$S\step5_checks.sql" db:/tmp/step5_checks.sql
docker compose exec -T db sh -c "psql -U postgres -d marketplace -X -v end=$END -f /tmp/step5_checks.sql 2>&1" | Select-String -Pattern '^===|mismatch|without|missing|zero|lines_on|paid_on|min|delivered|in_transit|processing|^\s+[0-9]' | ForEach-Object { "$_" }

"=== 4. against the calibration"
$env:PYTHONIOENCODING = 'utf-8'
python "$S\step5_validate.py" $END

"=== 5. localisation"
python "$S\step5_places_validate.py"

"=== 6. storefront checkout on the generated database"
docker compose run --rm -v "${S}:/scratch:ro" --entrypoint python storefront-api /scratch/step5_storefront.py 2>&1 | ForEach-Object { "$_" } | Select-String -Pattern '^\s+\(|saved card'

"=== 7. another seed differs; the default end date is today"
Generate "$S\gen3.log" @('--seed', '8', '--end-date', $END)
Fingerprint "$S\gen3.txt"
"seed 8 vs seed 7: " + (Same "$S\gen1.txt" "$S\gen3.txt")
Generate "$S\gen4.log" @('--seed', '7')

"=== 8. footprint"
docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}" | Select-String 'am-step5'
docker compose exec -T db sh -c "psql -U postgres -d marketplace -XAt -c 'SELECT pg_size_pretty(pg_database_size(current_database()))'; du -sh /var/lib/postgresql/data"

"=== 9. tear down"
Dc --profile build down -v

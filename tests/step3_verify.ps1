# Step 3: verify the legacy loader on a fresh database, in its own compose
# project and port so a stack started with `docker compose up` is left alone.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
$csvDir = 'C:/Users/charl/Documents/Work/ALBERT_SCHOOL/TANGOAI_EDUCATION_assets/datasets/Amazon/Amazon_tx_database_files'
Set-Location $repo
$env:COMPOSE_PROJECT_NAME = 'am-step3'
$env:DB_PORT = '55432'
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Recreate|Recreated)|^\s*$'

function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }
function Load([string]$Dir, [string]$Log, [string[]]$Extra = @()) {
    $env:LEGACY_CSV_DIR = $Dir
    $t = Measure-Command { docker compose --profile build run --rm @Extra load-legacy 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 $Log }
    $code = $LASTEXITCODE
    Remove-Item Env:LEGACY_CSV_DIR
    "load exit=$code in $([int]$t.TotalSeconds) s"
    Get-Content $Log | Select-String -NotMatch $noise | ForEach-Object { "  $_" }
}
function Fingerprint([string]$Out) {
    docker compose exec -T db psql -U postgres -d marketplace -XAt -f /tmp/fp.sql 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 $Out
}
function SameAs1([string]$Other, [string]$Label) {
    $a = @(Get-Content "$S\fp1.txt" | Where-Object { $_ -match '^\w+\|\d+\|[0-9a-f]{32}$' })
    $b = @(Get-Content $Other | Where-Object { $_ -match '^\w+\|\d+\|[0-9a-f]{32}$' })
    if ($a.Count -lt 26 -or $b.Count -lt 26) {
        "FAILED: a fingerprint is incomplete ($($a.Count) and $($b.Count) table lines, expected 26)"
    } elseif ((Get-FileHash "$S\fp1.txt").Hash -eq (Get-FileHash $Other).Hash) {
        $Label
    } else {
        "FAILED: fingerprints differ"
        Compare-Object (Get-Content "$S\fp1.txt") (Get-Content $Other)
    }
}

"=== 0. Docker, other stacks, compose without LEGACY_CSV_DIR"
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    "Docker Desktop is not running: starting it"
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 3
        docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { break }
    }
}
$server = docker info --format "{{.ServerVersion}}" 2>$null
if ($LASTEXITCODE -ne 0) { "ABORT: Docker is still not reachable"; exit 1 }
"docker server $server"
docker ps --format "{{.Names}}" | Select-String 'albert-marketplace' | ForEach-Object { "running already (left alone): $_" }
Remove-Item Env:LEGACY_CSV_DIR -ErrorAction SilentlyContinue
"default services: " + ((docker compose config --services 2>&1) -join ', ')
"with --profile build: " + ((docker compose --profile build config --services 2>&1) -join ', ')

"=== 1. fresh database"
Dc down -v
Dc up -d
$st = ''
for ($i = 0; $i -lt 60; $i++) {
    $st = docker inspect -f "{{.State.Status}} exit={{.State.ExitCode}}" am-step3-migrate-1 2>$null
    if ($st -like 'exited*') { break }
    Start-Sleep -Seconds 2
}
"migrate: $st"
if ($st -ne 'exited exit=0') { "ABORT: migrations did not complete"; Dc logs --no-color; exit 1 }
Dc cp "$S\step3_fingerprint.sql" db:/tmp/fp.sql

"=== 2. first load"
Load $csvDir "$S\load1.log"
Fingerprint "$S\fp1.txt"

"=== 3. second load: identical database?"
Load $csvDir "$S\load2.log"
Fingerprint "$S\fp2.txt"
SameAs1 "$S\fp2.txt" 'fingerprints identical'
Get-Content "$S\fp1.txt"

"=== 4. a load that fails (empty CSV folder) leaves the database as it was"
New-Item -ItemType Directory -Force "$S\empty_csv" | Out-Null
Load (($S -replace '\\', '/') + '/empty_csv') "$S\load_fail.log"
Fingerprint "$S\fp3.txt"
SameAs1 "$S\fp3.txt" 'fingerprint unchanged after the failed load'

"=== 5. the loader with Windows line endings, as a Windows checkout has it"
New-Item -ItemType Directory -Force "$S\crlf" | Out-Null
$text = [IO.File]::ReadAllText("$repo\db\load_legacy.sql") -replace "`r?`n", "`r`n"
[IO.File]::WriteAllText("$S\crlf\load_legacy.sql", $text)
"CR bytes in the copy: " + ([regex]::Matches($text, "`r")).Count
Load $csvDir "$S\load_crlf.log" @('-v', (($S -replace '\\', '/') + '/crlf:/crlf:ro'), '--entrypoint', 'psql --no-psqlrc --file /crlf/load_legacy.sql')
Fingerprint "$S\fp4.txt"
SameAs1 "$S\fp4.txt" 'fingerprint identical with CRLF line endings'

"=== 6. checks"
Dc cp "$S\step3_checks.sql" db:/tmp/step3_checks.sql
docker compose exec -T db sh -c "psql -U postgres -d marketplace -X -f /tmp/step3_checks.sql 2>&1"

"=== 7. values against the CSVs"
$env:PYTHONIOENCODING = 'utf-8'
python "$S\step3_fidelity.py" $csvDir

"=== 8. footprint"
docker stats --no-stream --format "{{.Name}}\t{{.MemUsage}}" | Select-String 'am-step3'
docker compose exec -T db du -sh /var/lib/postgresql/data

"=== 9. tear down the verification project"
Dc down -v

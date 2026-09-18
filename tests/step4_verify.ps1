# Step 4: lock the generators project, run the calibration twice, validate it.
$ErrorActionPreference = 'Continue'
$S = $PSScriptRoot
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
# Its own compose project and port, so a stack started with `docker compose up` is untouched
$env:COMPOSE_PROJECT_NAME = 'am-step4'
$env:DB_PORT = '55432'
$env:RETAIL_XLSX_DIR = 'C:/Users/charl/Documents/Work/ALBERT_SCHOOL/TANGOAI_EDUCATION_assets/datasets/online_retail_II'
$noise = 'Container .* (Creating|Created|Running|Waiting|Healthy|Starting|Started|Exited|Recreate|Recreated)|Volume .* (Creating|Created)|^\s*$'
function Dc { docker compose @args 2>&1 | ForEach-Object { "$_" } | Select-String -NotMatch $noise | ForEach-Object { "$_" } }

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    "Docker Desktop is not running: starting it"
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    for ($i = 0; $i -lt 90; $i++) { Start-Sleep -Seconds 3; docker info --format "{{.ServerVersion}}" 2>$null | Out-Null; if ($LASTEXITCODE -eq 0) { break } }
}
docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { "ABORT: Docker is still not reachable"; exit 1 }

"=== 0. services"
"default: " + ((docker compose config --services 2>&1) -join ', ')
"--profile build: " + ((docker compose --profile build config --services 2>&1) -join ', ')

"=== 1. lock the generators project"
Dc --profile build run --rm calibrate uv lock
if (-not (Test-Path generators\uv.lock)) { "ABORT: no uv.lock"; exit 1 }
Select-String -Path generators\uv.lock -Pattern '^name = "(pandas|python-calamine|numpy)"' -Context 0, 1 | ForEach-Object { ($_.Line + ' ' + $_.Context.PostContext[0]).Trim() }

"=== 2. calibrate, twice"
foreach ($run in 1, 2) {
    $t = Measure-Command { docker compose --profile build run --rm calibrate 2>&1 | ForEach-Object { "$_" } | Out-File -Encoding utf8 "$S\cal$run.log" }
    "run $run exit=$LASTEXITCODE in $([int]$t.TotalSeconds) s"
    Get-Content "$S\cal$run.log" | Select-String -NotMatch $noise | ForEach-Object { "  $_" }
    Copy-Item generators\history\calibration.json "$S\cal$run.json"
    "  sha256 " + (Get-FileHash generators\history\calibration.json -Algorithm SHA256).Hash
}
if ((Get-FileHash "$S\cal1.json").Hash -eq (Get-FileHash "$S\cal2.json").Hash) { "byte-identical across runs" } else { "FAILED: runs differ" }

"=== 3. the lock is stable"
Dc --profile build run --rm calibrate uv lock --locked
"uv lock --locked exit=$LASTEXITCODE"

"=== 4. validate against build-spec §5.4"
$env:PYTHONIOENCODING = 'utf-8'
python "$S\step4_validate.py" generators\history\calibration.json
"lines in calibration.json: " + (Get-Content generators\history\calibration.json).Count

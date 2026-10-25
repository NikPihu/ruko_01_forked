# Start the whole RUKO demo stack on Windows and connect the phone to it.
#
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1            # start everything (after every git pull too)
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Regenerate # rebuild data first
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -Stop       # stop the services
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -NoBait     # skip the task-scam bait account
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1 -BuildConsole # force a console rebuild
#
# Steps: venv + requirements, synthetic data (if missing), the analyst console (rebuilt when its
# source changed), mock intel on 8001, risk API (--demo-clock --lab --seed-demo: the demo agents
# fill the console once at startup), mule pump, bait pump, adb reverse so the phone's
# http://127.0.0.1:8000/ reaches the API, and the demo users' contacts on the emulator.
# If port 8000 is taken on the laptop, the API moves to the next free port and adb reverse maps
# phone 8000 to it.

param(
    [int]$ApiPort = 8000,
    [int]$IntelPort = 8001,
    [int]$Payers = 40,
    [switch]$Regenerate,
    [switch]$NoPump,
    [switch]$BaitPump,   # kept for old commands: the bait pump now runs by default
    [switch]$NoBait,
    [switch]$BuildConsole,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$Logs = Join-Path $Root "logs"
$PidFile = Join-Path $Logs "dev.pids"
New-Item -ItemType Directory -Force $Logs | Out-Null

function Stop-Stack {
    if (Test-Path $PidFile) {
        foreach ($id in Get-Content $PidFile) {
            try { Stop-Process -Id ([int]$id) -Force -ErrorAction Stop; Write-Host "stopped $id" } catch {}
        }
        Remove-Item $PidFile
    }
}

if ($Stop) { Stop-Stack; exit 0 }
Stop-Stack

function Test-PortFree([int]$port) {
    $l = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return -not $l
}

function Wait-Health([string]$url, [int]$seconds = 30) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        try { return Invoke-RestMethod -Uri $url -TimeoutSec 2 } catch { Start-Sleep -Milliseconds 500 }
    }
    throw "no answer from $url after $seconds s (see logs\*.log)"
}

# 1. Python venv
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "creating .venv"
    python -m venv .venv
    & $Py -m pip install -q -r backend\requirements.txt
}
# The API scores with the trained model (ml/model/predict.py), which needs LightGBM; without it the
# API falls back to the rules. ml\requirements.txt includes backend\requirements.txt.
# Run every time (quick when nothing changed), so a pull that adds a package just works.
Write-Host "checking Python packages"
& $Py -m pip install -q --disable-pip-version-check -r ml\requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install -r ml\requirements.txt failed" }
$env:PYTHONPATH = "backend;ml;data"
$env:PYTHONIOENCODING = "utf-8"

# 2. Synthetic world (data\*.parquet is git ignored)
if ($Regenerate -or -not (Test-Path "data\ledger.parquet")) {
    Write-Host "generating data"
    & $Py -m sim.generate --users 2000 --days 30 --seed 7 --out data/
    if ($LASTEXITCODE -ne 0) { throw "sim.generate failed" }
}

# 2b. Analyst console (console\dist is git ignored; the API serves it at /console/)
# console\dist is not in git, so after a pull it is rebuilt whenever any console source is newer.
$consoleStale = -not (Test-Path "console\dist\index.html")
if (-not $consoleStale) {
    $built = (Get-Item "console\dist\index.html").LastWriteTime
    $newer = Get-ChildItem console\src, console\index.html, console\package.json -Recurse -File |
        Where-Object { $_.LastWriteTime -gt $built } | Select-Object -First 1
    $consoleStale = [bool]$newer
}
if ($BuildConsole -or $consoleStale) {
    if (Get-Command npm -ErrorAction SilentlyContinue) {
        Write-Host "building the analyst console"
        Push-Location console
        try {
            $lockNewer = (Test-Path "node_modules") -and (Test-Path "package-lock.json") -and
                ((Get-Item "package-lock.json").LastWriteTime -gt (Get-Item "node_modules").LastWriteTime)
            if (-not (Test-Path "node_modules") -or $lockNewer) { npm install --no-audit --no-fund | Out-Null }
            npm run build | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Host "console build failed; the API still runs without it" }
        } finally { Pop-Location }
    } else {
        Write-Host "npm not found; skipping the analyst console (install Node.js to get it)"
    }
}

# 3. Ports
if (-not (Test-PortFree $IntelPort)) { throw "port $IntelPort is taken; stop that process or pass -IntelPort" }
$phonePort = 8000
$wanted = $ApiPort
while ($ApiPort -eq $IntelPort -or -not (Test-PortFree $ApiPort)) { $ApiPort++ }
if ($ApiPort -ne $wanted) { Write-Host "port $wanted is taken, the API uses $ApiPort" }

# 4. Services
$intel = Start-Process -FilePath $Py -PassThru -WindowStyle Hidden `
    -ArgumentList "-m", "intel_mock.app", "--data", "data", "--port", "$IntelPort" `
    -RedirectStandardOutput "$Logs\intel.log" -RedirectStandardError "$Logs\intel.err.log"
$intel.Id | Out-File $PidFile -Encoding ascii
Wait-Health "http://127.0.0.1:$IntelPort/health" | Out-Null
Write-Host "mock intel up on $IntelPort"

$api = Start-Process -FilePath $Py -PassThru -WindowStyle Hidden `
    -ArgumentList "-m", "api.main", "--data", "data", "--port", "$ApiPort", `
                  "--intel", "http://127.0.0.1:$IntelPort", "--demo-clock", "--lab", "--seed-demo" `
    -RedirectStandardOutput "$Logs\api.log" -RedirectStandardError "$Logs\api.err.log"
$api.Id | Out-File $PidFile -Append -Encoding ascii
$health = Wait-Health "http://127.0.0.1:$ApiPort/health"
Write-Host "risk API up on $ApiPort ($($health | ConvertTo-Json -Compress))"

# 5. Mule pump, so the demo mule looks live to the bank features
if (-not $NoPump) {
    & $Py -m sim.mule_pump --url "http://127.0.0.1:$IntelPort" --payers $Payers
    if ($LASTEXITCODE -ne 0) { throw "sim.mule_pump failed" }
}

# 5b. Task-scam bait account fanning out to 40 users, for the payment graph demo (/console/graph)
if (-not $NoBait) {
    & $Py -m sim.bait_pump --api "http://127.0.0.1:$ApiPort" --intel "http://127.0.0.1:$IntelPort"
    if ($LASTEXITCODE -ne 0) { throw "sim.bait_pump failed" }
}

# 6. Phone
$Adb = Join-Path $env:LOCALAPPDATA "Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path $Adb)) { $Adb = (Get-Command adb -ErrorAction SilentlyContinue).Source }
if ($Adb) {
    $devices = & $Adb devices | Select-String "\tdevice$"
    if ($devices) {
        & $Adb reverse "tcp:$phonePort" "tcp:$ApiPort" | Out-Null
        Write-Host "phone: adb reverse tcp:$phonePort -> laptop tcp:$ApiPort"
        # The mock NPCI's UPI number mapper (mobile -> UPI ID), as a real PSP app would call it.
        & $Adb reverse "tcp:8001" "tcp:$IntelPort" | Out-Null
        Write-Host "phone: adb reverse tcp:8001 -> laptop tcp:$IntelPort (UPI number mapper)"
        # The demo users' address books (people really paid in the world, plus a few never paid),
        # on emulators only: never write into a real phone's contacts.
        if ($devices -match "emulator-") {
            foreach ($u in @("u_demo_meena", "u_001435")) {
                & $Py -m sim.contacts --data data --user $u --adb | Out-Null
            }
            Write-Host "phone: Meena's and Rahul's contacts are in the emulator's Contacts"
        }
    } else {
        Write-Host "no phone or emulator connected; run later: adb reverse tcp:$phonePort tcp:$ApiPort"
    }
} else {
    Write-Host "adb not found; run later: adb reverse tcp:$phonePort tcp:$ApiPort"
}

Write-Host ""
Write-Host "Ready. In Cache Pay tap 'Check Scam Shield' or long press the title for the debug panel."
if (Test-Path "console\dist\index.html") {
    Write-Host "Analyst console: http://127.0.0.1:$ApiPort/console/  (demo data fills it within ~30 s)"
    Write-Host "AI scammer page: http://127.0.0.1:$ApiPort/console/#/lab"
}
Write-Host "Logs: logs\api.log, logs\intel.log. Stop: scripts\dev.ps1 -Stop"

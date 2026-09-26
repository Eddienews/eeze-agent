<#
Eeze Agent - Windows installer / bootstrap (idempotent).

What it does:
  1. ensures the Python toolchain (installs uv if missing, via the official installer)
  2. installs project dependencies (uv sync), builds the screens (installs Node.js LTS via
     winget on a fresh machine) and installs ffmpeg via winget if missing (-NoTools skips)
  3. starts the background service (safe when already running)
  4. creates Desktop + Start Menu shortcuts
  5. registers autostart so routines fire without opening a terminal, plus a
     watchdog (Task Scheduler, every 10 min) that restarts the service if it died
  6. opens the setup wizard

Run it by double-clicking install.cmd in the repo root.
Running it again is also how you UPDATE: it re-syncs dependencies, rebuilds the screens
and restarts the service with the new code.
Flags: -NoBrowser -NoShortcuts -NoAutostart -NoUiBuild -NoTools
#>
param(
  [switch]$NoBrowser,
  [switch]$NoShortcuts,
  [switch]$NoAutostart,
  [switch]$NoUiBuild,
  [switch]$NoTools
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

function Say([string]$m)  { Write-Host "  $m" }
function Step([string]$m) { Write-Host "> $m" -ForegroundColor Cyan }
function Ok([string]$m)   { Write-Host "  [ok] $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }

Write-Host ""
Write-Host "Eeze Agent setup" -ForegroundColor Cyan
Write-Host "-----------------"

Step "Checking the Python toolchain (uv)"
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Say "uv not found - installing it (official installer)..."
  Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  $candidate = Join-Path $env:USERPROFILE ".local\bin"
  if (Test-Path $candidate) { $env:Path = "$candidate;$env:Path" }
  if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was installed but is not on PATH yet. Close this window and run install.cmd again."
  }
}
Ok ("uv " + ((& uv --version) -join " "))

# Stop a running service first: on Windows it keeps compiled packages (.pyd) locked, so an
# update of the dependencies would fail half-way. Running routines are not killed.
$prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
$null = & uv run --no-sync eeze api stop 2>&1
$ErrorActionPreference = $prev

Step "Installing dependencies (first run may download Python)"
& uv sync --quiet
if ($LASTEXITCODE -ne 0) {
  throw "uv sync failed (exit $LASTEXITCODE) - nothing was changed on the running setup. Close other Eeze windows and run install.cmd again."
}
Ok "dependencies ready"

function Update-PathFromSystem {
  # winget installs update the machine/user PATH, not this window's copy.
  $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $user = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$machine;$user;$env:Path"
}

function Install-WithWinget([string]$id, [string]$what) {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Warn "winget is not available - install $what yourself, then run install.cmd again"
    return $false
  }
  Say "installing $what (winget $id)..."
  $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  $null = & winget install --id $id -e --silent --accept-source-agreements --accept-package-agreements 2>&1
  $ErrorActionPreference = $prev
  Update-PathFromSystem
  return $true
}

$uiEntry = Join-Path $Repo "ui\dist\client\index.html"
if (-not $NoUiBuild) {
  Step "Building the app screens (ui/)"
  # A fresh download has no built screens: Node.js is needed once to build them.
  if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    $null = Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js (needed once to build the screens)"
  }
  if (Get-Command npm -ErrorAction SilentlyContinue) {
    # npm/uv write progress to stderr; under "Stop" Windows PowerShell would abort on it.
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    if (-not (Test-Path (Join-Path $Repo "ui\node_modules"))) {
      Say "downloading the screen components (first run only, a few minutes)..."
      Push-Location (Join-Path $Repo "ui")
      $null = & npm ci --no-audit --no-fund 2>&1
      Pop-Location
    }
    $ui = & uv run eeze ui build 2>&1 | Out-String
    $ErrorActionPreference = $prev
    if ($LASTEXITCODE -eq 0 -and (Test-Path $uiEntry)) { Ok "screens built" }
    elseif (Test-Path $uiEntry) { Warn "screen build failed - the previous build stays in use"; Say ($ui.Trim() -split "`n" | Select-Object -Last 5 | Out-String) }
    else { Warn "screen build failed"; Say ($ui.Trim() -split "`n" | Select-Object -Last 8 | Out-String) }
  }
}
if (-not (Test-Path $uiEntry)) {
  throw "The app screens are not built. Install Node.js LTS from https://nodejs.org, then run install.cmd again."
}

if (-not $NoTools) {
  Step "Checking media tools"
  # Video and photo missions use ffmpeg. Found on PATH, via EEZE_FFMPEG or in ~\tools\ffmpeg.
  $ffTools = Join-Path $env:USERPROFILE "tools\ffmpeg"
  if ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -or $env:EEZE_FFMPEG -or (Test-Path $ffTools)) {
    Ok "ffmpeg found"
  } elseif ((Install-WithWinget "Gyan.FFmpeg" "ffmpeg (video and photo missions)") -and (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Ok "ffmpeg installed"
  } else {
    Warn "ffmpeg not found - video/photo missions need it (https://ffmpeg.org); everything else works"
  }
  if (-not (Get-Command blender -ErrorAction SilentlyContinue) -and -not (Test-Path "$env:ProgramFiles\Blender Foundation")) {
    Say "Blender not found - only needed for 3D missions (https://www.blender.org)"
  }
}

Step "Starting the background service"
# (Stopped above, before the dependency sync, so the new code is what starts now.)
$start = & uv run eeze api start | Out-String
if ($start -match '"status":\s*"(started|already_running)"') {
  Ok "service is up on http://127.0.0.1:8765"
} else {
  Warn "service did not report readiness - check ~\.eeze\api.log"
}

if (-not $NoShortcuts) {
  Step "Creating shortcuts"
  $ws = New-Object -ComObject WScript.Shell
  $desktop = [Environment]::GetFolderPath("Desktop")
  $programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
  # "Eeze Agent" opens the dashboard already paired (`eeze open`: starts the service if it
  # is down, then a one-time code signs the browser in). No console window (pythonw).
  $pyOpen = Join-Path $Repo ".venv\Scripts\pythonw.exe"
  if (-not (Test-Path $pyOpen)) { $pyOpen = Join-Path $Repo ".venv\Scripts\python.exe" }
  $openArgs = "-c `"import os,sys; os.chdir(r'$Repo'); from eeze_agent.cli import main; sys.exit(main(['open']))`""
  foreach ($dir in @($desktop, $programs)) {
    if (Test-Path $dir) {
      $lnk = $ws.CreateShortcut((Join-Path $dir "Eeze Agent.lnk"))
      $lnk.TargetPath = $pyOpen
      $lnk.Arguments = $openArgs
      $lnk.WorkingDirectory = $Repo
      $lnk.Description = "Eeze Agent - open the dashboard"
      $lnk.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
      $lnk.Save()
    }
  }
  # "Eeze Agent - Update" re-runs this installer (pull in new code, rebuild the screens).
  if (Test-Path $programs) {
    $upd = $ws.CreateShortcut((Join-Path $programs "Eeze Agent - Update.lnk"))
    $upd.TargetPath = Join-Path $Repo "install.cmd"
    $upd.WorkingDirectory = $Repo
    $upd.Description = "Eeze Agent - install updates"
    $upd.IconLocation = "$env:SystemRoot\System32\shell32.dll,238"
    $upd.Save()
  }
  Ok "shortcuts ready: 'Eeze Agent' (Desktop + Start Menu) and 'Eeze Agent - Update' (Start Menu)"
}

if (-not $NoAutostart) {
  Step "Registering autostart (so routines fire)"
  $startup = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
  if (Test-Path $startup) {
    $lines = @(
      "@echo off",
      "rem Starts the Eeze background service (schedules). Created by scripts\install.ps1.",
      "cd /d `"$Repo`"",
      "`"$Repo\.venv\Scripts\python.exe`" -c `"import sys; from eeze_agent.cli import main; sys.exit(main(['api','start']))`" >nul 2>nul"
    )
    Set-Content -Path (Join-Path $startup "Eeze Agent service.cmd") -Value $lines -Encoding ASCII
    Ok "autostart registered (skip next time with -NoAutostart)"
  }
  # Watchdog: `api start` is idempotent (no-op while healthy), so running it every
  # 10 minutes brings a crashed/stopped service back without anyone noticing it died.
  $pyw = Join-Path $Repo ".venv\Scripts\pythonw.exe"
  if (-not (Test-Path $pyw)) { $pyw = Join-Path $Repo ".venv\Scripts\python.exe" }
  $cmd = "`"$pyw`" -c `"import os,sys; os.chdir(r'$Repo'); from eeze_agent.cli import main; sys.exit(main(['api','start']))`""
  try {
    & schtasks /Create /F /SC MINUTE /MO 10 /TN "Eeze Agent watchdog" /TR $cmd | Out-Null
    Ok "watchdog registered (Task Scheduler: 'Eeze Agent watchdog', every 10 min)"
  } catch {
    Warn "could not register the watchdog task - the service will only start at login"
  }
}

Step "Health check"
$healthy = $false
foreach ($i in 1..40) {
  try {
    $null = Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "http://127.0.0.1:8765/api/health"
    $healthy = $true; break
  } catch { Start-Sleep -Milliseconds 250 }
}
if ($healthy) { Ok "service responding" } else { Warn "service not responding yet" }

Write-Host ""
if (-not $NoBrowser) {
  # Open already paired (one-time code); fall back to the plain URL.
  $py = Join-Path $Repo ".venv\Scripts\python.exe"
  & $py -c "import os,sys; os.chdir(r'$Repo'); from eeze_agent.cli import main; sys.exit(main(['open','/setup']))" 2>$null
  if ($LASTEXITCODE -ne 0) { Start-Process "http://127.0.0.1:8765/setup" }
  Ok "opened Eeze in your browser"
} else {
  Say "Open http://127.0.0.1:8765/setup when ready."
}
Write-Host "Done - Eeze is ready." -ForegroundColor Green

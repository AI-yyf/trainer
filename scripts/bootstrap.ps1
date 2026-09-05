Param(
  [switch]$SkipExtension,
  [switch]$SkipWebview,
  [switch]$SkipServer,
  [switch]$UseUv,
  [switch]$Strict
)

$ErrorActionPreference = "Stop"

function Write-Section {
  param([string]$Message)
  Write-Host ""
  Write-Host "== $Message ==" -ForegroundColor Cyan
}

function Write-Status {
  param(
    [string]$Status,
    [string]$Message
  )

  $color = switch ($Status) {
    "OK" { "Green" }
    "SKIP" { "Yellow" }
    "WARN" { "Yellow" }
    default { "Red" }
  }

  Write-Host "[$Status] $Message" -ForegroundColor $color
}

function Test-Command {
  param([string]$Name)
  return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-PythonLauncher {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    return @{
      Path = $py.Source
      Args = @("-3")
    }
  }

  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    return @{
      Path = $python.Source
      Args = @()
    }
  }

  throw "Python 3.12+ is required but neither 'py' nor 'python' is available."
}

function Assert-LastExitCode {
  param([string]$Action)

  if ($LASTEXITCODE -ne 0) {
    throw "$Action failed with exit code $LASTEXITCODE."
  }
}

function Invoke-SystemPython {
  param([string[]]$Args)

  $launcher = Get-PythonLauncher
  & $launcher.Path @($launcher.Args + $Args)
}

function Get-PythonVersionText {
  $launcher = Get-PythonLauncher
  return (& $launcher.Path @($launcher.Args + @("--version")))
}

function Assert-PythonVersion {
  $versionText = Get-PythonVersionText
  if ($versionText -notmatch "Python\s+(\d+)\.(\d+)\.(\d+)") {
    throw "Unable to determine Python version from '$versionText'."
  }

  $major = [int]$Matches[1]
  $minor = [int]$Matches[2]
  if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 12)) {
    throw "Python 3.12+ is required. Found $versionText."
  }

  return $versionText
}

function Test-ServerPackageReady {
  return (Test-Path "server/app/main.py")
}

function Invoke-NpmInstall {
  param(
    [string]$Prefix,
    [string]$Label
  )

  if (-not (Test-Path (Join-Path $Prefix "package.json"))) {
    if ($Strict) {
      throw "$Label package.json is missing at $Prefix."
    }

    Write-Status "SKIP" "$Label manifest missing at $Prefix."
    return
  }

  Write-Status "OK" "Installing $Label dependencies"
  npm install --prefix $Prefix
  Assert-LastExitCode "$Label dependency install"
}

Write-Section "Environment"

if (-not (Test-Command "node")) {
  throw "Node.js is required."
}

if (-not (Test-Command "npm")) {
  throw "npm is required."
}

Write-Status "OK" "Node $(node --version)"
Write-Status "OK" "npm $(npm --version)"
Write-Status "OK" (Assert-PythonVersion)

Write-Section "Bootstrap"

if (-not $SkipExtension) {
  Invoke-NpmInstall -Prefix "extension" -Label "extension"
}

if (-not $SkipWebview) {
  Invoke-NpmInstall -Prefix "extension/webview" -Label "webview"
}

if (-not $SkipServer) {
  if (-not (Test-Path "server/pyproject.toml")) {
    if ($Strict) {
      throw "server/pyproject.toml is missing."
    }

    Write-Status "SKIP" "Server manifest missing."
  } elseif (-not (Test-ServerPackageReady)) {
    if ($Strict) {
      throw "Server package skeleton is incomplete. Add server/app/main.py before bootstrap."
    }

    Write-Status "SKIP" "Server package skeleton is incomplete; skipping Python environment install."
  } elseif ($UseUv -and (Test-Command "uv")) {
    Write-Status "OK" "Syncing server environment with uv"
    uv sync --project server --extra dev
    Assert-LastExitCode "uv sync"
  } else {
    if ($UseUv -and -not (Test-Command "uv")) {
      Write-Status "WARN" "uv was requested but is not installed; falling back to venv + pip."
    }

    if (-not (Test-Path "server/.venv")) {
      Write-Status "OK" "Creating server virtual environment"
      Invoke-SystemPython -Args @("-m", "venv", "server/.venv")
      Assert-LastExitCode "server virtual environment creation"
    }

    Write-Status "OK" "Installing server editable package"
    & "server/.venv/Scripts/python.exe" -m pip install -e "server[dev]"
    Assert-LastExitCode "server editable install"
  }
}

Write-Section "Done"
Write-Status "OK" "Bootstrap completed."

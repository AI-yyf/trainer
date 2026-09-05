Param(
  [switch]$SkipInstall,
  [switch]$StartSidecar,
  [switch]$UseUv,
  [switch]$AutoPort,
  [int]$Port = 8765,
  [string]$BindHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"

$extensionPortStart = 34891
$extensionPortEnd = 34911

function Assert-LastExitCode {
  param([string]$Action)

  if ($LASTEXITCODE -ne 0) {
    throw "$Action failed with exit code $LASTEXITCODE."
  }
}

function Test-AnySource {
  param([string]$Pattern)
  return $null -ne (
    Get-ChildItem -Path $Pattern -Recurse -File -ErrorAction SilentlyContinue |
      Select-Object -First 1
  )
}

function Test-PortAvailable {
  param(
    [string]$BindHost,
    [int]$BindPort
  )

  try {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($BindHost), $BindPort)
    $listener.Start()
    $listener.Stop()
    return $true
  } catch {
    return $false
  }
}

function Resolve-SidecarPort {
  param(
    [string]$TargetHost,
    [int]$PreferredPort,
    [switch]$PreferAuto
  )

  if (-not $PreferAuto) {
    return $PreferredPort
  }

  $candidatePorts = [System.Collections.Generic.List[int]]::new()
  $candidatePorts.Add($PreferredPort)
  foreach ($candidate in $extensionPortStart..$extensionPortEnd) {
    if ($candidate -ne $PreferredPort) {
      $candidatePorts.Add($candidate)
    }
  }

  foreach ($candidate in $candidatePorts) {
    if (Test-PortAvailable -BindHost $TargetHost -BindPort $candidate) {
      return $candidate
    }
  }

  throw "No available sidecar port found across $PreferredPort and ${extensionPortStart}-${extensionPortEnd}."
}

if (-not $SkipInstall) {
  powershell -ExecutionPolicy Bypass -File "scripts/bootstrap.ps1" -UseUv:$UseUv
  Assert-LastExitCode "bootstrap"
}

if (Test-Path "extension/webview/package.json") {
  npm run build --prefix extension/webview
  Assert-LastExitCode "webview build"
}

if (Test-AnySource "extension/src/*.ts") {
  npm run build --prefix extension
  Assert-LastExitCode "extension host build"
} else {
  Write-Host "Skipping extension host build: extension/src has not been populated yet." -ForegroundColor Yellow
}

if ($StartSidecar) {
  if (Test-Path "server/app/main.py") {
    if (Test-Path "server/.venv/Scripts/python.exe") {
      $resolvedPort = Resolve-SidecarPort -TargetHost $BindHost -PreferredPort $Port -PreferAuto:$AutoPort
      $env:TRAINER_PORT = [string]$resolvedPort
      Write-Host "Starting Trainer sidecar on ${BindHost}:$resolvedPort" -ForegroundColor Cyan
      & "server/.venv/Scripts/python.exe" "server/run_sidecar.py" --host $BindHost --port $resolvedPort --reload
      exit 0
    }

    Write-Host "Server package exists but server/.venv is missing. Run scripts/bootstrap.ps1 first." -ForegroundColor Yellow
  } else {
    Write-Host "Skipping sidecar launch: server/app/main.py has not been added yet." -ForegroundColor Yellow
  }
}

Write-Host "Start the sidecar with:"
Write-Host "server/.venv/Scripts/python.exe server/run_sidecar.py --host $BindHost --port $Port --reload"
Write-Host "Use -AutoPort to scan 8765 and the extension-managed range ${extensionPortStart}-${extensionPortEnd}."

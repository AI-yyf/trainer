Param(
  [int[]]$Port,
  [switch]$Strict,
  [switch]$ProviderSmoke,
  [switch]$TrainerTurnSmoke,
  [switch]$TrainingReturnSmoke,
  [string]$ProviderSmokeApiKey,
  [string]$ProviderSmokeBaseUrl,
  [string]$ProviderSmokeModel,
  [string]$ProviderSmokeProtocol,
  [string]$ProviderSmokeResponseLanguage,
  [string]$TrainerTurnSmokeSidecarUrl,
  [string]$TrainerTurnSmokeApiKey,
  [string]$TrainerTurnSmokeBaseUrl,
  [string]$TrainerTurnSmokeModel,
  [string]$TrainerTurnSmokeProtocol,
  [string]$TrainerTurnSmokeResponseLanguage,
  [string]$TrainingReturnSmokeSidecarUrl,
  [string]$TrainingReturnSmokeApiKey,
  [string]$TrainingReturnSmokeBaseUrl,
  [string]$TrainingReturnSmokeModel,
  [string]$TrainingReturnSmokeProtocol,
  [string]$TrainingReturnSmokeResponseLanguage
)

$ErrorActionPreference = "Stop"

$checks = [System.Collections.Generic.List[object]]::new()
$extensionPortStart = 34891
$extensionPortEnd = 34911

function Add-Check {
  param(
    [string]$Area,
    [string]$Status,
    [string]$Detail
  )

  $checks.Add([pscustomobject]@{
    Area = $Area
    Status = $Status
    Detail = $Detail
  })
}

function Test-Command {
  param([string]$Name)
  return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-AnySource {
  param([string]$Pattern)
  return $null -ne (
    Get-ChildItem -Path $Pattern -Recurse -File -ErrorAction SilentlyContinue |
      Select-Object -First 1
  )
}

function Invoke-NodeScript {
  param(
    [string]$ScriptPath,
    [hashtable]$Environment = @{}
  )

  $previousValues = @{}
  foreach ($key in $Environment.Keys) {
    $previousValues[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
    [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], "Process")
  }

  try {
    $output = & node $ScriptPath 2>&1
    $exitCode = $LASTEXITCODE
    if ($output) {
      Write-Host $output
    }
    return $exitCode
  } finally {
    foreach ($key in $Environment.Keys) {
      $previous = $previousValues[$key]
      [Environment]::SetEnvironmentVariable($key, $previous, "Process")
    }
  }
}

function Get-ProbePorts {
  param([int[]]$ExplicitPorts)

  if ($ExplicitPorts -and $ExplicitPorts.Count -gt 0) {
    return $ExplicitPorts
  }

  $ports = [System.Collections.Generic.List[int]]::new()
  $ports.Add(8765)
  foreach ($candidate in $extensionPortStart..$extensionPortEnd) {
    $ports.Add($candidate)
  }
  return $ports
}

Add-Check -Area "Node" -Status ($(if (Test-Command "node") { "ok" } else { "missing" })) -Detail ($(if (Test-Command "node") { node --version } else { "Node.js is not available." }))
Add-Check -Area "npm" -Status ($(if (Test-Command "npm") { "ok" } else { "missing" })) -Detail ($(if (Test-Command "npm") { npm --version } else { "npm is not available." }))
Add-Check -Area "Python" -Status ($(if ((Test-Command "py") -or (Test-Command "python")) { "ok" } else { "missing" })) -Detail ($(if (Test-Command "py") { & (Get-Command py).Source -3 --version } elseif (Test-Command "python") { python --version } else { "Python 3.12+ is not available." }))

Add-Check -Area "Root manifest" -Status ($(if (Test-Path "package.json") { "ok" } else { "missing" })) -Detail "package.json"
Add-Check -Area "Extension manifest" -Status ($(if (Test-Path "extension/package.json") { "ok" } else { "missing" })) -Detail "extension/package.json"
Add-Check -Area "Webview manifest" -Status ($(if (Test-Path "extension/webview/package.json") { "ok" } else { "missing" })) -Detail "extension/webview/package.json"
Add-Check -Area "Server manifest" -Status ($(if (Test-Path "server/pyproject.toml") { "ok" } else { "missing" })) -Detail "server/pyproject.toml"
Add-Check -Area "Shared protocol" -Status ($(if (Test-Path "shared/src/protocol.ts") { "ok" } else { "missing" })) -Detail "shared/src/protocol.ts"

Add-Check -Area "Extension host sources" -Status ($(if (Test-AnySource "extension/src/*.ts") { "ok" } else { "pending" })) -Detail "Expected TypeScript host sources under extension/src."
Add-Check -Area "Webview sources" -Status ($(if (Test-AnySource "extension/webview/src/*") { "ok" } else { "pending" })) -Detail "Expected webview app sources under extension/webview/src."
Add-Check -Area "Extension build output" -Status ($(if (Test-Path "extension/dist/extension/src/extension.js") { "ok" } else { "pending" })) -Detail "Expected built extension entrypoint at extension/dist/extension/src/extension.js."
Add-Check -Area "Webview build output" -Status ($(if (Test-Path "extension/webview/dist/index.html") { "ok" } else { "pending" })) -Detail "Expected bundled webview entrypoint at extension/webview/dist/index.html."
Add-Check -Area "Server package" -Status ($(if (Test-Path "server/app/main.py") { "ok" } else { "pending" })) -Detail "Expected FastAPI sidecar entrypoint at server/app/main.py."
Add-Check -Area "Server tests" -Status ($(if (Test-AnySource "server/tests/*.py") { "ok" } else { "pending" })) -Detail "Expected smoke or unit tests under server/tests."
Add-Check -Area "Server virtualenv" -Status ($(if (Test-Path "server/.venv/Scripts/python.exe") { "ok" } else { "pending" })) -Detail "Expected bootstrap-created interpreter at server/.venv/Scripts/python.exe."

if ($ProviderSmoke) {
  if (Test-Command "node") {
    $smokeApiKey = if ($ProviderSmokeApiKey) { $ProviderSmokeApiKey.Trim() } else { $env:TRAINER_PROVIDER_SMOKE_API_KEY }
    $smokeBaseUrl = if ($ProviderSmokeBaseUrl) { $ProviderSmokeBaseUrl.Trim() } else { $env:TRAINER_PROVIDER_SMOKE_BASE_URL }
    $smokeModel = if ($ProviderSmokeModel) { $ProviderSmokeModel.Trim() } else { $env:TRAINER_PROVIDER_SMOKE_MODEL }
    $smokeProtocol = if ($ProviderSmokeProtocol) { $ProviderSmokeProtocol.Trim() } else { $env:TRAINER_PROVIDER_SMOKE_PROTOCOL }
    $smokeResponseLanguage = if ($ProviderSmokeResponseLanguage) { $ProviderSmokeResponseLanguage.Trim() } else { $env:TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE }

    if (-not $smokeApiKey) {
      Add-Check -Area "Provider smoke" -Status "missing" -Detail "Pass -ProviderSmokeApiKey or set TRAINER_PROVIDER_SMOKE_API_KEY."
    } else {
      $providerSmokeEnv = @{
        TRAINER_PROVIDER_SMOKE_API_KEY = $smokeApiKey
      }
      if ($smokeBaseUrl) {
        $providerSmokeEnv.TRAINER_PROVIDER_SMOKE_BASE_URL = $smokeBaseUrl
      }
      if ($smokeModel) {
        $providerSmokeEnv.TRAINER_PROVIDER_SMOKE_MODEL = $smokeModel
      }
      if ($smokeProtocol) {
        $providerSmokeEnv.TRAINER_PROVIDER_SMOKE_PROTOCOL = $smokeProtocol
      }
      if ($smokeResponseLanguage) {
        $providerSmokeEnv.TRAINER_PROVIDER_SMOKE_RESPONSE_LANGUAGE = $smokeResponseLanguage
      }

      $providerSmokeExit = Invoke-NodeScript "scripts/provider-smoke.mjs" -Environment $providerSmokeEnv
      Add-Check -Area "Provider smoke" -Status ($(if ($providerSmokeExit -eq 0) { "ok" } else { "failed" })) -Detail "Live provider smoke via scripts/provider-smoke.mjs"
    }
  } else {
    Add-Check -Area "Provider smoke" -Status "missing" -Detail "Node.js is not available for provider smoke."
  }
}

$portsToCheck = Get-ProbePorts -ExplicitPorts $Port
$healthFound = $false

foreach ($candidatePort in $portsToCheck) {
  try {
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:$candidatePort/health" -UseBasicParsing -TimeoutSec 2
    Add-Check -Area "Sidecar health" -Status "ok" -Detail "HTTP $($health.StatusCode) from /health on port $candidatePort"
    $healthFound = $true
    break
  } catch {
  }
}

if (-not $healthFound) {
  $checkedPorts = ($portsToCheck | Select-Object -Unique) -join ", "
  Add-Check -Area "Sidecar health" -Status "pending" -Detail "No sidecar health endpoint answered on ports: $checkedPorts."
}

if ($TrainerTurnSmoke) {
  if (-not (Test-Command "node")) {
    Add-Check -Area "Trainer turn smoke" -Status "missing" -Detail "Node.js is not available for trainer turn smoke."
  } else {
    $turnSmokeApiKey = if ($TrainerTurnSmokeApiKey) { $TrainerTurnSmokeApiKey.Trim() } else { $env:TRAINER_TURN_SMOKE_PROVIDER_API_KEY }
    $turnSmokeBaseUrl = if ($TrainerTurnSmokeBaseUrl) { $TrainerTurnSmokeBaseUrl.Trim() } else { $env:TRAINER_TURN_SMOKE_PROVIDER_BASE_URL }
    $turnSmokeModel = if ($TrainerTurnSmokeModel) { $TrainerTurnSmokeModel.Trim() } else { $env:TRAINER_TURN_SMOKE_PROVIDER_MODEL }
    $turnSmokeProtocol = if ($TrainerTurnSmokeProtocol) { $TrainerTurnSmokeProtocol.Trim() } else { $env:TRAINER_TURN_SMOKE_PROVIDER_PROTOCOL }
    $turnSmokeResponseLanguage = if ($TrainerTurnSmokeResponseLanguage) { $TrainerTurnSmokeResponseLanguage.Trim() } else { $env:TRAINER_TURN_SMOKE_RESPONSE_LANGUAGE }
    $turnSmokeSidecarUrl = if ($TrainerTurnSmokeSidecarUrl) { $TrainerTurnSmokeSidecarUrl.Trim() } else { $env:TRAINER_TURN_SMOKE_SIDECAR_URL }

    if (-not $turnSmokeApiKey) {
      Add-Check -Area "Trainer turn smoke" -Status "missing" -Detail "Pass -TrainerTurnSmokeApiKey or set TRAINER_TURN_SMOKE_PROVIDER_API_KEY."
    } elseif (-not $turnSmokeBaseUrl) {
      Add-Check -Area "Trainer turn smoke" -Status "missing" -Detail "Pass -TrainerTurnSmokeBaseUrl or set TRAINER_TURN_SMOKE_PROVIDER_BASE_URL."
    } else {
      if (-not $turnSmokeSidecarUrl) {
        if ($healthFound) {
          $turnSmokeSidecarUrl = "http://127.0.0.1:$candidatePort"
        } else {
          Add-Check -Area "Trainer turn smoke" -Status "missing" -Detail "Pass -TrainerTurnSmokeSidecarUrl, set TRAINER_TURN_SMOKE_SIDECAR_URL, or start a local sidecar first."
        }
      }

      if ($turnSmokeSidecarUrl) {
        $trainerTurnSmokeEnv = @{
          TRAINER_TURN_SMOKE_SIDECAR_URL = $turnSmokeSidecarUrl
          TRAINER_TURN_SMOKE_PROVIDER_API_KEY = $turnSmokeApiKey
          TRAINER_TURN_SMOKE_PROVIDER_BASE_URL = $turnSmokeBaseUrl
        }
        if ($turnSmokeModel) {
          $trainerTurnSmokeEnv.TRAINER_TURN_SMOKE_PROVIDER_MODEL = $turnSmokeModel
        }
        if ($turnSmokeProtocol) {
          $trainerTurnSmokeEnv.TRAINER_TURN_SMOKE_PROVIDER_PROTOCOL = $turnSmokeProtocol
        }
        if ($turnSmokeResponseLanguage) {
          $trainerTurnSmokeEnv.TRAINER_TURN_SMOKE_RESPONSE_LANGUAGE = $turnSmokeResponseLanguage
        }

        $trainerTurnSmokeExit = Invoke-NodeScript "scripts/trainer-turn-smoke.mjs" -Environment $trainerTurnSmokeEnv
        Add-Check -Area "Trainer turn smoke" -Status ($(if ($trainerTurnSmokeExit -eq 0) { "ok" } else { "failed" })) -Detail "Live trainer turn smoke via scripts/trainer-turn-smoke.mjs"
      }
    }
  }
}

if ($TrainingReturnSmoke) {
  if (-not (Test-Command "node")) {
    Add-Check -Area "Training return smoke" -Status "missing" -Detail "Node.js is not available for training return smoke."
  } else {
    $returnSmokeApiKey = if ($TrainingReturnSmokeApiKey) { $TrainingReturnSmokeApiKey.Trim() } else { $env:TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_API_KEY }
    $returnSmokeBaseUrl = if ($TrainingReturnSmokeBaseUrl) { $TrainingReturnSmokeBaseUrl.Trim() } else { $env:TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_BASE_URL }
    $returnSmokeModel = if ($TrainingReturnSmokeModel) { $TrainingReturnSmokeModel.Trim() } else { $env:TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_MODEL }
    $returnSmokeProtocol = if ($TrainingReturnSmokeProtocol) { $TrainingReturnSmokeProtocol.Trim() } else { $env:TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_PROTOCOL }
    $returnSmokeResponseLanguage = if ($TrainingReturnSmokeResponseLanguage) { $TrainingReturnSmokeResponseLanguage.Trim() } else { $env:TRAINER_TRAINING_RETURN_SMOKE_RESPONSE_LANGUAGE }
    $returnSmokeSidecarUrl = if ($TrainingReturnSmokeSidecarUrl) { $TrainingReturnSmokeSidecarUrl.Trim() } else { $env:TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL }

    if (-not $returnSmokeApiKey) {
      Add-Check -Area "Training return smoke" -Status "missing" -Detail "Pass -TrainingReturnSmokeApiKey or set TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_API_KEY."
    } elseif (-not $returnSmokeBaseUrl) {
      Add-Check -Area "Training return smoke" -Status "missing" -Detail "Pass -TrainingReturnSmokeBaseUrl or set TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_BASE_URL."
    } else {
      if (-not $returnSmokeSidecarUrl) {
        if ($healthFound) {
          $returnSmokeSidecarUrl = "http://127.0.0.1:$candidatePort"
        } else {
          Add-Check -Area "Training return smoke" -Status "missing" -Detail "Pass -TrainingReturnSmokeSidecarUrl, set TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL, or start a local sidecar first."
        }
      }

      if ($returnSmokeSidecarUrl) {
        $trainingReturnSmokeEnv = @{
          TRAINER_TRAINING_RETURN_SMOKE_SIDECAR_URL = $returnSmokeSidecarUrl
          TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_API_KEY = $returnSmokeApiKey
          TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_BASE_URL = $returnSmokeBaseUrl
        }
        if ($returnSmokeModel) {
          $trainingReturnSmokeEnv.TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_MODEL = $returnSmokeModel
        }
        if ($returnSmokeProtocol) {
          $trainingReturnSmokeEnv.TRAINER_TRAINING_RETURN_SMOKE_PROVIDER_PROTOCOL = $returnSmokeProtocol
        }
        if ($returnSmokeResponseLanguage) {
          $trainingReturnSmokeEnv.TRAINER_TRAINING_RETURN_SMOKE_RESPONSE_LANGUAGE = $returnSmokeResponseLanguage
        }

        $trainingReturnSmokeExit = Invoke-NodeScript "scripts/training-return-smoke.mjs" -Environment $trainingReturnSmokeEnv
        Add-Check -Area "Training return smoke" -Status ($(if ($trainingReturnSmokeExit -eq 0) { "ok" } else { "failed" })) -Detail "Live training return smoke via scripts/training-return-smoke.mjs"
      }
    }
  }
}

$checks | Format-Table -AutoSize

$blockingStatuses = @("missing", "failed")
if ($Strict) {
  $blockingStatuses += "pending"
}

$blocking = $checks | Where-Object { $_.Status -in $blockingStatuses }
if ($blocking.Count -gt 0) {
  exit 1
}

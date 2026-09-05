Param(
  [switch]$Strict
)

$ErrorActionPreference = "Stop"

$failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure {
  param([string]$Message)
  $failures.Add($Message)
  Write-Host "[FAIL] $Message" -ForegroundColor Red
}

function Write-Info {
  param(
    [string]$Status,
    [string]$Message
  )

  $color = switch ($Status) {
    "OK" { "Green" }
    "SKIP" { "Yellow" }
    default { "Cyan" }
  }

  Write-Host "[$Status] $Message" -ForegroundColor $color
}

function Test-AnySource {
  param([string]$Pattern)
  return $null -ne (
    Get-ChildItem -Path $Pattern -Recurse -File -ErrorAction SilentlyContinue |
      Select-Object -First 1
  )
}

function Invoke-Check {
  param(
    [scriptblock]$Command,
    [string]$SuccessMessage,
    [string]$FailureMessage
  )

  & $Command
  if ($LASTEXITCODE -eq 0) {
    Write-Info "OK" $SuccessMessage
    return
  }

  Add-Failure "$FailureMessage (exit $LASTEXITCODE)"
}

if (Test-Path "extension/webview/package.json") {
  Invoke-Check `
    -Command { npm run check --prefix extension/webview } `
    -SuccessMessage "Webview check completed." `
    -FailureMessage "Webview check failed."
} elseif ($Strict) {
  Add-Failure "Webview manifest is missing."
} else {
  Write-Info "SKIP" "Webview manifest is missing."
}

if (Test-AnySource "extension/src/*.ts") {
  if (Test-Path "extension/node_modules/typescript") {
    Invoke-Check `
      -Command { npm run check --prefix extension } `
      -SuccessMessage "Extension host typecheck completed." `
      -FailureMessage "Extension host typecheck failed."

    if (Test-AnySource "extension/tests/*.test.js") {
      Invoke-Check `
        -Command { npm run build --prefix extension } `
        -SuccessMessage "Extension host build completed." `
        -FailureMessage "Extension host build failed."

      Invoke-Check `
        -Command { node --test extension/tests/*.test.js } `
        -SuccessMessage "Extension host contract tests completed." `
        -FailureMessage "Extension host contract tests failed."
    } elseif ($Strict) {
      Add-Failure "Extension host tests are missing under extension/tests."
    } else {
      Write-Info "SKIP" "Extension host tests are not present yet."
    }
  } elseif ($Strict) {
    Add-Failure "Extension dependencies are not installed. Run scripts/bootstrap.ps1."
  } else {
    Write-Info "SKIP" "Extension dependencies are not installed yet."
  }
} elseif ($Strict) {
  Add-Failure "Extension host sources are missing under extension/src."
} else {
  Write-Info "SKIP" "Extension host sources are not present yet."
}

if (Test-Path "server/app/main.py") {
  if (Test-Path "server/.venv/Scripts/python.exe") {
    Invoke-Check `
      -Command { & "server/.venv/Scripts/python.exe" -m ruff check server/app server/tests } `
      -SuccessMessage "Server Ruff check completed." `
      -FailureMessage "Server Ruff check failed."

    Invoke-Check `
      -Command { & "server/.venv/Scripts/python.exe" -m pyright server/app } `
      -SuccessMessage "Server Pyright check completed." `
      -FailureMessage "Server Pyright check failed."

    Invoke-Check `
      -Command { & "server/.venv/Scripts/python.exe" -m pytest server/tests } `
      -SuccessMessage "Server pytest completed." `
      -FailureMessage "Server pytest failed."
  } elseif ($Strict) {
    Add-Failure "Server virtual environment is missing. Run scripts/bootstrap.ps1."
  } else {
    Write-Info "SKIP" "Server virtual environment is not ready yet."
  }
} elseif ($Strict) {
  Add-Failure "Server package entrypoint is missing under server/app/main.py."
} else {
  Write-Info "SKIP" "Server package entrypoint is not present yet."
}

if ($failures.Count -gt 0) {
  exit 1
}

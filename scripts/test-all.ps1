$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$results = @()

function Invoke-Suite($name, $directory, $command, $arguments) {
  Write-Host "`n=== $name ===" -ForegroundColor Cyan
  Push-Location (Join-Path $root $directory)
  try {
    & $command @arguments
    $code = $LASTEXITCODE
    $script:results += [pscustomobject]@{ Service = $name; ExitCode = $code }
  } finally {
    Pop-Location
  }
}

Invoke-Suite "Frontend build" "frontend" "npm" @("run", "build")
Invoke-Suite "Backend tests" "backend" "python" @("-m", "pytest", "-q")
Invoke-Suite "LLM API tests" "llm-service" "python" @("-m", "pytest", "-q", "tests")
Invoke-Suite "Deterministic ML tests" "ml-service" "python" @("-m", "pytest", "-q")

Write-Host "`n=== Test summary ==="
$results | Format-Table -AutoSize
if (($results | Where-Object { $_.ExitCode -ne 0 }).Count -gt 0) { exit 1 }
exit 0

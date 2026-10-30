$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
$results = @()

function Get-ServicePython($directory) {
  $servicePath = Join-Path $root $directory
  $windowsPython = Join-Path $servicePath ".venv\Scripts\python.exe"
  $unixPython = Join-Path $servicePath ".venv\bin\python"
  if (Test-Path $windowsPython) { return $windowsPython }
  if (Test-Path $unixPython) { return $unixPython }
  return "python"
}

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

$backendPython = Get-ServicePython "backend"
$llmPython = Get-ServicePython "llm-service"
$mlPython = Get-ServicePython "ml-service"

Invoke-Suite "Frontend build" "frontend" "npm" @("run", "build")
Invoke-Suite "Backend tests" "backend" $backendPython @("-m", "pytest", "-q")
Invoke-Suite "LLM API tests" "llm-service" $llmPython @("-m", "pytest", "-q", "tests")
Invoke-Suite "Deterministic ML tests" "ml-service" $mlPython @("-m", "pytest", "-q")

Write-Host "`n=== Test summary ==="
$results | Format-Table -AutoSize
if (($results | Where-Object { $_.ExitCode -ne 0 }).Count -gt 0) { exit 1 }
exit 0

[CmdletBinding()]
param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"
$failures = [System.Collections.Generic.List[string]]::new()

function Write-Check([string]$Label, [bool]$Passed, [string]$Detail) {
    if ($Passed) {
        Write-Host "[PASS] $Label - $Detail" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] $Label - $Detail" -ForegroundColor Red
        $script:failures.Add($Label)
    }
}

function Read-EnvFile([string]$Path) {
    $values = @{}
    if (-not (Test-Path $Path)) { throw "Missing environment file: $Path" }
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*#') { continue }
        $match = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$')
        if ($match.Success) {
            $value = $match.Groups[2].Value.Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $values[$match.Groups[1].Value] = $value
        }
    }
    return $values
}

function Test-PortProcess([int]$Port, [string]$ExpectedFragment) {
    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) {
        Write-Check "Port $Port" $false "No process is listening."
        return
    }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)"
    $command = [string]$process.CommandLine
    $passed = $command.ToLowerInvariant().Contains($ExpectedFragment.ToLowerInvariant())
    Write-Check "Port $Port process" $passed ($(if ($passed) { "Expected runtime is active." } else { "Unexpected command line: $command" }))
}

Write-Host ""
Write-Host "SolarSleuth local runtime verification" -ForegroundColor Cyan
Write-Host "Repository: $Root"
Write-Host ""

$llmEnv = Read-EnvFile (Join-Path $Root "llm-service/.env")
$backendEnv = Read-EnvFile (Join-Path $Root "backend/.env")
$mlEnv = Read-EnvFile (Join-Path $Root "ml-service/.env")

Test-PortProcess 8000 "llm-service\.venv\scripts\python.exe"
Test-PortProcess 8001 "backend\.venv\scripts\python.exe"
Test-PortProcess 8002 "ml-service\.venv\scripts\python.exe"
Test-PortProcess 5173 "node"

$timeoutOk = $backendEnv["LLM_TIMEOUT_SECONDS"] -eq "300"
Write-Check "Backend LLM timeout" $timeoutOk "LLM_TIMEOUT_SECONDS must be 300."

$tokens = @($backendEnv["INTERNAL_SERVICE_TOKEN"], $mlEnv["INTERNAL_SERVICE_TOKEN"], $llmEnv["INTERNAL_SERVICE_TOKEN"])
$tokensMatch = ($tokens[0] -and $tokens[1] -and $tokens[2] -and $tokens[0] -ceq $tokens[1] -and $tokens[1] -ceq $tokens[2])
Write-Check "Shared internal token" $tokensMatch "All three services must use the same non-empty token; values are not printed."

$cors = [string]$backendEnv["CORS_ORIGINS"]
$corsOk = $cors.Contains("http://127.0.0.1:5173") -and $cors.Contains("http://localhost:5173")
Write-Check "CORS origins" $corsOk "Both localhost and 127.0.0.1 frontend origins must be allowed."

# Detect processes started from an older checkout: these fields exist only in current code.
try {
    $llmReady = Invoke-RestMethod -Uri "http://127.0.0.1:8000/ready" -TimeoutSec 10
    $llmCurrent = $llmReady.PSObject.Properties.Name -contains "last_inference_error" -and $llmReady.PSObject.Properties.Name -contains "last_prompt_tokens"
    Write-Check "LLM code version" $llmCurrent "Port 8000 must run llm-service from this repository; restart it from $Root\llm-service if this fails."
} catch {
    Write-Check "LLM code version" $false $_.Exception.Message
}
try {
    $backendReady = Invoke-RestMethod -Uri "http://127.0.0.1:8001/ready" -TimeoutSec 10
    $backendCurrent = $backendReady.PSObject.Properties.Name -contains "llm_model_name" -and $backendReady.PSObject.Properties.Name -contains "ml_status"
    Write-Check "Backend code version" $backendCurrent "Port 8001 must run backend from this repository; restart it from $Root\backend if this fails."
} catch {
    Write-Check "Backend code version" $false $_.Exception.Message
}

try {
    $warmup = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/warmup" -TimeoutSec 300
    Write-Check "LLM warmup" ([bool]$warmup.model_loaded) "Model: $($warmup.model_name); status: $($warmup.status)."
} catch {
    Write-Check "LLM warmup" $false $_.Exception.Message
}

try {
    $ready = Invoke-RestMethod -Uri "http://127.0.0.1:8001/ready" -TimeoutSec 10
    $readyOk = $ready.status -eq "ready" -and $ready.ml_service_reachable -and $ready.llm_api_reachable -and $ready.model_loaded -and $ready.llm_status -eq "ready"
    Write-Check "Backend readiness" ([bool]$readyOk) ("status={0}; ML={1}; LLM={2}; model={3}; error={4}" -f $ready.status, $ready.ml_status, $ready.llm_status, $ready.model_loaded, $ready.llm_error)
} catch {
    Write-Check "Backend readiness" $false $_.Exception.Message
}

try {
    $null = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -TimeoutSec 10
    Write-Check "Frontend HTTP" $true "Vite responded on port 5173."
} catch {
    Write-Check "Frontend HTTP" $false $_.Exception.Message
}

Write-Host ""
if ($failures.Count -gt 0) {
    Write-Host "Runtime verification failed: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "All local runtime checks passed." -ForegroundColor Green

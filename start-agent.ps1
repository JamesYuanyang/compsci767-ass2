param(
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

$ollamaExe = "D:\Ollama\App\ollama.exe"
if (-not (Test-Path $ollamaExe)) {
    throw "Ollama was not found at $ollamaExe"
}

$env:OLLAMA_MODELS = "D:\Ollama\Models"
$env:LLM_PROVIDER = "ollama"
$env:OLLAMA_BASE_URL = "http://127.0.0.1:11434"
$env:LLM_MODEL = "llama3.2:1b"
$env:LLM_TIMEOUT_SECONDS = "45"
$env:LLM_HEALTH_TIMEOUT_SECONDS = "1.5"

$ollamaRunning = Get-Process -Name "ollama" -ErrorAction SilentlyContinue
if (-not $ollamaRunning) {
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

try {
    Invoke-RestMethod "$env:OLLAMA_BASE_URL/api/tags" -TimeoutSec 5 | Out-Null
} catch {
    throw "Ollama did not become available at $env:OLLAMA_BASE_URL"
}

$modelList = Invoke-RestMethod "$env:OLLAMA_BASE_URL/api/tags" -TimeoutSec 5
if (-not ($modelList.models | Where-Object { $_.name -eq $env:LLM_MODEL -or $_.model -eq $env:LLM_MODEL })) {
    & $ollamaExe pull $env:LLM_MODEL
}

Write-Host "Starting Personal Task Planning Agent with $env:LLM_MODEL on http://127.0.0.1:$Port"
& ".\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port $Port

param(
    [string]$BindAddress = '127.0.0.1',
    [int]$Port = 8000,
    [string]$ConfigFile = 'config/fathom.yaml'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw '尚未安装 FATHOM，请先运行 scripts\install.ps1。'
}

Set-Location $projectRoot
$resolvedConfig = Join-Path $projectRoot $ConfigFile
if (Test-Path -LiteralPath $resolvedConfig) {
    $env:FATHOM_CONFIG_FILE = $resolvedConfig
}
& $pythonExecutable -m uvicorn fathom.main:app --host $BindAddress --port $Port

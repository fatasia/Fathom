param(
    [switch]$LiteOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$virtualEnvironment = Join-Path $projectRoot '.venv'
$pythonExecutable = Join-Path $virtualEnvironment 'Scripts\python.exe'

Set-Location $projectRoot
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    python -m venv $virtualEnvironment
}

& $pythonExecutable -m pip install --upgrade pip
if ($LiteOnly) {
    & $pythonExecutable -m pip install -e '.[dev]'
} else {
    & $pythonExecutable -m pip install -e '.[dev,connectors-sql,connectors-industrial,connectors-context]'
}

Set-Location (Join-Path $projectRoot 'apps\web')
pnpm install
pnpm build

Set-Location $projectRoot
& $pythonExecutable -m fathom.cli init
Write-Host 'FATHOM 安装完成。运行 scripts\start.ps1 启动 Web 服务。'

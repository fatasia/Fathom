param(
    [ValidateSet('up', 'down', 'status')]
    [string]$Action = 'up',
    [string]$Version = '1.16.1'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$difyRoot = Join-Path $projectRoot 'tools\dify'
$composeRoot = Join-Path $difyRoot 'docker'
$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
$dockerExecutable = if ($dockerCommand) {
    $dockerCommand.Source
} else {
    'C:\Program Files\Docker\Docker\resources\bin\docker.exe'
}
if (-not (Test-Path -LiteralPath $dockerExecutable)) {
    throw '未找到 Docker CLI，请先安装并启动 Docker Desktop。'
}

if (-not (Test-Path -LiteralPath $composeRoot)) {
    New-Item -ItemType Directory -Path (Join-Path $projectRoot 'tools') -Force | Out-Null
    git clone --depth 1 --branch $Version https://github.com/langgenius/dify.git $difyRoot
}

$environmentFile = Join-Path $composeRoot '.env'
if (-not (Test-Path -LiteralPath $environmentFile)) {
    Copy-Item -LiteralPath (Join-Path $composeRoot '.env.example') -Destination $environmentFile
}

Set-Location $composeRoot
switch ($Action) {
    'up' { & $dockerExecutable compose up -d }
    'down' { & $dockerExecutable compose down }
    'status' { & $dockerExecutable compose ps }
}

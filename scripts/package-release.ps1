param(
    [string]$Version = '0.1.0'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$distDirectory = Join-Path $projectRoot 'dist'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$packageName = "FATHOM-$Version-$timestamp"
$stagingParent = Join-Path $distDirectory ".staging-$timestamp"
$stagingRoot = Join-Path $stagingParent $packageName
$archivePath = Join-Path $distDirectory "$packageName.zip"

New-Item -ItemType Directory -Force -Path $distDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null

try {
    & git -C $projectRoot archive --format=tar HEAD | tar -xf - -C $stagingRoot
    if ($LASTEXITCODE -ne 0) {
        throw '无法从当前 Git 提交创建发布目录'
    }

    $staticSource = Join-Path $projectRoot 'apps/api/src/fathom/interfaces/static'
    if (-not (Test-Path -LiteralPath (Join-Path $staticSource 'index.html'))) {
        throw '未找到已编译 Web 页面，请先在 apps/web 执行 pnpm build'
    }
    $staticTarget = Join-Path $stagingRoot 'apps/api/src/fathom/interfaces/static'
    New-Item -ItemType Directory -Force -Path $staticTarget | Out-Null
    Copy-Item -LiteralPath (Join-Path $staticSource 'index.html') -Destination $staticTarget
    Copy-Item -LiteralPath (Join-Path $staticSource 'assets') -Destination $staticTarget -Recurse

    $manifest = @(
        "FATHOM deployment package",
        "Version: $Version",
        "Created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss K')",
        "Commit: $(& git -C $projectRoot rev-parse HEAD)",
        'Excluded: runtime databases, credentials, caches, Dify volumes, dependencies'
    )
    Set-Content -LiteralPath (Join-Path $stagingRoot 'PACKAGE.txt') -Value $manifest -Encoding utf8

    Compress-Archive -LiteralPath $stagingRoot -DestinationPath $archivePath -CompressionLevel Optimal
    $hash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -LiteralPath "$archivePath.sha256" -Value "$hash  $packageName.zip" -Encoding ascii
    Get-Item -LiteralPath $archivePath | Select-Object FullName, Length, LastWriteTime
    Write-Host "SHA256: $hash"
}
finally {
    $resolvedDist = (Resolve-Path -LiteralPath $distDirectory).Path
    $resolvedStaging = (Resolve-Path -LiteralPath $stagingParent -ErrorAction SilentlyContinue).Path
    if ($resolvedStaging -and $resolvedStaging.StartsWith($resolvedDist, [System.StringComparison]::OrdinalIgnoreCase)) {
        Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
    }
}

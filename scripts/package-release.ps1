param(
    [string]$Version = '0.4.0'
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$distDirectory = Join-Path $projectRoot 'dist'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$packageName = "FATHOM-$Version-$timestamp"
$stagingParent = Join-Path $distDirectory ".staging-$timestamp"
$stagingRoot = Join-Path $stagingParent $packageName
$archivePath = Join-Path $distDirectory "$packageName.zip"

$excludedExtensions = @(
    '.pdf', '.docx', '.pptx', '.xlsx',
    '.mp4', '.mov', '.avi', '.mkv', '.webm', '.wmv', '.m4v', '.mpeg', '.mpg',
    '.mp3', '.wav', '.flac', '.aac', '.m4a'
)

function Test-PackagePath {
    param([Parameter(Mandatory)][string]$Path)

    $normalized = $Path.Replace('\\', '/')
    if ($normalized -match '^(dist|data|artifacts|\.git|\.venv|node_modules)/') {
        return $false
    }
    if ($normalized -match '(^|/)(node_modules|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|\.vite|coverage|volumes?|test[-_]?data|sample[-_]?data|fixtures?)(/|$)') {
        return $false
    }
    if ($normalized -eq 'config/fathom.yaml' -or $normalized -match '(^|/)\.env($|\.)') {
        return $normalized.EndsWith('.example', [System.StringComparison]::OrdinalIgnoreCase)
    }
    return -not ($excludedExtensions -contains [System.IO.Path]::GetExtension($normalized).ToLowerInvariant())
}

New-Item -ItemType Directory -Force -Path $distDirectory | Out-Null
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null

try {
    # Git prints UTF-8 paths, but a Chinese Windows console defaults to GBK and
    # would mangle non-ASCII names into unreadable bytes. Forcing UTF-8 output
    # keeps paths like docs/使用手册.md resolvable on disk.
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
    # Package the current working tree so reviewed but uncommitted feature work
    # is not silently omitted. Git still supplies the authoritative file list,
    # including non-ignored untracked source files.
    $sourceFiles = @(& git -C $projectRoot -c core.quotepath=false ls-files --cached --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) {
        throw '无法读取当前 Git 工作区文件列表'
    }
    if ($sourceFiles.Count -eq 0) {
        throw 'Git 工作区文件列表为空，拒绝生成空发布包'
    }
    $missingSources = [System.Collections.Generic.List[string]]::new()
    $projectPrefix = $projectRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    $stagingPrefix = $stagingRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    foreach ($gitPath in $sourceFiles) {
        if (-not (Test-PackagePath -Path $gitPath)) {
            continue
        }
        $relativePath = $gitPath.Replace('/', [System.IO.Path]::DirectorySeparatorChar)
        $sourcePath = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $relativePath))
        $targetPath = [System.IO.Path]::GetFullPath((Join-Path $stagingRoot $relativePath))
        if (-not $sourcePath.StartsWith($projectPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "源文件越出项目目录：$gitPath"
        }
        if (-not $targetPath.StartsWith($stagingPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "目标文件越出暂存目录：$gitPath"
        }
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            # A tracked file that cannot be resolved means the path list itself is
            # wrong (encoding or a stale index), never a routine skip.
            $missingSources.Add($gitPath)
            continue
        }
        $targetDirectory = Split-Path -Parent $targetPath
        New-Item -ItemType Directory -Force -Path $targetDirectory | Out-Null
        Copy-Item -LiteralPath $sourcePath -Destination $targetPath
    }
    if ($missingSources.Count -gt 0) {
        throw "以下文件在 Git 索引中但磁盘上不存在，发布包将不完整：`n$($missingSources -join "`n")"
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
        'Source: current Git working tree (tracked and non-ignored untracked files)',
        'Excluded: PDF/DOCX/Office binaries, audio/video, local test/runtime data, credentials, caches, external platform volumes, dependencies'
    )
    Set-Content -LiteralPath (Join-Path $stagingRoot 'PACKAGE.txt') -Value $manifest -Encoding utf8

    # Force UTF-8 entry names so Chinese documents unpack consistently on
    # Windows and Linux.
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $stagingRoot,
        $archivePath,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $true,
        [System.Text.Encoding]::UTF8
    )

    # Read the archive back instead of trusting the staging tree: this is what
    # catches an encoding fault that silently drops non-ASCII paths.
    $requiredEntries = @(
        'LICENSE',
        'README.md',
        'PACKAGE.txt',
        'semantic/manufacturing.execution.yaml',
        'seed/golden-questions.yaml',
        'seed/demo-dataset.yaml',
        'docs/使用手册.md',
        'docs/架构设计.md',
        'docs/部署与接入指南.md',
        'apps/api/src/fathom/main.py',
        'apps/api/src/fathom/interfaces/static/index.html'
    )
    $written = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::Ordinal)
    $archive = [System.IO.Compression.ZipFile]::OpenRead($archivePath)
    try {
        foreach ($entry in $archive.Entries) {
            $written.Add(($entry.FullName -replace '\\', '/')) | Out-Null
        }
    }
    finally {
        $archive.Dispose()
    }
    $absent = @($requiredEntries | Where-Object { -not $written.Contains("$packageName/$_") })
    if ($absent.Count -gt 0) {
        throw "发布包缺少必要文件（可能因路径编码问题被跳过）：`n$($absent -join "`n")"
    }
    if ($written.Count -lt 2) {
        throw '发布包内容异常：条目过少'
    }

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

param(
    [switch]$BuildExe,
    [switch]$FromPortable
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$portableRoot = Join-Path $projectRoot "MyBarid-AI-Portable"

if (-not (Test-Path -LiteralPath $portableRoot)) {
    New-Item -ItemType Directory -Path $portableRoot | Out-Null
}

if ($BuildExe -and $FromPortable) {
    throw "Use either -BuildExe or -FromPortable, not both."
}

if ($BuildExe) {
    Push-Location $projectRoot
    try {
        $pyinstaller = Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe"
        if (-not (Test-Path -LiteralPath $pyinstaller)) {
            $pyinstaller = Join-Path $projectRoot ".venv-build\Scripts\pyinstaller.exe"
        }
        if (-not (Test-Path -LiteralPath $pyinstaller)) {
            throw "PyInstaller environment not found. Create .venv-build or repair .venv."
        }
        $buildRoot = Join-Path $env:TEMP "MyBarid-AI-pyinstaller"
        $workPath = Join-Path $buildRoot "build"
        $distPath = Join-Path $buildRoot "dist"
        New-Item -ItemType Directory -Force -Path $buildRoot | Out-Null
        & $pyinstaller --noconfirm --clean --workpath $workPath --distpath $distPath (Join-Path $projectRoot "MyBarid-AI.spec")
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

$releaseFiles = @(
    @{ Name = "MyBarid-AI.exe"; Source = $(if ($FromPortable) { Join-Path $portableRoot "MyBarid-AI.exe" } else { Join-Path (Join-Path $env:TEMP "MyBarid-AI-pyinstaller\dist") "MyBarid-AI.exe" }) },
    @{ Name = "VERSION"; Source = $(if ($FromPortable) { Join-Path $portableRoot "VERSION" } else { Join-Path $projectRoot "VERSION" }) },
    @{ Name = "CHANGELOG.json"; Source = $(if ($FromPortable) { Join-Path $portableRoot "CHANGELOG.json" } else { Join-Path $projectRoot "CHANGELOG.json" }) }
)

foreach ($file in $releaseFiles) {
    $sourcePath = $file.Source
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Release file not found: $sourcePath"
    }
    $rootDestination = Join-Path $projectRoot $file.Name
    $portableDestination = Join-Path $portableRoot $file.Name
    if (([IO.Path]::GetFullPath($sourcePath)) -ne ([IO.Path]::GetFullPath($rootDestination))) {
        Copy-Item -LiteralPath $sourcePath -Destination $rootDestination -Force
    }
    if (([IO.Path]::GetFullPath($sourcePath)) -ne ([IO.Path]::GetFullPath($portableDestination))) {
        Copy-Item -LiteralPath $sourcePath -Destination $portableDestination -Force
    }
}

# تنظیمات کاربر در Portable منبع اصلی است؛ نسخه‌ای هم در ریشه پروژه نگه می‌داریم.
$userFiles = @("app.db", "criteria_config.json", "api-key.bin")
foreach ($name in $userFiles) {
    $sourcePath = Join-Path $portableRoot $name
    if (Test-Path -LiteralPath $sourcePath) {
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $projectRoot $name) -Force
    }
}

Write-Host "Portable and project root are synchronized."

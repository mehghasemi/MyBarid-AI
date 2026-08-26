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
        & (Join-Path $projectRoot ".venv\Scripts\pyinstaller.exe") --noconfirm --clean (Join-Path $projectRoot "MyBarid-AI.spec")
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller failed with exit code $LASTEXITCODE."
        }
    }
    finally {
        Pop-Location
    }
}

$releaseFiles = @(
    @{ Name = "MyBarid-AI.exe"; Source = $(if ($FromPortable) { Join-Path $portableRoot "MyBarid-AI.exe" } else { Join-Path $projectRoot "dist\MyBarid-AI.exe" }) },
    @{ Name = "VERSION"; Source = $(if ($FromPortable) { Join-Path $portableRoot "VERSION" } else { Join-Path $projectRoot "VERSION" }) },
    @{ Name = "CHANGELOG.json"; Source = $(if ($FromPortable) { Join-Path $portableRoot "CHANGELOG.json" } else { Join-Path $projectRoot "CHANGELOG.json" }) }
)

foreach ($file in $releaseFiles) {
    $sourcePath = $file.Source
    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Release file not found: $sourcePath"
    }
    if ($FromPortable) {
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $projectRoot $file.Name) -Force
    } else {
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $portableRoot $file.Name) -Force
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

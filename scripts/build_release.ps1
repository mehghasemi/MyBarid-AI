$ErrorActionPreference = "Stop"
$scriptPath = Join-Path $PSScriptRoot "sync_portable.ps1"
& $scriptPath -BuildExe
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

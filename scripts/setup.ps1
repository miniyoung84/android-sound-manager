# One-time developer setup for Windows.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# Creates .venv (Python 3.13), installs the app in editable mode with dev tools,
# and reports which external tools (adb, ffmpeg, node) are available.

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Find-Python {
    $direct = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if (Test-Path $direct) { return $direct }
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        $resolved = & $launcher.Source -3.13 -c 'import sys; print(sys.executable)'
        if ($LASTEXITCODE -eq 0) { return $resolved.Trim() }
    }
    throw 'Python 3.13 not found. Install it with: winget install -e --id Python.Python.3.13 --source winget'
}

if (-not (Test-Path '.venv\Scripts\python.exe')) {
    $py = Find-Python
    Write-Host "Creating .venv with $py"
    & $py -m venv .venv
}

$venvPy = Join-Path $root '.venv\Scripts\python.exe'
& $venvPy -m pip install --upgrade pip --quiet
& $venvPy -m pip install -e '.[dev]' --quiet
Write-Host 'Python dependencies installed.' -ForegroundColor Green

# Pre-commit hook that blocks private data from being committed to this public repo.
git config core.hooksPath scripts/hooks
if (-not (Test-Path '.private-patterns')) {
    Set-Content -Path '.private-patterns' -Encoding ascii -Value @(
        '# Local only (gitignored). One case-insensitive regex per line.',
        '# Add your email, device serial, contact names, etc. The pre-commit hook blocks matches.'
    )
}
Write-Host 'Pre-commit privacy hook enabled (edit .private-patterns to add your own terms).'

Write-Host "`nExternal tools:"
& $venvPy -m soundmanager.tools

Write-Host @'

If anything is MISSING:
  adb     -> https://developer.android.com/tools/releases/platform-tools (unzip to %LOCALAPPDATA%\Android\Sdk)
  ffmpeg  -> winget install -e --id Gyan.FFmpeg --source winget
  node    -> winget install -e --id OpenJS.NodeJS.LTS --source winget

Run the app:  .venv\Scripts\python -m soundmanager
Shortcuts:    powershell -ExecutionPolicy Bypass -File scripts\install_shortcuts.ps1
Run tests:    .venv\Scripts\python -m pytest
'@

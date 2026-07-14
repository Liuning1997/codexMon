$ErrorActionPreference = 'Stop'
$PluginRoot = Split-Path -Parent $PSScriptRoot
$Startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$ShortcutPath = Join-Path $Startup 'Codex Moon Dashboard.lnk'

if (Test-Path -LiteralPath $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath -Force
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*codex-moon-dashboard*monitor.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host 'Codex Moon Dashboard startup entry removed.'

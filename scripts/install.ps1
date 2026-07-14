$ErrorActionPreference = 'Stop'

$PluginRoot = Split-Path -Parent $PSScriptRoot
$Monitor = Join-Path $PluginRoot 'scripts\monitor.py'
$Startup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup'
$ShortcutPath = Join-Path $Startup 'Codex Moon Dashboard.lnk'

function Resolve-Python {
    $candidates = @(
        'D:\Anaconda\pythonw.exe',
        'D:\Anaconda\python.exe',
        (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source,
        (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    throw 'Python was not found. Install Python 3.10+ or update the Python path in this script.'
}

$Python = Resolve-Python
$PythonConsole = $Python -replace 'pythonw\.exe$', 'python.exe'
if (-not (Test-Path -LiteralPath $PythonConsole)) { $PythonConsole = $Python }

$previousErrorActionPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $PythonConsole -c 'import tkinter, PIL, psutil' 2>$null
$dependencyExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorActionPreference
if ($dependencyExitCode -ne 0) {
    Write-Host 'Installing or completing Pillow and psutil dependencies...'
    & $PythonConsole -m pip install -r (Join-Path $PluginRoot 'scripts\requirements.txt')
}

New-Item -ItemType Directory -Path $Startup -Force | Out-Null
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $Python
$shortcut.Arguments = '"' + $Monitor + '"'
$shortcut.WorkingDirectory = $PluginRoot
$shortcut.Description = 'Open Codex Moon Dashboard while Codex is running'
$shortcut.Save()

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like '*codex-moon-dashboard*monitor.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Process -FilePath $Python -ArgumentList ('"' + $Monitor + '"') -WorkingDirectory $PluginRoot
Write-Host 'Codex Moon Dashboard startup entry created and monitor started.'

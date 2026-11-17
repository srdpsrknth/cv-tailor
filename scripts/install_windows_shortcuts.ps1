# Run once per checkout, or again after moving the project.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $PSScriptRoot 'windows_gui.ps1'
$powershell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$programs = Join-Path ([Environment]::GetFolderPath('Programs')) 'CV Tailor'
New-Item -ItemType Directory -Force -Path $programs | Out-Null
foreach ($folder in @($desktop, $programs)) {
    foreach ($action in @('Open', 'Stop')) {
        $name = if ($action -eq 'Open') { 'CV Tailor' } else { 'Stop CV Tailor' }
        $shortcut = $shell.CreateShortcut((Join-Path $folder "$name.lnk"))
        $shortcut.TargetPath = $powershell
        $shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $launcher
        if ($action -eq 'Stop') { $shortcut.Arguments += ' -Stop' }
        $shortcut.WorkingDirectory = $projectRoot
        $shortcut.Description = "$action the local CV Tailor GUI"
        $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,1"
        $shortcut.Save()
        Write-Output (Join-Path $folder "$name.lnk")
    }
}

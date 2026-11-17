# Launch only the Streamlit GUI. The API is optional (ADR 0020).
[CmdletBinding()]
param([switch]$Stop, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$appPath = Join-Path $projectRoot 'ui\app.py'
$logs = Join-Path $projectRoot '.runtime\logs'

try {
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Python environment missing. Run python scripts/setup.py from the project folder.'
    }
    # Read the port with the same dotenv semantics as the existing launcher.
    $portText = & $python -c "import os,sys; from pathlib import Path; from dotenv import load_dotenv; load_dotenv(Path(sys.argv[1])/'.env'); print(int(os.getenv('UI_PORT', '8501')))" $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Could not read UI_PORT from .env.' }
    $port = [int]$portText
    if ($port -lt 1 -or $port -gt 65535) { throw 'UI_PORT must be between 1 and 65535.' }
    $url = "http://127.0.0.1:$port"
    $listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
    if ($listeners.Count -gt 0) {
        $ownerIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
        foreach ($ownerId in $ownerIds) {
            $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $ownerId"
            if (-not $owner -or $owner.CommandLine -notlike '*-m streamlit run*' -or
                $owner.CommandLine.IndexOf($appPath, [StringComparison]::OrdinalIgnoreCase) -lt 0) {
                throw "Port $port belongs to another program. Stop it or change UI_PORT in .env."
            }
        }
        if ($Stop) {
            foreach ($ownerId in $ownerIds) { Stop-Process -Id $ownerId }
            Write-Output 'CV Tailor GUI stopped.'
            exit 0
        }
    } elseif ($Stop) {
        Write-Output 'CV Tailor GUI is already stopped.'
        exit 0
    } else {
        New-Item -ItemType Directory -Force -Path $logs | Out-Null
        # A shortcut must work without a terminal and without inheriting its cwd.
        $arguments = '-m streamlit run "{0}" --server.address 127.0.0.1 --server.port {1} --server.headless true --browser.gatherUsageStats false' -f $appPath, $port
        $started = Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs 'gui.stdout.log') -RedirectStandardError (Join-Path $logs 'gui.stderr.log')
    }
    $ready = $false
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try {
            $response = Invoke-WebRequest "$url/_stcore/health" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200 -and $response.Content.Trim() -eq 'ok') {
                $ready = $true
                break
            }
        } catch { }
        if ($started -and $started.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        if ($started -and -not $started.HasExited) { $started.Kill() }
        throw "GUI did not become ready. See $logs\gui.stderr.log and gui.stdout.log."
    }
    if (-not $NoBrowser) { Start-Process $url }
    Write-Output "CV Tailor GUI ready: $url"
} catch {
    if ($NoBrowser) { Write-Error $_ -ErrorAction Continue } else {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, 'CV Tailor', 'OK', 'Error') | Out-Null
    }
    exit 1
}

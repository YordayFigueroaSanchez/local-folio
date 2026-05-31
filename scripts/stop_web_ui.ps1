$stopped = $false

# Stop listener process on UI port when available.
try {
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $listenerIds = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique

        foreach ($listenerId in ($listenerIds | Where-Object { $_ -ne $null })) {
            Stop-Process -Id $listenerId -Force -ErrorAction SilentlyContinue
            $stopped = $true
        }
    }
} catch {
    # Ignore and continue with fallback detection.
}

# Fallback: stop python processes running web_ui_server.py.
try {
    $pythonProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and
            $_.CommandLine -and
            $_.CommandLine -match "scripts[\\/]+web_ui_server\\.py"
        }

    foreach ($proc in $pythonProcesses) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        $stopped = $true
    }
} catch {
    # Ignore and report final status.
}

if ($stopped) {
    Write-Host "UI detenida."
} else {
    Write-Host "No se encontro proceso activo de la UI."
}

exit 0

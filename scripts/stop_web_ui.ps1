param(
    [int]$Port = 8765
)

$stopped = $false

# Stop listener process on UI port when available.
try {
    if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
        $listenerIds = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique

        foreach ($listenerId in ($listenerIds | Where-Object { $_ -ne $null })) {
            Stop-Process -Id $listenerId -Force -ErrorAction SilentlyContinue
            $stopped = $true
        }
    }
} catch {
    # Ignore and continue with fallback detection.
}

# Fallback: stop python processes running web_ui_server.py on this port.
# El puerto 8765 tambien matchea instancias lanzadas sin --port explicito
# (ese es el default), para no romper el comportamiento previo.
try {
    $portArgPattern = [regex]::Escape("--port $Port")
    $pythonProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            ($_.Name -eq "python.exe" -or $_.Name -eq "pythonw.exe") -and
            $_.CommandLine -and
            $_.CommandLine -match "scripts[\\/]+web_ui_server\.py" -and
            (
                $_.CommandLine -match $portArgPattern -or
                ($Port -eq 8765 -and $_.CommandLine -notmatch "--port")
            )
        }

    foreach ($proc in $pythonProcesses) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
        $stopped = $true
    }
} catch {
    # Ignore and report final status.
}

if ($stopped) {
    Write-Host "UI detenida (puerto $Port)."
} else {
    Write-Host "No se encontro proceso activo de la UI en el puerto $Port."
}

exit 0

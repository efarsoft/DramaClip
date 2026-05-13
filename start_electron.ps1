$p = "D:\DramaClip"
$e = "$p\node_modules\electron\dist\electron.exe"
$args = "$p\dist-electron\main\app.js"
if (-not (Test-Path $e)) {
    $e = "$p\node_modules\.bin\electron.cmd"
    $args = "."
}
Write-Host "Starting: $e $args"
Start-Process -WindowStyle Normal -FilePath $e -ArgumentList $args -WorkingDirectory $p
Start-Sleep -Seconds 3
$proc = Get-Process electron -ErrorAction SilentlyContinue
if ($proc) {
    Write-Host "Electron running: PID=$($proc.Id)"
} else {
    Write-Host "Electron NOT running, check for errors"
}

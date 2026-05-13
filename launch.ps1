$proc = Start-Process -FilePath "D:\DramaClip\node_modules\.bin\electron.cmd" -ArgumentList "D:\DramaClip" -WorkingDirectory "D:\DramaClip" -WindowStyle Normal -PassThru
Start-Sleep -Seconds 2
if ($proc.HasExited) {
    Write-Host "Process exited with code: $($proc.ExitCode)"
} else {
    Write-Host "Electron running with PID: $($proc.Id)"
}

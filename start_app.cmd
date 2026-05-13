@echo off
subst X: D:\DramaClip >nul 2>nul
start "" "X:\node_modules\.bin\electron.cmd" "X:\"
echo Electron started!

@echo off
rem Launch script for DramaClip - works around UNC path limitation
cd /d D:\DramaClip
if errorlevel 1 (
  subst Q: D:\DramaClip
  cd /d Q:\
)
start "DramaClip" /B node_modules\.bin\electron.cmd "D:\DramaClip"
exit /b 0

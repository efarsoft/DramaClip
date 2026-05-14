import subprocess, sys, os

# Try to install faster-whisper
try:
    from faster_whisper import WhisperModel
    print("ALREADY_INSTALLED")
except ImportError:
    print("Installing faster-whisper...")
    r = subprocess.run([sys.executable, "-m", "pip", "install", "faster-whisper"], 
                      capture_output=True, text=True)
    if r.returncode == 0:
        print("INSTALL_OK")
    else:
        print(f"INSTALL_FAILED: {r.stderr[-300:]}")

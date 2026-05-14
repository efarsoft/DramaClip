"""检查 Python 环境和安装 faster-whisper"""
import sys
import subprocess
import os

print(f"Python: {sys.executable}")
print(f"Version: {sys.version}")

# Check if we should install
try:
    from faster_whisper import WhisperModel
    print("faster-whisper already installed!")
except ImportError:
    print("faster-whisper NOT installed. Installing...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "faster-whisper"],
        capture_output=True, text=True
    )
    print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    if result.returncode != 0:
        print(f"STDERR: {result.stderr[-500:]}")
        sys.exit(1)
    print("Installation complete!")
    
# Verify import
from faster_whisper import WhisperModel
print("faster-whisper import OK!")

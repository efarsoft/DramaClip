import sys, subprocess, os

log_path = r"D:\_install_log.txt"
with open(log_path, "w", encoding="utf-8") as f:
    f.write(f"Python: {sys.executable}\n")
    f.write(f"Version: {sys.version}\n")
    try:
        from faster_whisper import WhisperModel
        f.write("faster-whisper already installed!\n")
    except ImportError:
        f.write("Installing faster-whisper...\n")
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "faster-whisper"],
            capture_output=True, text=True, timeout=300
        )
        f.write(r.stdout[-1000:] + "\n")
        f.write(r.stderr[-1000:] + "\n")
        if r.returncode == 0:
            f.write("Install OK!\n")
        else:
            f.write(f"FAILED exit={r.returncode}\n")
            sys.exit(1)
    # Verify
    from faster_whisper import WhisperModel
    f.write("faster-whisper import OK!\n")
print("Done - check D:\\_install_log.txt", flush=True)

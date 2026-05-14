"""检查 faster-whisper 是否已安装"""
try:
    from faster_whisper import WhisperModel
    print("faster-whisper OK")
except ImportError as e:
    print(f"NOT INSTALLED: {e}")

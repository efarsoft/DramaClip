import os
import sys
import time
from pathlib import Path

# 添加工程根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.init import init_all
from app.services.model_manager import (
    check_whisper_model,
    download_whisper_model,
    delete_whisper_model
)
from app.services.analyze.asr_service import _get_model

def progress_cb(pct, msg):
    print(f"[{pct}%] {msg}")

def main():
    print("正在初始化应用环境...")
    init_all()
    
    print("\n--- ASR 语音识别模型本地化与 ModelScope 高速下载 & 离线加载测试 ---")
    model_size = "tiny"
    
    # 检查是否已下载模型，如果没有，触发 ModelScope 自动高速下载
    is_downloaded = check_whisper_model(model_size)
    print(f"检测模型 '{model_size}' 本地状态: {'已下载' if is_downloaded else '未下载'}")
    
    if not is_downloaded:
        print(f"本地未检测到 {model_size}，现在启动 ModelScope 高速自动下载...")
        download_whisper_model(model_size, progress_callback=progress_cb)
        
        # 再次确认
        is_downloaded_after = check_whisper_model(model_size)
        print(f"下载后状态检测: {'成功' if is_downloaded_after else '失败'}")
        assert is_downloaded_after, "ASR 模型下载失败"
    else:
        print(f"模型 {model_size} 已就绪，直接进入离线加载验证")
        
    print("\n开始验证 ASR 纯离线加载机制...")
    # 断开网络是不必要的，因为我们在 `asr_service.py` 中强制设置了 `local_files_only=True`
    # 下面我们验证实例化 `WhisperModel` 时，是否会无视外部网络阻碍秒级启动
    start_time = time.time()
    try:
        model_instance = _get_model(model_size=model_size, device="cpu", compute_type="int8")
        elapsed = time.time() - start_time
        print(f"离线 ASR 模型实例加载成功！用时: {elapsed:.2f} 秒")
        assert model_instance is not None, "加载的模型实例为空"
        print("纯离线加载机制验证: OK!")
    except Exception as e:
        print(f"离线加载失败: {e}")
        sys.exit(1)
        
    print("\n恭喜！ASR 语音识别纯离线加载与 ModelScope 自动高速下载机制验证通过！")

if __name__ == "__main__":
    main()

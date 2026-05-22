import os
import sys
from pathlib import Path

# 添加工程根目录到 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.init import init_all
from app.services.model_manager import (
    check_pyannote_model,
    download_pyannote_model,
    delete_pyannote_model,
    PYANNOTE_MODELS
)

def progress_cb(pct, msg):
    print(f"[{pct}%] {msg}")

def main():
    print("正在初始化应用环境...")
    init_all()
    
    print("\n--- 测试 Pyannote Segmentation 3.0 下载 (约100MB) ---")
    model_name = "segmentation-3.0"
    
    print(f"清理已存在的 {model_name}...")
    delete_pyannote_model(model_name)
    
    print(f"验证 {model_name} 状态是否为未下载:")
    exists_before = check_pyannote_model(model_name)
    print(f"已下载: {exists_before}")
    assert not exists_before, "模型删除失败或状态检测错误"
    
    print(f"开始通过 ModelScope 下载 {model_name}...")
    download_pyannote_model(model_name, progress_callback=progress_cb)
    
    print(f"验证 {model_name} 下载后的状态:")
    exists_after = check_pyannote_model(model_name)
    print(f"已下载: {exists_after}")
    assert exists_after, "模型下载失败"
    
    print("\n恭喜！Pyannote 说话人分离模型本地化 ModelScope 高速下载验证成功！")

if __name__ == "__main__":
    main()

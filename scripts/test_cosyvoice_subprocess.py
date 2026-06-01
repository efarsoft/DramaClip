"""
Phase 3.1 验证脚本：测试 CosyVoice Subprocess 隔离后端

用法（在项目根目录）：
python scripts/test_cosyvoice_subprocess.py

会尝试：
1. 检查 is_available
2. 如果不可用，提示运行安装
3. 如果可用，尝试生成一段短音频并保存
"""

import sys
from pathlib import Path

# 确保能导入 app
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.tts.engines.cosyvoice.backend import CosyVoiceSubprocessBackend
from app.services.tts.registry import list_backends

def main():
    print("=== CosyVoice Subprocess 隔离后端验证 ===")

    # 1. 检查 registry
    backends = list_backends()
    sub = next((b for b in backends if b["id"] == "cosyvoice_subprocess"), None)
    if sub:
        print(f"Registry 发现: {sub['display_name']}")
        print(f"  isolation_mode: {sub.get('isolation_mode')}")
        print(f"  available: {sub.get('available')}")
        if not sub.get('available'):
            print(f"  reason: {sub.get('reason')}")
            print(f"  install_hint: {sub.get('install_hint')[:100]}...")
    else:
        print("错误：未在 registry 中找到 cosyvoice_subprocess")
        return

    # 2. 直接检查 backend
    backend = CosyVoiceSubprocessBackend()
    ok, msg = backend.is_available()
    print(f"\nis_available(): {ok} - {msg}")

    if not ok:
        print("\n请先执行安装：")
        print("  python -c \"from app.services.tts.engines.cosyvoice.backend import install_cosyvoice_isolated_runtime; install_cosyvoice_isolated_runtime()\"")
        return

    # 3. 尝试生成（需要模型已下载）
    print("\n尝试生成测试音频（需要 Fun-CosyVoice3 模型已下载）...")
    try:
        audio = backend.generate("你好，这是一个隔离进程测试。", speed=1.0)
        print(f"生成成功！音频形状: {audio.shape}, 采样率: {backend.sample_rate}")

        # 保存测试文件
        import torchaudio
        out_path = Path("test_cosyvoice_subprocess_output.wav")
        torchaudio.save(str(out_path), audio, backend.sample_rate)
        print(f"已保存测试音频到: {out_path}")
    except Exception as e:
        print(f"生成失败（可能是模型未下载或 sidecar 问题）: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()

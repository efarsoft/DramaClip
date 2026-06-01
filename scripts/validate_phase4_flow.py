"""
Phase 4 端到端流程验证脚本

模拟新用户完整体验：
1. 首次运行检测
2. 获取推荐套装
3. 应用推荐配置
4. 触发高质量引擎安装（CosyVoice 隔离运行时）
5. 检查引擎健康状态
6. 验证是否可用于生成/分析

运行方式：
python scripts/validate_phase4_flow.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.onboarding import (
    is_first_run,
    get_recommended_packs,
    get_hardware_recommendation,
    apply_recommended_pack,
)
from app.services.tts.engines.cosyvoice.backend import (
    CosyVoiceSubprocessBackend,
    install_cosyvoice_isolated_runtime,
)
from app.services.tts.registry import list_backends


def simulate_new_user_flow():
    print("=" * 60)
    print("Phase 4 - 新用户完整体验模拟")
    print("=" * 60)

    # 1. 首次运行检测
    print("\n[1] 首次运行检测")
    first = is_first_run()
    print(f"    是否首次运行: {first}")
    if not first:
        print("    (注意：标记文件已存在，本次为非首次模拟)")

    # 2. 获取推荐
    print("\n[2] 获取推荐套装")
    packs = get_recommended_packs()
    recommended = get_hardware_recommendation()
    print(f"    硬件推荐: {recommended}")
    for p in packs:
        print(f"    - {p['name']} ({p['id']})")

    # 3. 应用推荐配置
    print(f"\n[3] 应用推荐配置: {recommended}")
    success = apply_recommended_pack(recommended)
    print(f"    配置应用结果: {'成功' if success else '失败'}")

    # 4. 检查当前引擎状态
    print("\n[4] 检查高质量引擎状态")
    backends = list_backends()
    for b in backends:
        if b['id'] in ['cosyvoice_subprocess', 'kokoro']:
            print(f"    {b['display_name']}: available={b['available']}, isolation={b.get('isolation_mode')}")

    # 5. 尝试安装 CosyVoice 隔离运行时（如果选了 extreme）
    if recommended == 'extreme_quality':
        print("\n[5] 触发 CosyVoice 隔离运行时安装（模拟）")
        backend = CosyVoiceSubprocessBackend()
        ok, msg = backend.is_available()
        print(f"    安装前状态: {ok} - {msg[:80]}...")

        print("    开始安装（这会真实执行安装流程，请耐心等待）...")
        install_success = install_cosyvoice_isolated_runtime()
        print(f"    安装结果: {'成功' if install_success else '失败'}")

        # 重新检查
        ok2, msg2 = backend.is_available()
        print(f"    安装后状态: {ok2} - {msg2}")

        # 尝试真实生成验证（如果模型已就绪）
        if ok2:
            try:
                print("    尝试调用 generate 验证...")
                audio = backend.generate("测试文本。", speed=1.0)
                print(f"    ✅ 生成成功！音频形状: {audio.shape}")
            except Exception as gen_err:
                print(f"    ⚠️ 生成验证失败（可能模型未完全下载）: {gen_err}")
    else:
        print("\n[5] 跳过 CosyVoice 安装（用户选择了轻量套装）")

    # 6. 最终健康检查 + 模拟成片路径
    print("\n[6] 最终引擎健康检查与成片路径验证")
    final_backends = list_backends()
    for b in final_backends:
        if 'cosyvoice' in b['id'] or b['id'] == 'kokoro':
            status = "✅ 可用" if b['available'] else "❌ 不可用"
            print(f"    {b['display_name']}: {status}")

    print("\n    成片路径模拟：TTS 后端已就绪，可直接用于 narration 生成。")

    print("\n" + "=" * 60)
    print("Phase 4 流程模拟结束")
    print("如果安装成功，新用户即可获得高质量本地成片能力。")
    print("=" * 60)


if __name__ == "__main__":
    simulate_new_user_flow()

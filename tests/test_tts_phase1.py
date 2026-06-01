"""
Phase 1 verification script for TTSBackend + Registry (OmniVoice-Studio aligned)
Run: python tests/test_tts_phase1.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    print("=== DramaClip Phase 1 TTS Registry Verification ===\n")

    # 1. Import
    from app.services.tts import (
        list_backends,
        get_active_tts_backend,
        TTSBackend,
        register_backend,
    )
    print("[OK] Imports from app.services.tts succeeded")

    # 2. List backends (the rich list)
    backends = list_backends()
    print(f"\n[OK] list_backends() returned {len(backends)} entries (including future local targets):")
    for b in backends:
        status = "READY" if b["available"] else "NOT READY"
        hint = b.get("install_hint") or b.get("reason") or ""
        print(f"  - {b['id']:<18} {status:<10}  {b['display_name']}")
        if hint:
            print(f"      hint: {hint[:80]}...")

    # 3. Active backend instantiation
    try:
        active = get_active_tts_backend()
        print(f"\n[OK] get_active_tts_backend() -> {active.id} ({active.__class__.__name__})")
        print(f"     sample_rate={active.sample_rate}, gpu_compat={active.gpu_compat}")
    except Exception as e:
        print(f"\n[ERROR] get_active_tts_backend failed: {e}")
        return 1

    # 4. Basic generate smoke (edge should always work)
    try:
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            vf = os.path.join(td, "phase1_smoke.wav")
            # Edge backend
            edge_cls = [b for b in backends if b["id"] == "edge_tts"][0]
            # We call via active if it's edge, else force
            if active.id == "edge_tts":
                tensor = active.generate("你好，这是 Phase 1 验证。", voice_name="zh-CN-XiaoxiaoNeural", voice_file=vf, speed=1.0)
            else:
                from app.services.tts.backends.edge import EdgeTTSBackend
                edge = EdgeTTSBackend()
                tensor = edge.generate("你好，这是 Phase 1 验证。", voice_name="zh-CN-XiaoxiaoNeural", voice_file=vf, speed=1.0)
            print(f"\n[OK] generate() returned tensor shape={tuple(tensor.shape)}, dtype={tensor.dtype}")
            print(f"     voice_file exists: {os.path.exists(vf)}")
    except Exception as e:
        print(f"\n[ERROR] generate smoke test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n=== Phase 1 VERIFICATION PASSED (core registry + adapters working) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())

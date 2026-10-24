"""music 域模型登记与 registry 分支：四件套入册、engine_ready、探测判据。"""

from __future__ import annotations

from pathlib import Path

from dramaclip.infra.model_manager.registry import builtin_specs, detect_status, engine_ready

_MUSIC_IDS = {"acestep-v15", "acestep-v15-vae", "acestep-text-encoder", "acestep-lm-06b"}


def _spec(model_id: str):
    found = [s for s in builtin_specs() if s.model_id == model_id]
    assert len(found) == 1, f"{model_id} 应恰好在册一条"
    return found[0]


def test_four_acestep_specs_registered_as_music() -> None:
    music = [s for s in builtin_specs() if s.kind == "music"]
    assert {s.model_id for s in music} == _MUSIC_IDS
    assert all(s.engine == "acestep" for s in music)


def test_music_specs_are_dual_source_and_whitelisted() -> None:
    for model_id in _MUSIC_IDS:
        spec = _spec(model_id)
        kinds = {kind for kind, _repo in spec.sources()}
        assert kinds == {"modelscope", "hf_mirror", "huggingface"}, model_id
        assert spec.download_files, f"{model_id} 必须锁下载白名单（整仓下载是灾难）"


def test_engine_ready_true_for_music_kind() -> None:
    """配乐运行时接线判据与 vision 同哲学：文件在场是实 gate，registry 侧不拦。"""
    assert engine_ready(_spec("acestep-v15")) is True


def test_detect_status_recognizes_layouts(tmp_path: Path) -> None:
    # DiT：平铺权重
    dit = tmp_path / "music" / "acestep-v15-sft"
    dit.mkdir(parents=True)
    (dit / "model.safetensors").write_bytes(b"w")
    assert detect_status(tmp_path, _spec("acestep-v15"))["status"] == "installed"
    # VAE：主仓子目录前缀保留落盘 + .ckpt 不在册（diffusers safetensors 才是正身）
    vae = tmp_path / "music" / "acestep-vae" / "vae"
    vae.mkdir(parents=True)
    (vae / "diffusion_pytorch_model.safetensors").write_bytes(b"w")
    assert detect_status(tmp_path, _spec("acestep-v15-vae"))["status"] == "installed"
    # 文本编码器：上游硬编码目录名一层
    te = tmp_path / "music" / "acestep-text-encoder" / "Qwen3-Embedding-0.6B"
    te.mkdir(parents=True)
    (te / "model.safetensors").write_bytes(b"w")
    assert detect_status(tmp_path, _spec("acestep-text-encoder"))["status"] == "installed"


def test_placement_names_align_with_upstream_hardcoded_names() -> None:
    """placement 尾段/白名单前缀与上游注册名逐一对齐——改名即断链的守卫。"""
    assert _spec("acestep-v15").placement == "music/acestep-v15-sft"
    vae = _spec("acestep-v15-vae")
    assert vae.download_files[0].startswith("vae/")
    te = _spec("acestep-text-encoder")
    assert te.download_files[0].startswith("Qwen3-Embedding-0.6B/")
    assert _spec("acestep-lm-06b").placement == "music/acestep-5Hz-lm-0.6B"

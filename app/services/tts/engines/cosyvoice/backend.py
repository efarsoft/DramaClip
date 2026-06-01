"""
CosyVoiceSubprocessBackend

使用进程隔离方式运行 Fun-CosyVoice3 的 DramaClip 后端实现。

当前状态：骨架 + 协议验证通过。
后续会在这里接入真正的 CosyVoice 推理（延迟加载）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Tuple

from app.services.tts.tts_backend import register_backend
from app.services.tts.subprocess.subprocess_tts_backend import SubprocessTTSBackend
from app.services.tts.subprocess.cosyvoice_runtime_installer import (
    get_cosyvoice_python,
    is_runtime_ready,
    install_cosyvoice_runtime,
    get_install_instructions,
)


class CosyVoiceSubprocessBackend(SubprocessTTSBackend):
    """
    进程隔离版本的 CosyVoice3 后端。

    目前使用占位 sidecar（返回静音），用于验证整个隔离架构。
    真正推理逻辑后续会加到 sidecar main.py 中。
    """

    id = "cosyvoice_subprocess"
    display_name = "CosyVoice 3（进程隔离 · 高质量推荐）"

    supports_voice_cloning = True
    supports_voice_design = True
    supports_instruct = True
    gpu_compat = ("cuda", "mps", "cpu")

    required_model_repo = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"

    _DEFAULT_SAMPLE_RATE = 22050

    @classmethod
    def venv_python(cls) -> Path:
        """
        优先返回用户通过“一键安装”创建的专属 CosyVoice venv。
        如果不存在，回退到当前 Python（用于快速测试）。
        """
        dedicated = get_cosyvoice_python()
        if dedicated and dedicated.exists():
            return dedicated

        import sys
        return Path(sys.executable)

    @classmethod
    def sidecar_script(cls) -> Path:
        return Path(__file__).parent / "main.py"

    @property
    def sample_rate(self) -> int:
        return self._DEFAULT_SAMPLE_RATE

    @property
    def supported_languages(self) -> list[str]:
        return ["zh", "en", "multi"]

    @classmethod
    def is_available(cls) -> Tuple[bool, str]:
        """
        真正诚实的可用性检查（Phase 3.1 核心改进）。
        返回 (可用, 给用户的清晰提示)
        """
        script = cls.sidecar_script()
        if not script.exists():
            return False, f"隔离 sidecar 脚本缺失: {script}"

        ready, msg = is_runtime_ready()
        if ready:
            return True, "CosyVoice 3（进程隔离）已就绪"

        # 给出可操作的安装提示
        hint = (
            "CosyVoice 隔离运行时未就绪。\n"
            "推荐操作：在设置 → 模型管理 中找到 CosyVoice 引擎，点击“一键安装运行时”。\n"
            "或者手动按照以下指引操作：\n" + get_install_instructions()[:300] + "..."
        )
        return False, hint

    def generate(self, text: str, **kwargs) -> torch.Tensor:
        """
        通过 sidecar 生成语音，并传递模型目录。
        """
        # 获取模型目录
        model_dir = None
        try:
            from app.services.model_manager import resolve_model_path
            _resolved = resolve_model_path(self.required_model_repo)
            if _resolved:
                model_dir = str(_resolved)
        except Exception:
            pass
        if not model_dir:
            raise RuntimeError(f"CosyVoice 模型未找到: {self.required_model_repo}。请先在模型管理中下载。")

        with self._lock:
            self._spawn()
            msg = {
                "op": "synthesize",
                "text": text,
                "model_dir": model_dir,
            }
            for k, v in kwargs.items():
                if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                    msg[k] = v

            self._send(msg)
            reply = self._recv_with_timeout(120)  # 给推理更多时间

        if not reply:
            raise RuntimeError(f"{self.id} sidecar 在生成中关闭了管道")

        if reply.get("op") == "error":
            raise RuntimeError(f"{self.id} sidecar 错误: {reply.get('message')}")

        if reply.get("op") != "audio":
            raise RuntimeError(f"{self.id} sidecar 返回了意外的 op: {reply.get('op')}")

        pcm_b64 = reply.get("audio_pcm_b64", "")
        pcm = __import__("base64").b64decode(pcm_b64)
        arr = __import__("numpy").frombuffer(pcm, dtype="int16").astype("float32") / 32768.0
        tensor = torch.from_numpy(arr.copy()).unsqueeze(0)
        return tensor


# 自动注册
register_backend(CosyVoiceSubprocessBackend)


# 暴露给外部（Settings / IPC）调用的安装入口
def install_cosyvoice_isolated_runtime(
    progress_callback: Optional[Callable[[int, str], None]] = None,
) -> bool:
    """供 UI 调用的一键安装入口。"""
    from app.services.tts.subprocess.cosyvoice_runtime_installer import install_cosyvoice_runtime
    return install_cosyvoice_runtime(progress_callback=progress_callback)

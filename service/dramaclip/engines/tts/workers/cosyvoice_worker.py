"""CosyVoice 合成 worker：在隔离 venv（Python 3.11，torch 2.7.0 按机型选型）内运行。

协议（stdout 逐行 JSON，stdin 同；与 indextts_worker 逐字同形）：
  就绪行: {"ready": true, "device": "cuda"|"cpu", "sample_rate": 24000}
  请求:   {"id": "段id", "text": "...", "voice": "参考音频路径", "out": "输出wav路径", "lang": "zh"}
  应答:   {"id": "...", "ok": true} 或 {"id": "...", "ok": false, "error": "..."}

一次加载三件套权重（llm/flow/hift），进程常驻按行合成。stderr 只进诊断日志。

关键实现来自本机 Windows 已实测通过的组合（CPU 真合成验证）：
- 上游 checkout 固定 074ca6dc（tts_runtime.py 安装时解包），AutoModel 加载
  （300M 走 legacy 分支，Fun-CosyVoice3 走 v3 分支，同一入口）。
- transformers 5 的三个适配补丁：Qwen 权重先以 fp32 载入（bf16 构造会把训练
  权重不可逆舍入）、forward_one_step 的注意力掩码要拼回缓存前缀、CPU 上把
  llm/flow/hift 显式 float()。
- 产物统一重采样到 24000Hz 落盘（与能力声明一处口径）。
- 克隆走 cross_lingual：文本带 <|zh|> 语言标签前缀（v1/v2 模式要求）；免参考
  转写。zero_shot 需 prompt_text 槽位，留协议扩展后裁决。
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any


#: 上游仓库 checkout 根（tts_runtime.py 安装时解包到 runtimes/ 下），
#: 由桥进程经环境变量下发——worker 自己不猜数据目录。调用时解析：
#: import 期硬取会让无变量环境（单测/误直接跑）在 import 行就炸。
def _src_dir() -> Path:
    raw = os.environ.get("DRAMACLIP_COSYVOICE_SRC")
    if not raw:
        raise RuntimeError(
            "DRAMACLIP_COSYVOICE_SRC 未设置：本 worker 由引擎桥拉起，不单独运行"
            "（运行环境经引擎页「安装运行环境」安装）"
        )
    return Path(raw)

#: 统一落盘采样率（模型输出如不同，先重采样再写 wav）。
_SAMPLE_RATE = 24_000

_LANG_TAGS = {
    "zh": "<|zh|>", "en": "<|en|>", "ja": "<|ja|>", "ko": "<|ko|>", "yue": "<|yue|>",
}

_SYSTEM_PROMPT = "You are a helpful assistant."
_ENDOFPROMPT = "<|endofprompt|>"


def _tts_text(text: str, lang: str, is_v3: bool) -> str:
    """cross_lingual 的合成文本前缀：v1/v2 要语言标签（<|zh|>），v3 要系统提示词
    前缀（上游 v3 示例的固定写法）——两代不是同一套约定，混用即哑火。"""
    if is_v3:
        return text if _ENDOFPROMPT in text else f"{_SYSTEM_PROMPT}{_ENDOFPROMPT}{text}"
    tag = _LANG_TAGS.get(lang) or _LANG_TAGS.get(lang[:2], "<|zh|>")
    return f"{tag}{text}"


def _bootstrap_sys_path() -> None:
    """仓库根 + Matcha-TTS 子模块进 sys.path（上游 README 的 PYTHONPATH 套路）。"""
    src = _src_dir()
    matcha = src / "third_party" / "Matcha-TTS"
    for path in (str(src), str(matcha)):
        if Path(path).is_dir() and path not in sys.path:
            sys.path.insert(0, path)


def _probe_cuda() -> str:
    """真探针而非 is_available：老卡（Pascal cc5.2）会被认出但新 CUDA 栈无内核。"""
    import torch  # noqa: PLC0415

    if not torch.cuda.is_available():
        return "cpu"
    try:
        (torch.ones(4, device="cuda") * 2).sum().item()
        return "cuda"
    except Exception:  # noqa: BLE001 - 任何 CUDA 故障都按不可用处理，诚实回 CPU
        torch.cuda.empty_cache()
        print(">> CUDA 探针失败，回退 CPU", file=sys.stderr)
        return "cpu"


def _check() -> int:
    """--check 模式：只验证依赖可 import（桥的 runtime_ready 探针），不加载模型。"""
    _bootstrap_sys_path()
    import matcha.utils  # noqa: F401, PLC0415
    import torch  # noqa: F401, PLC0415
    import transformers  # noqa: F401, PLC0415
    from cosyvoice.cli.cosyvoice import AutoModel  # noqa: F401, PLC0415

    print("check-ok", file=sys.stderr)
    return 0


@contextlib.contextmanager
def _qwen_full_precision_load() -> Iterator[None]:
    """transformers 5 会按 checkpoint 的 bf16 构造 Qwen：先强制 fp32 载入。

    否则 llm.pt 的训练权重在构造期就被不可逆舍入，事后 float() 救不回来。
    """
    import torch  # noqa: PLC0415
    import transformers  # noqa: PLC0415

    qwen = getattr(transformers, "Qwen2ForCausalLM", None)
    if qwen is None:
        yield  # 没有 Qwen 的老栈（CosyVoice 1 旧环境）：什么都不用补
        return
    owned = qwen.__dict__.get("from_pretrained")
    original = qwen.from_pretrained

    def load(cls: Any, *args: Any, **kwargs: Any) -> Any:
        if "dtype" not in kwargs and "torch_dtype" not in kwargs:
            kwargs["torch_dtype"] = torch.float32
        return original(*args, **kwargs)

    qwen.from_pretrained = classmethod(load)
    try:
        yield
    finally:
        if owned is None:
            del qwen.from_pretrained
        else:
            qwen.from_pretrained = owned


def _repair_qwen_cache(model: Any) -> None:
    """新 transformers 把单 token 掩码按字面处理，会藏掉缓存里的文本/音色前缀——
    只修这一处实例方法，全量掩码保持上游行为。"""
    from cosyvoice.llm import llm as llm_module  # noqa: PLC0415

    qwen_encoder = getattr(llm_module, "Qwen2Encoder", None)
    if qwen_encoder is None:
        return
    components = getattr(model, "model", model)
    encoder = getattr(getattr(components, "llm", None), "llm", None)
    if not isinstance(encoder, qwen_encoder):
        return  # CosyVoice 1 用别的编码器
    original = encoder.forward_one_step

    def forward_one_step(xs: Any, masks: Any, cache: Any = None) -> Any:
        if cache is None or masks.shape[-1] == xs.shape[1]:
            return original(xs, masks, cache)
        length = (
            cache.get_seq_length() if hasattr(cache, "get_seq_length") else cache[0][0].shape[-2]
        )
        if not length:
            return original(xs, masks, cache)
        import torch  # noqa: PLC0415

        prefix = masks.new_ones((*masks.shape[:-1], length))
        return original(xs, torch.cat((prefix, masks), dim=-1), cache)

    encoder.forward_one_step = forward_one_step


def _load_model(model_dir: str, device: str) -> Any:
    import torch  # noqa: PLC0415
    from cosyvoice.cli.cosyvoice import AutoModel  # noqa: PLC0415

    with _qwen_full_precision_load():
        model = AutoModel(model_dir=model_dir)
    _repair_qwen_cache(model)
    if device == "cpu" or not torch.cuda.is_available():
        # Qwen 权重可能是 bf16 而 CPU 的 token 输入是 fp32；CUDA 精度不动
        components = getattr(model, "model", model)
        for name in ("llm", "flow", "hift"):
            component = getattr(components, name, None)
            if component is not None and hasattr(component, "float"):
                component.float()
    return model


def _main(model_dir: str, device: str, proto_fd: int) -> int:
    import torchaudio  # noqa: PLC0415
    from cosyvoice.utils.file_utils import load_wav  # noqa: PLC0415

    model = _load_model(model_dir, device)
    proto = os.fdopen(proto_fd, "w", encoding="utf-8")

    def send(obj: dict[str, object]) -> None:
        proto.write(json.dumps(obj, ensure_ascii=False) + "\n")
        proto.flush()

    send({"ready": True, "device": device, "sample_rate": _SAMPLE_RATE})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
            prompt = load_wav(job["voice"], 16000)
            lang = str(job.get("lang") or "zh").lower()
            is_v3 = type(model).__name__ == "CosyVoice3"
            chunks = list(
                model.inference_cross_lingual(
                    _tts_text(job["text"], lang, is_v3), prompt, stream=False
                )
            )
            if not chunks:
                raise RuntimeError("上游未产出任何语音段")
            result = chunks[-1]  # 非流式：只取最后一段完整产物
            import torch  # noqa: PLC0415

            speech = result["tts_speech"].reshape(-1).to(torch.float32).detach().cpu()
            native_rate = int(getattr(model, "sample_rate", _SAMPLE_RATE) or _SAMPLE_RATE)
            if native_rate != _SAMPLE_RATE:
                speech = torchaudio.functional.resample(speech, native_rate, _SAMPLE_RATE)
            torchaudio.save(job["out"], speech.unsqueeze(0), _SAMPLE_RATE)
            reply = {"id": job["id"], "ok": True}
        except Exception as exc:  # noqa: BLE001 - 逐段失败只回错误，进程不死（后续段继续）
            reply = {"id": job.get("id", "?"), "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        send(reply)
    return 0


def main() -> int:
    if "--check" in sys.argv:
        return _check()
    model_dir = sys.argv[1]
    device = sys.argv[2] if len(sys.argv) > 2 else "auto"

    # 库的进度信息（">> loading..." 等 print）走 stdout 会污染 JSON 协议——
    # 在 import 任何 cosyvoice 模块前把 fd 1 换成 stderr，协议行用真正的 stdout 写。
    proto_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    _bootstrap_sys_path()

    if device == "auto":
        device = _probe_cuda()
    return _main(model_dir, device, proto_fd)


if __name__ == "__main__":
    sys.exit(main())

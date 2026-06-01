# CosyVoice 3 Subprocess 隔离后端（Phase 3.1）

## 目标
让 Fun-CosyVoice3（目前中文短剧质量最强的开源 TTS 之一）真正实现“安装完成就能用”，解决传统方式下依赖冲突导致“模型下了但跑不起来”的问题。

## 架构
- 基于参考项目 OmniVoice-Studio 的 `SubprocessBackend` 设计。
- 主进程与 sidecar 通过**长度前缀 JSON** 协议通信（stdin/stdout）。
- Sidecar 运行在独立 Python 解释器（推荐专属 venv），彻底隔离依赖。
- `id = "cosyvoice_subprocess"`（在 registry 中可被 `get_active_tts_backend` 选中）。

## 当前状态（截至本次执行）
- ✅ SubprocessTTSBackend 基类（进程管理、协议、超时、错误处理）
- ✅ CosyVoice sidecar 支持真实推理（SFT / zero-shot / instruct2，lazy load）
- ✅ 一键安装运行时框架（自动创建 venv + git clone + pip install + Windows 提示）
- ✅ 诚实的 `is_available()` + 清晰的 install_hint
- ✅ IPC 接口 `cosyvoice:installRuntime`（带进度推送）
- ✅ 已集成到 `voice.py` 调用链和 `list_backends()`
- ⚠️ 仍需用户手动/一键触发安装（因为依赖较重）

## 使用方式（后端）

```python
from app.services.tts import get_active_tts_backend

# 方式1：直接使用
backend = get_active_tts_backend("cosyvoice_subprocess")
audio = backend.generate("你好世界", speed=1.0)

# 方式2：通过配置（推荐）
# 在 unified_config 或 settings 中设置 tts.engine = "cosyvoice_subprocess"
```

## 安装运行时

推荐通过前端模型管理调用 `cosyvoice:installRuntime`。

后端也可直接调用：
```python
from app.services.tts.engines.cosyvoice.backend import install_cosyvoice_isolated_runtime
install_cosyvoice_isolated_runtime(progress_callback=print)
```

安装位置：
- venv: `pretrained_models/.venvs/cosyvoice3`
- 源码: `pretrained_models/CosyVoice`

## 已知问题 / 注意事项
- Windows 上 sox 是最大坑，必须单独安装并加入 PATH。
- 模型仍需通过中央 catalog（FunAudioLLM/Fun-CosyVoice3-0.5B-2512）单独下载。
- 首次加载模型较慢（sidecar 会发送 progress 事件）。
- 目前 sidecar 仍使用与主进程相同的 Python 作为 fallback（生产应强制使用专属 venv）。

## 下一步计划（Phase 3 后续）
- 前端完整接线（模型管理页显示“一键安装”按钮 + 实时进度）
- 更强的 sidecar 进度上报和模型热更新
- 支持更多 CosyVoice 高级功能（emotion vector、speaker embedding 等）
- 把相同模式推广到其他重模型（IndexTTS2、FishSpeech 等）

## 验证脚本
项目根目录执行：
```bash
python scripts/test_cosyvoice_subprocess.py
```

---

**核心理念**（与整个 DramaClip 一致）：
质量第一 + 傻瓜化体验。通过隔离让“最高质量的本地引擎”真正可用，而不是只停留在“模型目录里有”。
"""
设置 Handler
处理用户配置和设置管理

配置管理策略：
1. settings.json 是唯一的用户配置存储（前端直接读写）
2. UnifiedConfig 是唯一的配置读取入口（所有后端服务）
3. config.toml 仅作为兼容性备份
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from app.ipc.protocol import RPCError


def _merge_config_into_settings(settings: Dict) -> None:
    """从 UnifiedConfig 读取配置并合并到 settings（仅首次初始化时使用）"""
    try:
        from app.config.unified_config import config as unified

        # 从 UnifiedConfig 获取 LLM 配置
        llm_cfg = unified.get("openai_protocol", {})
        
        openai_cfg = settings.setdefault("openai_protocol", {})
        if llm_cfg.get("api_key") and not openai_cfg.get("api_key"):
            openai_cfg["api_key"] = llm_cfg["api_key"]
        if llm_cfg.get("base_url") and not openai_cfg.get("base_url"):
            openai_cfg["base_url"] = llm_cfg["base_url"]
        if llm_cfg.get("model") and not openai_cfg.get("model"):
            openai_cfg["model"] = llm_cfg["model"]
        openai_cfg.setdefault("max_tokens", 4096)
        openai_cfg.setdefault("temperature", 0.7)
    except Exception:
        logger.warning("[Settings] Failed to merge UnifiedConfig", exc_info=True)


def _sync_settings_to_config(settings: Dict) -> None:
    """将 settings.json 的配置同步到 UnifiedConfig 并保存到 config.toml（兼容性保留）"""
    try:
        from app.config.unified_config import reload_config
        
        # 触发 UnifiedConfig 重新加载
        reload_config()
        logger.info("[Settings] Reloaded UnifiedConfig")
    except Exception:
        logger.warning("[Settings] Failed to reload UnifiedConfig", exc_info=True)


def settings_get() -> Dict:
    """获取设置（从 config.toml 和 settings.json 联合读取）

    Returns:
        用户设置字典
    """
    logger.info("[Settings] Getting settings")

    settings_file = Path.home() / ".dramaclip" / "settings.json"
    if settings_file.exists():
        try:
            raw = json.loads(settings_file.read_text(encoding="utf-8"))
            if "openai_protocol" in raw and "output" in raw and "tts" in raw:
                _merge_config_into_settings(raw)
                if "custom_models" not in raw:
                    raw["custom_models"] = {"asr": [], "tts": []}
                else:
                    if "asr" not in raw["custom_models"]:
                        raw["custom_models"]["asr"] = []
                    if "tts" not in raw["custom_models"]:
                        raw["custom_models"]["tts"] = []
                return raw
            return _upgrade_settings(raw)
        except Exception as e:
            logger.debug(f"[Settings] Failed to load settings: {e}")

    settings = _default_settings()
    _merge_config_into_settings(settings)
    return settings


def _default_settings() -> Dict:
    """新版嵌套结构的默认设置 - 与 UnifiedConfig 保持一致"""
    return {
        # LLM 协议配置
        "openai_protocol": {
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "max_tokens": 4096,
            "temperature": 0.7,
            "enabled": True,
        },
        "anthropic_protocol": {
            "api_key": "",
            "base_url": "",
            "model": "claude-3-5-sonnet-latest",
            "max_tokens": 4096,
            "temperature": 0.7,
            "enabled": False,
        },
        # Vision LLM 配置（用于视频分析）
        "vision": {
            "llm_provider": "openai",
            "openai_api_key": "",
            "openai_model_name": "Qwen/Qwen3.5-122B-A10B",
            "openai_base_url": "https://api.siliconflow.cn/v1",
            "analysis_prompt": "",
        },
        # Text LLM 配置（用于文本生成）
        "text": {
            "llm_provider": "openai",
            "openai_api_key": "",
            "openai_model_name": "Pro/zai-org/GLM-5",
            "openai_base_url": "https://api.siliconflow.cn/v1",
        },
        # 素材源配置
        "material": {
            "pexels_api_keys": [],
            "pixabay_api_keys": [],
            "directory": "",
        },
        # TTS 配置
        "tts": {
            "enabled": True,
            "engine": "kokoro",       # 本地轻量中文 TTS 首选（82MB，极快）；edge_tts 作为云端兜底
            "voice": "zf_001",
            "speed": 1.0,
            "pitch": 1.0,
        },
        # ASR 配置
        "asr": {
            "enabled": True,
            "engine": "sensevoice",      # faster_whisper | sensevoice
            "model": "SenseVoice-large",  # whisper: tiny/base/small/medium/large-v3
                                         # sensevoice: SenseVoice-small/SenseVoice-large
            "language": "auto",
            "translate": False,
            "enable_emotion": True,      # SenseVoice 专有
            "enable_audio_events": True, # SenseVoice 专有
        },
        # ViT 配置
        "vit": {
            "enabled": True,
            "provider": "openai_protocol",
            "model": "qwen-vl-max",
            "batch_size": 4,
        },
        # 输出配置
        "output": {
            "path": str(Path.home() / "DramaClip" / "Outputs"),
            "quality": "1080p",
            "format": "mp4",
            "fps": 30,
            "codec": "h264",
        },
        # 硬件配置
        "hardware": {
            "enabled": True,
            "ffmpeg_hwaccel": "auto",
            "gpu_device": "0",
            "threads": 4,
            "max_workers": 5,
        },
        # 自定义模型
        "custom_models": {
            "asr": [],
            "tts": [],
        },
    }


def _upgrade_settings(flat: Dict) -> Dict:
    """将旧版扁平设置升级到新版嵌套结构"""
    defaults = _default_settings()
    result = dict(defaults)

    MAPPING = {
        "openai_api_key": ("openai_protocol", "api_key"),
        "gemini_api_key": ("anthropic_protocol", "api_key"),
        "default_output_path": ("output", "path"),
        "default_quality": ("output", "quality"),
        "tts_engine": ("tts", "engine"),
        "voice_name": ("tts", "voice"),
    }

    for old_key, (section, field) in MAPPING.items():
        if old_key in flat and flat[old_key]:
            result[section][field] = flat[old_key]

    try:
        settings_file = Path.home() / ".dramaclip" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.debug(f"[Settings] Failed to save upgraded settings: {e}")

    return result


def settings_update(settings: Optional[Dict[str, Any]] = None, **kwargs) -> Dict:
    """更新设置（同步 LLM 配置到 config.toml，并热更新统一配置）

    Args:
        settings: 新的设置字典
        **kwargs: 兼容直接解包传入的设置字段

    Returns:
        更新结果
    """
    logger.info("[Settings] Updating settings")
    if settings is None:
        settings = kwargs

    _sync_settings_to_config(settings)

    settings_file = Path.home() / ".dramaclip" / "settings.json"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 热更新统一配置
    try:
        from app.config.unified_config import reload_config
        reload_config()
        logger.info("[Settings] 统一配置已热更新")
    except Exception as e:
        logger.warning(f"[Settings] 统一配置热更新失败: {e}")

    logger.info("[Settings] Settings updated")
    return {"success": True}

"""
统一配置访问模块
P0 核心：解决 config.toml 和 settings.json 两套配置系统的问题

策略：
1. settings.json 作为唯一配置源（前端操作的配置）
2. LLMServiceManager 直接读取 settings.json
3. config.toml 作为备份配置（仅在 settings.json 不存在时使用）
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple
from loguru import logger


class ConfigValidationError(Exception):
    """配置验证错误"""
    pass


class UnifiedConfig:
    """
    统一配置访问器

    所有服务应该从这个类读取配置，而不是直接读取 config.toml 或 settings.json
    """

    _instance: Optional["UnifiedConfig"] = None
    _settings: Dict[str, Any] = {}
    _validation_errors: List[str] = []

    # 必需配置项
    REQUIRED_SECTIONS = ["openai_protocol", "output"]
    
    # 配置验证规则
    VALIDATION_RULES = {
        "openai_protocol.api_key": {
            "type": str,
            "required": False,
            "message": "OpenAI API Key 未配置，部分 AI 功能将不可用",
        },
        "openai_protocol.base_url": {
            "type": str,
            "required": False,
            "default": "https://api.openai.com/v1",
        },
        "output.path": {
            "type": str,
            "required": True,
            "message": "输出路径未配置",
        },
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_settings()
        return cls._instance

    def _load_settings(self):
        """加载 settings.json"""
        settings_file = Path.home() / ".dramaclip" / "settings.json"

        if settings_file.exists():
            try:
                self._settings = json.loads(settings_file.read_text(encoding="utf-8"))
                logger.debug("[Config] 从 settings.json 加载配置")
                self._sync_path_manager_output()
                return
            except Exception as e:
                logger.warning(f"[Config] 加载 settings.json 失败: {e}")

        # 降级：从 config.toml 加载
        self._load_from_config_toml()

    def _load_from_config_toml(self):
        """从 config.toml 降级加载（兼容旧配置）"""
        try:
            from app.config import config as cfg

            self._settings = {
                # LLM 协议配置
                "openai_protocol": {
                    "api_key": cfg.app.get("vision_openai_api_key", ""),
                    "base_url": cfg.app.get("vision_openai_base_url", ""),
                    "model": cfg.app.get("text_openai_model_name", "gpt-4o"),
                    "max_tokens": 4096,
                    "temperature": 0.7,
                    "enabled": True,
                },
                "anthropic_protocol": {
                    "api_key": cfg.app.get("gemini_api_key", ""),
                    "base_url": "",
                    "model": "claude-3-5-sonnet-latest",
                    "max_tokens": 4096,
                    "temperature": 0.7,
                    "enabled": False,
                },
                # Vision LLM 配置（从 config.toml [app] 段迁移）
                "vision": {
                    "llm_provider": cfg.app.get("vision_llm_provider", "openai"),
                    "openai_api_key": cfg.app.get("vision_openai_api_key", ""),
                    "openai_model_name": cfg.app.get("vision_openai_model_name", "Qwen/Qwen3.5-122B-A10B"),
                    "openai_base_url": cfg.app.get("vision_openai_base_url", "https://api.siliconflow.cn/v1"),
                    "analysis_prompt": cfg.app.get("vision_analysis_prompt", ""),
                },
                # Text LLM 配置（从 config.toml [app] 段迁移）
                "text": {
                    "llm_provider": cfg.app.get("text_llm_provider", "openai"),
                    "openai_api_key": cfg.app.get("text_openai_api_key", ""),
                    "openai_model_name": cfg.app.get("text_openai_model_name", "Pro/zai-org/GLM-5"),
                    "openai_base_url": cfg.app.get("text_openai_base_url", "https://api.siliconflow.cn/v1"),
                },
                # 素材源配置
                "material": {
                    "pexels_api_keys": cfg.app.get("pexels_api_keys", []),
                    "pixabay_api_keys": cfg.app.get("pixabay_api_keys", []),
                    "directory": cfg.app.get("material_directory", ""),
                },
                # TTS 配置
                "tts": {
                    "enabled": True,
                    "engine": "supertonic",
                    "voice": "M1",
                    "speed": 1.0,
                    "pitch": 1.0,
                },
                # ASR 配置
                "asr": {
                    "enabled": True,
                    "engine": cfg.asr.get("engine", "sensevoice"),
                    "model": cfg.asr.get("model", "SenseVoice-large"),
                    "language": cfg.asr.get("language", "auto"),
                    "translate": cfg.asr.get("translate", False),
                    "enable_emotion": cfg.asr.get("enable_emotion", True),
                    "enable_audio_events": cfg.asr.get("enable_audio_events", True),
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
                    "max_workers": cfg._cfg.get("hardware", {}).get("max_workers", 5),
                },
                # 代理配置
                "proxy": cfg._cfg.get("proxy", {}),
            }
            logger.debug("[Config] 从 config.toml 降级加载配置")
            self._sync_path_manager_output()
        except Exception as e:
            logger.warning(f"[Config] 加载 config.toml 失败: {e}")
            self._settings = self._get_default_settings()
            self._sync_path_manager_output()

    def _sync_path_manager_output(self):
        """同步配置的输出路径到全局路径管理器"""
        output_path = self.get("output.path")
        if output_path:
            try:
                from app.utils.path_manager import get_path_manager
                get_path_manager().set_output_root(output_path)
                logger.info(f"[Config] 已同步全局路径管理器输出根目录: {output_path}")
            except Exception as e:
                logger.warning(f"[Config] 同步路径管理器输出根目录失败: {e}")

    def _get_default_settings(self) -> Dict[str, Any]:
        """获取默认配置 - 统一配置结构"""
        return {
            # LLM 协议配置（前端 SettingsPage 使用）
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
                "engine": "supertonic",
                "voice": "M1",
                "speed": 1.0,
                "pitch": 1.0,
            },
            # ASR 配置
            "asr": {
                "enabled": True,
                "engine": "sensevoice",
                "model": "SenseVoice-large",
                "language": "auto",
                "translate": False,
                "enable_emotion": True,
                "enable_audio_events": True,
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
            # 代理配置
            "proxy": {
                "enabled": False,
                "http": "",
                "https": "",
            },
        }

    def validate(self) -> Tuple[bool, List[str]]:
        """
        验证配置完整性

        Returns:
            (是否有效, 错误信息列表)
        """
        errors = []
        warnings = []

        # 检查必需配置节
        for section in self.REQUIRED_SECTIONS:
            if section not in self._settings:
                errors.append(f"缺少必需配置节: {section}")

        # 检查验证规则
        for key, rule in self.VALIDATION_RULES.items():
            value = self.get(key)
            
            if value is None:
                if rule.get("required"):
                    errors.append(rule.get("message", f"{key} 是必需的"))
                elif "default" in rule:
                    # 设置默认值
                    self._set_default(key, rule["default"])
                    warnings.append(f"{key} 使用默认值: {rule['default']}")
            elif not isinstance(value, rule["type"]):
                errors.append(f"{key} 类型错误，期望 {rule['type'].__name__}")

        # 检查输出路径
        output_path = self.get("output.path")
        if output_path:
            path = Path(output_path)
            try:
                path.mkdir(parents=True, exist_ok=True)
                # 测试写入权限
                test_file = path / ".write_test"
                test_file.write_text("test")
                test_file.unlink()
            except Exception as e:
                errors.append(f"输出路径无法写入: {output_path} ({e})")

        # 检查 API Key 格式
        api_key = self.get("openai_protocol.api_key")
        if api_key and not api_key.startswith("sk-"):
            warnings.append("OpenAI API Key 格式可能不正确")

        self._validation_errors = errors
        
        if errors:
            logger.error(f"[Config] 配置验证失败: {errors}")
        if warnings:
            logger.warning(f"[Config] 配置警告: {warnings}")

        return len(errors) == 0, errors + warnings

    def _set_default(self, key: str, value: Any):
        """设置默认值"""
        keys = key.split(".")
        target = self._settings
        
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        
        target[keys[-1]] = value

    def is_valid(self) -> bool:
        """检查配置是否有效"""
        valid, _ = self.validate()
        return valid

    def get_validation_errors(self) -> List[str]:
        """获取验证错误"""
        return self._validation_errors.copy()

    def reload(self):
        """重新加载配置（热更新）"""
        self._load_settings()
        valid, messages = self.validate()
        if valid:
            logger.info("[Config] 配置已热更新并验证通过")
        else:
            logger.warning(f"[Config] 配置已更新但验证失败: {messages}")

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持点号分隔的路径

        示例：
            config.get("openai_protocol.api_key")
            config.get("output.path")
        """
        keys = key.split(".")
        value = self._settings

        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default

        return value if value is not None else default

    def get_llm_config(self, provider: str = "openai_protocol") -> Dict[str, Any]:
        """获取 LLM 配置"""
        return self.get(provider, {})

    def get_output_config(self) -> Dict[str, Any]:
        """获取输出配置"""
        return self.get("output", {})

    def get_tts_config(self) -> Dict[str, Any]:
        """获取 TTS 配置"""
        return self.get("tts", {})

    def get_asr_config(self) -> Dict[str, Any]:
        """获取 ASR 配置"""
        return self.get("asr", {})

    def get_vision_config(self) -> Dict[str, Any]:
        """获取 Vision LLM 配置（用于视频分析）"""
        return self.get("vision", {})

    def get_text_config(self) -> Dict[str, Any]:
        """获取 Text LLM 配置（用于文本生成）"""
        return self.get("text", {})

    def get_material_config(self) -> Dict[str, Any]:
        """获取素材源配置"""
        return self.get("material", {})

    def get_vision_llm_provider(self) -> str:
        """获取 Vision LLM 提供商"""
        return self.get("vision.llm_provider", "openai")

    def get_text_llm_provider(self) -> str:
        """获取 Text LLM 提供商"""
        return self.get("text.llm_provider", "openai")

    def get_api_key(self, provider: str, key_type: str = "openai") -> str:
        """
        获取指定提供商的 API Key
        
        Args:
            provider: 配置段名称 (vision/text)
            key_type: 密钥类型 (openai/anthropic 等)
        """
        return self.get(f"{provider}.{key_type}_api_key", "")

    def get_material_directory(self) -> str:
        """获取素材目录"""
        return self.get("material.directory", "")

    def get_pexels_api_keys(self) -> List[str]:
        """获取 Pexels API Keys"""
        return self.get("material.pexels_api_keys", [])

    def get_pixabay_api_keys(self) -> List[str]:
        """获取 Pixabay API Keys"""
        return self.get("material.pixabay_api_keys", [])

    def get_proxy_config(self) -> Dict[str, Any]:
        """获取代理配置"""
        return self.get("proxy", {})

    def get_azure_config(self) -> Dict[str, Any]:
        """获取 Azure TTS 配置"""
        return self.get("azure", {})

    def get_tencent_config(self) -> Dict[str, Any]:
        """获取腾讯云 TTS 配置"""
        return self.get("tencent", {})

    def get_soulvoice_config(self) -> Dict[str, Any]:
        """获取 SoulVoice TTS 配置"""
        return self.get("soulvoice", {})

    def get_indextts2_config(self) -> Dict[str, Any]:
        """获取 IndexTTS2 配置"""
        return self.get("indextts2", {})

    def get_styletts2_config(self) -> Dict[str, Any]:
        """获取 StyleTTS2 配置"""
        return self.get("styletts2", {})

    def get_cosyvoice_config(self) -> Dict[str, Any]:
        """获取 CosyVoice 配置"""
        return self.get("cosyvoice", {})

    def get_legacy_app_config(self, key: str, default: Any = None) -> Any:
        """
        获取旧版 config.toml [app] 段的配置项（向后兼容）
        
        这个方法用于兼容那些还没有迁移到新配置结构的模块。
        如果 settings.json 中没有该配置，会从 config.toml 降级读取。
        
        Args:
            key: 配置键名
            default: 默认值
        """
        # 首先尝试从新配置中获取
        value = self.get(f"legacy.{key}")
        if value is not None:
            return value
        
        # 降级到 config.toml
        try:
            from app.config import config as cfg
            return cfg.app.get(key, default)
        except Exception:
            return default

    def get_legacy_config_section(self, section: str) -> Dict[str, Any]:
        """
        获取旧版 config.toml 的整个配置段（向后兼容）
        
        Args:
            section: 配置段名称
        """
        try:
            from app.config import config as cfg
            return cfg._cfg.get(section, {})
        except Exception:
            return {}


# 全局单例
config = UnifiedConfig()


def get_config() -> UnifiedConfig:
    """获取统一配置实例"""
    return config


def reload_config():
    """重新加载配置"""
    config.reload()


def validate_config() -> Tuple[bool, List[str]]:
    """验证配置（便捷函数）"""
    return config.validate()

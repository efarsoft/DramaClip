"""
统一配置访问模块

策略：
1. settings.json 作为唯一配置源（前端操作的配置）
2. config.toml 仅在 settings.json 不存在时作为降级数据源
3. 所有服务统一通过 UnifiedConfig.get() 读取配置
"""

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, List, Tuple, Callable
from loguru import logger

from app.core import SETTINGS_PATH


class ConfigValidationError(Exception):
    """配置验证错误"""
    pass


# ---- 唯一默认配置定义（消除三重重复）----

def _default_settings() -> Dict[str, Any]:
    """所有配置段的默认值（唯一定义点）"""
    return {
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
        "vision": {
            "llm_provider": "openai",
            "openai_api_key": "",
            "openai_model_name": "Qwen/Qwen3.5-122B-A10B",
            "openai_base_url": "https://api.siliconflow.cn/v1",
            "analysis_prompt": "",
        },
        "text": {
            "llm_provider": "openai",
            "openai_api_key": "",
            "openai_model_name": "Pro/zai-org/GLM-5",
            "openai_base_url": "https://api.siliconflow.cn/v1",
        },
        "material": {
            "pexels_api_keys": [],
            "pixabay_api_keys": [],
            "directory": "",
        },
        "tts": {
            "enabled": True,
            "engine": "edge_tts",
            "voice": "zh-CN-XiaoxiaoNeural",
            "speed": 1.0,
            "pitch": 1.0,
        },
        "asr": {
            "enabled": True,
            "engine": "sensevoice",
            "model": "SenseVoice-large",
            "language": "auto",
            "translate": False,
            "enable_emotion": True,
            "enable_audio_events": True,
        },
        "vit": {
            "enabled": True,
            "provider": "openai_protocol",
            "model": "qwen-vl-max",
            "batch_size": 4,
        },
        "output": {
            "path": str(Path.home() / "DramaClip" / "Outputs"),
            "quality": "1080p",
            "format": "mp4",
            "fps": 30,
            "codec": "h264",
        },
        "hardware": {
            "enabled": True,
            "ffmpeg_hwaccel": "auto",
            "gpu_device": "0",
            "threads": 4,
            "max_workers": 5,
        },
        "proxy": {
            "enabled": False,
            "http": "",
            "https": "",
        },
        "diarization": {
            "use_pyannote_by_default": False,
            "engine": "clustering",
        },
        "huggingface": {
            "token": "",
            "auto_login": True,
        },
    }


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """深度合并两个字典，override 中的值覆盖 base 中的值"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class UnifiedConfig:
    """
    统一配置访问器（单例）

    所有服务应该通过 get_config() 获取实例，而不是直接读取 config.toml 或 settings.json
    """

    _instance: Optional["UnifiedConfig"] = None
    _settings: Dict[str, Any] = {}
    _validation_errors: List[str] = []
    _reload_callbacks: List[Callable[[], None]] = []

    REQUIRED_SECTIONS = ["openai_protocol", "output"]

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
        """加载配置（settings.json 优先，降级到 config.toml）"""
        if SETTINGS_PATH.exists():
            try:
                raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                # 用默认值填充缺失的键
                self._settings = _deep_merge(_default_settings(), raw)
                logger.debug("[Config] 从 settings.json 加载配置")
                self._sync_path_manager_output()
                return
            except Exception as e:
                logger.warning(f"[Config] 加载 settings.json 失败: {e}")

        # 降级：从 config.toml 迁移
        self._load_from_config_toml()

    def _load_from_config_toml(self):
        """从 config.toml 降级加载（兼容旧配置）"""
        try:
            from app.config import config as cfg

            # 从 config.toml 映射到新结构
            toml_settings = {
                "openai_protocol": {
                    "api_key": cfg.app.get("vision_openai_api_key", ""),
                    "base_url": cfg.app.get("vision_openai_base_url", ""),
                    "model": cfg.app.get("text_openai_model_name", "gpt-4o"),
                },
                "vision": {
                    "llm_provider": cfg.app.get("vision_llm_provider", "openai"),
                    "openai_api_key": cfg.app.get("vision_openai_api_key", ""),
                    "openai_model_name": cfg.app.get("vision_openai_model_name", ""),
                    "openai_base_url": cfg.app.get("vision_openai_base_url", ""),
                    "analysis_prompt": cfg.app.get("vision_analysis_prompt", ""),
                },
                "text": {
                    "llm_provider": cfg.app.get("text_llm_provider", "openai"),
                    "openai_api_key": cfg.app.get("text_openai_api_key", ""),
                    "openai_model_name": cfg.app.get("text_openai_model_name", ""),
                    "openai_base_url": cfg.app.get("text_openai_base_url", ""),
                },
                "material": {
                    "pexels_api_keys": cfg.app.get("pexels_api_keys", []),
                    "pixabay_api_keys": cfg.app.get("pixabay_api_keys", []),
                    "directory": cfg.app.get("material_directory", ""),
                },
                "asr": {
                    "engine": cfg.asr.get("engine", "sensevoice"),
                    "model": cfg.asr.get("model", "SenseVoice-large"),
                    "language": cfg.asr.get("language", "auto"),
                    "translate": cfg.asr.get("translate", False),
                    "enable_emotion": cfg.asr.get("enable_emotion", True),
                    "enable_audio_events": cfg.asr.get("enable_audio_events", True),
                },
                "hardware": {
                    "max_workers": cfg._cfg.get("hardware", {}).get("max_workers", 5),
                },
                "proxy": cfg._cfg.get("proxy", {}),
            }
            # 用默认值填充，再用 toml 值覆盖
            self._settings = _deep_merge(_default_settings(), toml_settings)
            logger.debug("[Config] 从 config.toml 降级加载配置")
        except Exception as e:
            logger.warning(f"[Config] 加载 config.toml 失败: {e}")
            self._settings = _default_settings()

        self._sync_path_manager_output()

    def _sync_path_manager_output(self):
        """同步配置的输出路径到全局路径管理器"""
        output_path = self.get("output.path")
        if output_path:
            try:
                from app.utils.path_manager import get_path_manager
                get_path_manager().set_output_root(output_path)
            except Exception:
                pass

    # ---- 核心读取 ----

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值，支持点号分隔的路径（如 'openai_protocol.api_key'）"""
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

    # ---- 便捷方法 ----

    def get_llm_config(self, provider: str = "openai_protocol") -> Dict[str, Any]:
        return self.get(provider, {})

    def get_output_config(self) -> Dict[str, Any]:
        return self.get("output", {})

    def get_tts_config(self) -> Dict[str, Any]:
        return self.get("tts", {})

    def get_asr_config(self) -> Dict[str, Any]:
        return self.get("asr", {})

    def get_diarization_config(self) -> Dict[str, Any]:
        return self.get("diarization", {"use_pyannote_by_default": False, "engine": "clustering"})

    def get_huggingface_config(self) -> Dict[str, Any]:
        return self.get("huggingface", {"token": "", "auto_login": True})

    def get_vision_config(self) -> Dict[str, Any]:
        return self.get("vision", {})

    def get_text_config(self) -> Dict[str, Any]:
        return self.get("text", {})

    def get_material_config(self) -> Dict[str, Any]:
        return self.get("material", {})

    def get_vision_llm_provider(self) -> str:
        return self.get("vision.llm_provider", "openai")

    def get_text_llm_provider(self) -> str:
        return self.get("text.llm_provider", "openai")

    def get_api_key(self, provider: str, key_type: str = "openai") -> str:
        return self.get(f"{provider}.{key_type}_api_key", "")

    def get_material_directory(self) -> str:
        return self.get("material.directory", "")

    def get_pexels_api_keys(self) -> List[str]:
        return self.get("material.pexels_api_keys", [])

    def get_pixabay_api_keys(self) -> List[str]:
        return self.get("material.pixabay_api_keys", [])

    def get_proxy_config(self) -> Dict[str, Any]:
        return self.get("proxy", {})

    def get_azure_config(self) -> Dict[str, Any]:
        return self.get("azure", {})

    def get_tencent_config(self) -> Dict[str, Any]:
        return self.get("tencent", {})

    def get_soulvoice_config(self) -> Dict[str, Any]:
        return self.get("soulvoice", {})

    def get_indextts2_config(self) -> Dict[str, Any]:
        return self.get("indextts2", {})

    def get_styletts2_config(self) -> Dict[str, Any]:
        return self.get("styletts2", {})

    def get_cosyvoice_config(self) -> Dict[str, Any]:
        return self.get("cosyvoice", {})

    # ---- 向后兼容（config.toml 旧接口）----

    def get_legacy_app_config(self, key: str, default: Any = None) -> Any:
        """获取旧版 config.toml [app] 段的配置项（向后兼容）"""
        value = self.get(f"legacy.{key}")
        if value is not None:
            return value
        try:
            from app.config import config as cfg
            return cfg.app.get(key, default)
        except Exception:
            return default

    def get_legacy_config_section(self, section: str) -> Dict[str, Any]:
        """获取旧版 config.toml 的整个配置段（向后兼容）"""
        try:
            from app.config import config as cfg
            return cfg._cfg.get(section, {})
        except Exception:
            return {}

    # ---- 验证 ----

    def validate(self) -> Tuple[bool, List[str]]:
        """验证配置完整性"""
        errors = []
        warnings = []

        for section in self.REQUIRED_SECTIONS:
            if section not in self._settings:
                errors.append(f"缺少必需配置节: {section}")

        for key, rule in self.VALIDATION_RULES.items():
            value = self.get(key)
            if value is None:
                if rule.get("required"):
                    errors.append(rule.get("message", f"{key} 是必需的"))
                elif "default" in rule:
                    self._set_default(key, rule["default"])
                    warnings.append(f"{key} 使用默认值: {rule['default']}")
            elif not isinstance(value, rule["type"]):
                errors.append(f"{key} 类型错误，期望 {rule['type'].__name__}")

        output_path = self.get("output.path")
        if output_path:
            path = Path(output_path)
            try:
                path.mkdir(parents=True, exist_ok=True)
                test_file = path / ".write_test"
                test_file.write_text("test")
                test_file.unlink()
            except Exception as e:
                errors.append(f"输出路径无法写入: {output_path} ({e})")

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
        keys = key.split(".")
        target = self._settings
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value

    def is_valid(self) -> bool:
        valid, _ = self.validate()
        return valid

    def get_validation_errors(self) -> List[str]:
        return self._validation_errors.copy()

    # ---- 持久化 ----

    def save(self):
        """原子写入 settings.json"""
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = SETTINGS_PATH.with_suffix(".tmp")
        try:
            tmp_path.write_text(
                json.dumps(self._settings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp_path.replace(SETTINGS_PATH)
            logger.debug("[Config] settings.json 已保存")
        except Exception as e:
            logger.error(f"[Config] 保存 settings.json 失败: {e}")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def update(self, section: str, values: Dict[str, Any]):
        """更新指定配置段并持久化"""
        if section not in self._settings:
            self._settings[section] = {}
        self._settings[section] = _deep_merge(self._settings[section], values)
        self.save()

    # ---- 热重载 ----

    def reload(self):
        """重新加载配置（热更新）"""
        self._load_settings()
        valid, messages = self.validate()
        if valid:
            logger.info("[Config] 配置已热更新并验证通过")
        else:
            logger.warning(f"[Config] 配置已更新但验证失败: {messages}")
        self._invoke_reload_callbacks()

    def register_on_reload(self, callback: Callable[[], None]) -> None:
        """注册配置热重载回调"""
        if callback not in self._reload_callbacks:
            self._reload_callbacks.append(callback)

    def _invoke_reload_callbacks(self):
        if not self._reload_callbacks:
            return
        logger.info(f"[Config] 通知 {len(self._reload_callbacks)} 个服务配置已更新...")
        for cb in list(self._reload_callbacks):
            try:
                cb()
            except Exception as e:
                logger.error(f"[Config] 热重载回调执行失败: {e}")


# ---- 全局单例与便捷函数 ----

config = UnifiedConfig()


def get_config() -> UnifiedConfig:
    """获取统一配置实例（会触发配置热更新监听器启动）"""
    _ensure_watcher_started()
    return config


def reload_config():
    """重新加载配置"""
    config.reload()


def validate_config() -> Tuple[bool, List[str]]:
    """验证配置（便捷函数）"""
    return config.validate()


# ====================== 热更新文件监听器 ======================

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    _HAS_WATCHDOG = True
except ImportError:
    _HAS_WATCHDOG = False
    Observer = None
    FileSystemEventHandler = object


class _SettingsFileWatcher(FileSystemEventHandler):
    """settings.json 热更新监听器（带防抖）"""
    def __init__(self, unified_config: "UnifiedConfig", debounce_ms: int = 800):
        self.config = unified_config
        self.debounce_ms = debounce_ms
        self._last_reload = 0

    def on_modified(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith("settings.json"):
            return

        now = time.time() * 1000
        if now - self._last_reload < self.debounce_ms:
            return
        self._last_reload = now

        logger.info("[Config] 检测到 settings.json 变更，触发热重载...")
        try:
            self.config.reload()
        except Exception as e:
            logger.error(f"[Config] 热重载失败: {e}")


def _start_settings_watcher(cfg: "UnifiedConfig") -> Optional["Observer"]:
    """启动 settings.json 监听（仅当 watchdog 可用时）"""
    if not _HAS_WATCHDOG:
        logger.warning("[Config] watchdog 未安装，热更新监听不可用")
        return None

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    observer = Observer()
    handler = _SettingsFileWatcher(cfg)
    observer.schedule(handler, str(SETTINGS_PATH.parent), recursive=False)
    observer.start()
    logger.info(f"[Config] 已启动 settings.json 热更新监听")
    return observer


_config_observer: Optional["Observer"] = None


def _ensure_watcher_started():
    global _config_observer
    if _config_observer is None:
        _config_observer = _start_settings_watcher(config)


def stop_config_watcher():
    global _config_observer
    if _config_observer:
        _config_observer.stop()
        _config_observer.join(timeout=2)
        _config_observer = None
        logger.info("[Config] 配置热更新监听器已停止")

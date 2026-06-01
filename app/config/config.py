"""
config.toml 加载模块（向后兼容，主配置源已迁移到 settings.json）
"""

import os
import toml
from pathlib import Path
from loguru import logger

from app.config.defaults import build_default_app_config, merge_missing_app_defaults

root_dir = str(Path(__file__).resolve().parent.parent.parent)
config_file = os.path.join(root_dir, "config.toml")
version_file = os.path.join(root_dir, "project_version")


def get_version_from_file():
    """从project_version文件中读取版本号"""
    try:
        if os.path.isfile(version_file):
            with open(version_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        return "0.1.0"  # 默认版本号
    except (IOError, OSError) as e:
        logger.error(f"读取版本号文件失败: {str(e)}")
        return "0.1.0"  # 默认版本号


def load_config():
    """加载 config.toml（仅在 settings.json 不存在时使用）"""
    if not os.path.isfile(config_file):
        _config_ = build_default_config()
        write_config_file(_config_)
        logger.info("已从模板创建 config.toml")
        return _config_

    logger.info(f"load config from file: {config_file}")

    _config_ = load_toml_file(config_file)
    _config_["app"] = merge_missing_app_defaults(_config_.get("app", {}))
    return _config_


def load_toml_file(file_path):
    """Load a TOML file and fall back to utf-8-sig when needed."""
    try:
        return toml.load(file_path)
    except (toml.TomlDecodeError, IOError, OSError) as e:
        logger.warning(f"load config failed: {str(e)}, try to load as utf-8-sig")
        with open(file_path, mode="r", encoding="utf-8-sig") as fp:
            _cfg_content = fp.read()
            return toml.loads(_cfg_content)


def build_default_config():
    """Build the initial config file content for a fresh installation."""
    example_file = f"{root_dir}/config.example.toml"
    config_data = {}
    if os.path.isfile(example_file):
        config_data = load_toml_file(example_file)

    config_data["app"] = build_default_app_config(config_data.get("app", {}))
    return config_data


def write_config_file(config_data):
    parent_dir = os.path.dirname(config_file)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    with open(config_file, "w", encoding="utf-8") as f:
        f.write(toml.dumps(config_data))


# ---- 从 config.toml 加载全局变量（向后兼容，新代码请使用 UnifiedConfig）----
_cfg = load_config()
app = _cfg.get("app", {})
asr = _cfg.get("asr", {})

project_name = _cfg.get("project_name", "DramaClip")
project_description = _cfg.get("project_description", "")
project_version = get_version_from_file()

imagemagick_path = app.get("imagemagick_path", "")
if imagemagick_path and os.path.isfile(imagemagick_path):
    os.environ["IMAGEMAGICK_BINARY"] = imagemagick_path

ffmpeg_path = app.get("ffmpeg_path", "")
if ffmpeg_path and os.path.isfile(ffmpeg_path):
    os.environ["IMAGEIO_FFMPEG_EXE"] = ffmpeg_path

logger.info(f"{project_name} v{project_version}")

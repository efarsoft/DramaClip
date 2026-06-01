"""
配置包入口

模块职责划分：
- unified_config.py  统一配置访问器（单例，settings.json 为唯一配置源）
- config.py          config.toml 加载（仅当 settings.json 不存在时降级使用）
- defaults.py        LLM 默认值（供 config.toml 引导使用）
- audio_config.py    音频处理参数（DUCKING_CONFIG）
- models.yaml        模型定义数据文件
"""

from app.config.unified_config import config

__all__ = ["config"]

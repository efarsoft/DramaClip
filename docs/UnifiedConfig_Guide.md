# UnifiedConfig 使用指南

## 概述

DramaClip 使用 `UnifiedConfig` 作为统一的配置管理系统。**所有服务模块必须通过 `from app.config.unified_config import get_config` 读取配置**，严禁直接读取 `config.toml` 或 `settings.json`。

**优先级（已实现）**：`~/.dramaclip/settings.json`（GUI 修改，高优先） > 项目根 `config.toml` > 内置默认值。

**当前状态**：配置合并与读取已完整落地。热更新 watcher 仍在演进中（修改 settings.json 后建议重启后端进程以完全生效，部分服务已支持运行时重读）。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                     UnifiedConfig                           │
├─────────────────────────────────────────────────────────────┤
│  优先级：settings.json > config.toml > 默认值               │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│                    服务模块                                  │
│  (subtitle.py, task.py, llm/*.py, analyze/*.py, etc.)      │
└─────────────────────────────────────────────────────────────┘
```

## 基本用法

### 1. 导入配置

```python
from app.config.unified_config import get_config

# 获取配置实例
config = get_config()
```

### 2. 读取配置

```python
# 使用点号分隔的路径读取
api_key = config.get("openai_protocol.api_key")
output_path = config.get("output.path")

# 带默认值
timeout = config.get("llm_text_timeout", 180)
```

### 3. 使用专用方法

```python
# LLM 配置
llm_config = config.get_llm_config()  # 返回 dict

# ASR 配置
asr_config = config.get_asr_config()

# 输出配置
output_config = config.get_output_config()

# TTS 配置
tts_config = config.get_tts_config()

# 视觉配置
vision_config = config.get_vision_config()

# 材料配置
material_config = config.get_material_config()

# API Key
api_key = config.get_api_key("vision")  # 或 "text"

# 代理配置
proxy_config = config.get_proxy_config()
```

### 4. 向后兼容（迁移期间）

对于尚未完全迁移到新配置结构的模块，可以使用 `get_legacy_app_config`：

```python
# 获取旧版 config.toml [app] 段的配置项
value = config.get_legacy_app_config("llm_provider", "openai")
```

## 配置结构

### settings.json 结构

```json
{
  "openai_protocol": {
    "api_key": "sk-xxx",
    "model": "gpt-4o",
    "base_url": "https://api.openai.com/v1",
    "max_tokens": 4096,
    "temperature": 0.7,
    "enabled": true
  },
  "output": {
    "path": "/path/to/output"
  },
  "asr": {
    "engine": "faster_whisper",
    "model": "large-v3",
    "device": "cuda",
    "language": "zh"
  }
}
```

### config.toml 结构（降级读取）

```toml
[app]
llm_provider = "openai"
openai_api_key = "sk-xxx"
openai_model_name = "gpt-4o"

[asr]
engine = "faster_whisper"
model = "large-v3"
```

## 迁移指南

### 旧代码

```python
from app.config import config

# 直接读取 config.toml
api_key = config.app.get("openai_api_key")
model = config.app.get("openai_model_name")
```

### 新代码

```python
from app.config.unified_config import get_config

config = get_config()

# 从统一配置读取
api_key = config.get("openai_protocol.api_key")
model = config.get("openai_protocol.model")
```

### 常用配置键映射

| 旧键名 (config.toml) | 新键名 (UnifiedConfig) |
|---------------------|------------------------|
| `app.llm_provider` | `openai_protocol` 或使用 `get_text_llm_provider()` |
| `app.openai_api_key` | `openai_protocol.api_key` |
| `app.openai_model_name` | `openai_protocol.model` |
| `app.openai_base_url` | `openai_protocol.base_url` |
| `app.output_path` | `output.path` |
| `asr.engine` | `asr.engine` |
| `asr.model` | `asr.model` |

## 配置验证

```python
# 验证配置
is_valid = config.validate()

# 获取验证错误
errors = config.get_validation_errors()
if errors:
    for error in errors:
        print(f"配置错误: {error}")
```

## 重新加载配置

```python
from app.config.unified_config import reload_config

# 重新加载配置（热更新）
reload_config()
```

## 最佳实践

1. **始终使用 `get_config()` 获取配置实例**
   ```python
   from app.config.unified_config import get_config
   config = get_config()
   ```

2. **使用点号路径读取配置**
   ```python
   api_key = config.get("openai_protocol.api_key")
   ```

3. **提供默认值**
   ```python
   timeout = config.get("llm_text_timeout", 180)
   ```

4. **使用专用方法（如果可用）**
   ```python
   # 推荐
   llm_config = config.get_llm_config()
   
   # 不推荐
   llm_config = config.get("openai_protocol")
   ```

5. **避免直接访问 `_settings`**
   ```python
   # 不推荐
   api_key = config._settings["openai_protocol"]["api_key"]
   
   # 推荐
   api_key = config.get("openai_protocol.api_key")
   ```

## 故障排查

### 配置读取失败

如果配置读取返回 `None` 或默认值：

1. 检查 `settings.json` 文件是否存在：`~/.dramaclip/settings.json`
2. 检查 `config.toml` 文件是否存在：项目根目录
3. 运行配置验证脚本：`python app/scripts/verify_config.py`

### 配置不生效

1. 调用 `reload_config()` 重新加载配置
2. 检查是否有缓存：某些模块可能缓存了配置值

## 相关文件

- `app/config/unified_config.py` - UnifiedConfig 实现
- `app/config/config.py` - 旧版配置读取（降级使用）
- `app/scripts/verify_config.py` - 配置验证脚本

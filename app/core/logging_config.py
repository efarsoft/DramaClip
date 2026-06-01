"""
日志系统标准化配置

保留 loguru 作为日志引擎（全项目已广泛使用），增加：
1. JSON 输出模式（通过 DRAMACLIP_JSON_LOGS=1 启用，生产/日志采集友好）
2. HF Token 脱敏过滤器（防止 HuggingFace token 泄漏到日志）

参考 OmniVoice-Studio 的 _JsonFormatter + HFTokenRedactor 实现。
"""

import json
import os
import re
from pathlib import Path
from typing import TextIO

from loguru import logger

# ---------------------------------------------------------------------------
# HF Token 脱敏
# ---------------------------------------------------------------------------

_REDACTED = "hf_***REDACTED***"
_HF_TOKEN_RE = re.compile(r"hf_[A-Za-z0-9]{30,}")


def _redact_hf_tokens(text: str) -> str:
    """替换日志消息中的 HuggingFace token"""
    return _HF_TOKEN_RE.sub(_REDACTED, text)


def _sensitive_filter(record):
    """loguru 过滤器：脱敏 HF token（始终返回 True，仅修改不丢弃）"""
    try:
        if isinstance(record["message"], str):
            record["message"] = _redact_hf_tokens(record["message"])
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# JSON 格式化 Sink（loguru 兼容）
# ---------------------------------------------------------------------------

def json_sink(stream: TextIO):
    """
    创建一个 loguru JSON 格式的 sink。

    用法：
        logger.add(json_sink(sys.stderr), level="INFO")

    每行输出一个 JSON 对象，适合 ELK/Loki/Vector 等日志采集系统。
    """
    def _sink(message):
        record = message.record
        payload = {
            "t": record["time"].strftime("%Y-%m-%dT%H:%M:%S"),
            "level": record["level"].name,
            "name": record["name"],
            "func": record["function"],
            "line": record["line"],
            "msg": _redact_hf_tokens(str(record["message"])),
        }
        if record["exception"]:
            payload["exc"] = str(record["exception"])
        stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        stream.flush()

    return _sink


# ---------------------------------------------------------------------------
# 噪音日志过滤（从 config/__init__.py 迁移）
# ---------------------------------------------------------------------------

_NOISE_PATTERNS = [
    "已注册模板过滤器",
    "已注册提示词",
    "注册视觉模型提供商",
    "注册文本模型提供商",
    "LLM服务提供商注册",
    "FFmpeg支持的硬件加速器",
    "硬件加速测试优先级",
    "硬件加速方法",
]


def _noise_filter(record):
    """过滤 DEBUG 级别的噪音日志（注册消息等）"""
    if record["level"].name == "DEBUG":
        msg = str(record.get("message", ""))
        return not any(p in msg for p in _NOISE_PATTERNS)
    return True


# ---------------------------------------------------------------------------
# 统一配置入口
# ---------------------------------------------------------------------------

def configure_logging(log_dir: Path | None = None):
    """
    配置 DramaClip 日志系统。

    - 环境变量 DRAMACLIP_JSON_LOGS=1 启用 JSON 格式
    - 环境变量 DRAMACLIP_LOG_LEVEL 控制日志级别（默认 DEBUG）
    - 自动添加 HF token 脱敏过滤器
    - 文件日志自动轮转 + 保留 7 天
    """
    # 清除 loguru 默认 handler
    logger.remove()

    json_mode = os.environ.get("DRAMACLIP_JSON_LOGS") == "1"
    log_level = os.environ.get("DRAMACLIP_LOG_LEVEL", "DEBUG")

    # 组合 patcher：敏感信息脱敏 + 噪音过滤
    def _combined_patcher(record):
        _sensitive_filter(record)
        # 噪音过滤在 handler 级别处理（通过 filter 参数）

    logger.configure(patcher=_combined_patcher)

    # ---- 文件日志 ----
    if log_dir is None:
        log_dir = Path.home() / ".dramaclip" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    if json_mode:
        # JSON 模式：文件 + stderr 都用 JSON 格式
        import sys
        logger.add(
            log_dir / "backend.log",
            rotation="10 MB",
            retention="7 days",
            level=log_level,
            format=lambda r: json.dumps({
                "t": r["time"].strftime("%Y-%m-%dT%H:%M:%S"),
                "level": r["level"].name,
                "name": r["name"],
                "func": r["function"],
                "line": r["line"],
                "msg": _redact_hf_tokens(str(r["message"])),
            }, ensure_ascii=False),
            filter=_noise_filter,
        )
        logger.add(json_sink(sys.stderr), level=log_level, filter=_noise_filter)
    else:
        # 文本模式：文件详细 + stderr 简洁
        logger.add(
            log_dir / "backend.log",
            rotation="10 MB",
            retention="7 days",
            level=log_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
            filter=_noise_filter,
        )
        import sys
        if not getattr(sys, "frozen", False):
            logger.add(
                sys.stderr,
                level=log_level,
                format="{time:HH:mm:ss} | {level} | {message}",
                filter=_noise_filter,
            )

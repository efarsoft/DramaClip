"""
Hugging Face 认证辅助（Phase 3.2）

集中处理 gated 模型（pyannote 等）的 token 管理与登录。
"""

from __future__ import annotations

import os
from typing import Optional

from loguru import logger

from app.config.unified_config import get_config


def get_hf_token() -> Optional[str]:
    """获取当前配置的 HF_TOKEN（优先环境变量，其次配置）。"""
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    if token:
        return token

    cfg = get_config().get_huggingface_config()
    return cfg.get("token") or None


def ensure_hf_login() -> bool:
    """
    如果配置了 token，尝试登录 huggingface_hub。
    返回是否成功登录。
    """
    token = get_hf_token()
    if not token:
        return False

    try:
        from huggingface_hub import login
        login(token=token, add_to_git_credential=False)
        logger.info("[HF] 已使用配置的 token 登录")
        return True
    except Exception as e:
        logger.warning(f"[HF] 登录失败: {e}")
        return False


def get_hf_headers() -> dict:
    """返回带 token 的请求头（用于直接 HTTP 调用）。"""
    token = get_hf_token()
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}

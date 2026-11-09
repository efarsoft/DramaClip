"""AIGC 隐式标识（settings ``export.aigc_metadata``，默认关闭）。

业主裁决（2026-11-09）：默认关、用户可开——隐式标识与显式烧录（export.ai_label）
是两条独立要求，各自开关。payload 按 GB 45438-2025 元数据 JSON
（Label/ContentProducer/ProduceID）拼 ``AIGC=`` 前缀后整体 Base64，写入 MP4
comment 字段（抖音元数据规范接受 comment 通道）；XMP 容器注入超出 ffmpeg 能力，
只读 XMP 的平台靠发布包的逐平台 AI 声明指引兜底。

写入点在整片最终交付遍：concat 的单段分支是 copyfile 不经过 ffmpeg，
BGM/响度后置遍的元数据存活性各分支不一——收尾 ``-c copy`` remux 一次，
所有路径覆盖且仅一次（流复制不重编，秒级）。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

from dramaclip.infra import config
from dramaclip.infra.ffmpeg import runner

#: GB 45438-2025 内容属性：1=AI 生成合成（2/3 为传播平台专用，制作端不写）。
_LABEL = "1"


def enabled(settings: config.Settings) -> bool:
    """读取开关（默认 false；缺键同样判假）。"""
    return config.get_bool(settings, "export.aigc_metadata")


def producer_code(settings: config.Settings) -> str:
    """服务提供者编码（法定必填；空 = 未填，submit 守卫据此拒收）。"""
    return str(settings.get("export.aigc_producer_code", "") or "").strip()


def payload(producer: str, content_id: str) -> str:
    """AIGC= 前缀 + JSON 整体 Base64（先拼前缀再编码，解码端按前缀识别）。"""
    doc = {"Label": _LABEL, "ContentProducer": producer, "ProduceID": content_id}
    raw = "AIGC=" + json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def metadata_args(producer: str, content_id: str) -> list[str]:
    """擦源留标：-map_metadata -1 在前，comment 写入在后（顺序即语义）。"""
    return ["-map_metadata", "-1", "-metadata", f"comment={payload(producer, content_id)}"]


def stamp(film: Path, *, producer: str, content_id: str) -> None:
    """最终交付遍：流复制 remux 写入隐式标识；失败上抛（用户明示开启，不静默缺标）。"""
    staged = film.with_name(f"{film.stem}.aigc.part{film.suffix}")
    try:
        runner.run(
            ["-y", "-i", str(film), "-c", "copy",
             *metadata_args(producer, content_id), str(staged)],
            timeout_s=300,
        )
        staged.replace(film)
    finally:
        staged.unlink(missing_ok=True)

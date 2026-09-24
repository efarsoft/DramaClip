"""BGM 素材库：扫描 `data_dir/bgm/` → 曲目清单（入库素材，运行时不碰这里）。

三层分工（业主裁决的组织方式，各管一层、互不越权）：

- **子文件夹 = 情绪**（第一真相源）：``bgm/<emotion>/<files>``，emotion 取
  emotion_matcher 的 5 键。文件夹是人的显式归类动作，拖拽即归类、整目录拷走
  即迁移。非法目录名（拼错）→ 该目录文件归 "default" 并留痕，不 raise。
- **文件名前缀 = 兜底**：平铺在 bgm 根的文件仍认 ``<emotion>_<n>.<ext>``
  （非法/无前缀 → default）。同一文件两处都有信号时**子目录名优先**。
- **bgm_manifest.json = 资产说明**（人写，跟着素材走）：license/attribution/
  source_url 按相对路径索引；拷素材文件夹它就活着，重扫不丢版权信息。缺省/
  坏 JSON 降级空串——manifest 是登记簿不是门禁，但它缺了等于「出处不明」，
  商用前必须补（见 CPS 场景的版权纪律）。

**分析只发生在扫描入库这一次**：bpm（librosa 懒加载）与时长（ffprobe）测完
写进 bgm_tracks 表（repos/bgm.py），运行时选曲只读库——绝不每次出片重新分析。
本模块是入库工具（UI 素材库「扫描」触发），不在渲染热路径上。

降级纪律（与 B9/A2 同口径）：坏文件跳过留痕不炸、librosa 缺失 → bpm=None、
ffprobe 测不出时长 → 跳过该文件（时长是选曲与铺轨的硬输入，None 会传染）。
曲库是增强项：一颗坏文件不能炸整库，空库是合法态（selector 对空库返回 None，
渲染层无曲可用 = 现状逐字节一致）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from dramaclip.engines.subtitle.emotion_matcher import match_emotion
from dramaclip.engines.tts.base import audio_duration_s

_LOGGER = logging.getLogger(__name__)

# 与 emotion_matcher 的 5 键同源：情绪分类法只有一处真相（match_emotion 的返回值域），
# 这里只是它的字面集合。新增情绪键时改 emotion_matcher，不改这里——_EMOTIONS 用于
# 校验文件夹/前缀是否合法键，match_emotion 永远归一得到。
_EMOTIONS = frozenset({"default", "anger", "triumph", "suspense", "sadness"})
_AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".flac", ".ogg"})
_MANIFEST_NAME = "bgm_manifest.json"


@dataclass(frozen=True)
class BgmTrack:
    """一首曲库素材：机器测的（duration/bpm）+ 人写的（license/attribution/source_url）。"""

    file: Path
    emotion: str  # 5 键之一（非法输入已归一到 default）
    duration_s: float
    bpm: float | None  # librosa 缺失/测不出 → None（选曲时沉底，见 selector）
    license: str  # 可空串=出处未登记；商用前必须补（模块 docstring 的版权纪律）
    attribution: str
    source_url: str


@dataclass(frozen=True)
class ScanResult:
    """一次扫描的完整结果：入库素材 + 跳过留痕（理由是人话，直接进 UI/日志）。"""

    tracks: list[BgmTrack]
    skipped: list[tuple[Path, str]]  # (文件, 跳过原因)


def _emotion_from_folder(folder_name: str) -> str | None:
    """子目录名 → 情绪键；非法键返回 None（调用方归 default 并留痕）。"""
    name = folder_name.strip().lower()
    return name if name in _EMOTIONS else None


def _emotion_from_filename(stem: str) -> str:
    """文件名前缀兜底：``<emotion>_<n>`` → 情绪键；非法/无前缀 → default。"""
    head = stem.split("_", 1)[0].strip().lower()
    if head in _EMOTIONS:
        return head
    # 无前缀但名字含情绪词时走 match_emotion 的关键词路径（它本来就是文本→情绪键）
    return match_emotion(stem.replace("_", " "))


def _load_manifest(bgm_dir: Path) -> dict[str, dict[str, str]]:
    """bgm_manifest.json → {相对路径(posix): {license, attribution, source_url}}。

    缺省/坏 JSON/形状不对 → 空 dict（manifest 是登记簿不是门禁，坏了降级空串，
    但 warn 留痕：静默吞掉会让「出处不明」看起来像「已登记为空」）。
    """
    path = bgm_dir / _MANIFEST_NAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _LOGGER.warning("bgm_manifest.json 读取失败，全部曲目按出处未登记处理: %s", exc)
        return {}
    if not isinstance(raw, dict):
        _LOGGER.warning("bgm_manifest.json 顶层不是对象，忽略: %r", type(raw).__name__)
        return {}
    out: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            out[str(key)] = {
                field: str(value.get(field, "") or "")
                for field in ("license", "attribution", "source_url")
            }
    return out


def _measure_bpm(path: Path) -> float | None:
    """librosa 懒加载测 bpm；缺依赖/坏文件 → None（与 B9 拍点的降级同哲学）。

    importlib 绕开静态导入：librosa.beat 是惰性重导出，mypy strict 下
    `from librosa import beat` 报 attr-defined（audio_analyzer 同款坑与解法）。
    """
    try:
        import importlib

        import numpy as np

        beat = importlib.import_module("librosa.beat")
        core = importlib.import_module("librosa.core")
        y, sr = core.load(str(path), mono=True)
        tempo, _frames = beat.beat_track(y=y, sr=sr)
        # librosa 1.x 的 tempo 是 1-d ndarray（shape (1,)，实测 [117.45]）：
        # 直接 float() 抛 TypeError（只有 0-d 可转）——与 audio_analyzer._estimate_bpm
        # 同款坑同款解（reshape 取标量 + 空数组保护）。
        tempo_arr = np.asarray(tempo).reshape(-1)
        value = float(tempo_arr[0]) if tempo_arr.size else 0.0
        if value <= 0:
            return None
        return round(value, 1)
    except Exception as exc:  # noqa: BLE001 - 任何失败都降级 None：bpm 是增强不是硬输入
        _LOGGER.info("bpm 测量失败（降级 None）: %s (%s)", path.name, exc)
        return None


def scan_library(bgm_dir: Path) -> ScanResult:
    """扫描曲库目录 → (入库素材, 跳过留痕)。低频入库工具，不在渲染热路径上。

    目录形状::

        bgm/
          suspense/track_a.mp3     ← 子目录名=情绪（第一真相源）
          anger/track_b.wav
          triumph_01.mp3           ← 平铺：文件名前缀兜底
          bgm_manifest.json        ← 资产说明（license/署名/出处），跟素材走

    时长用 ffprobe（tts_base.audio_duration_s）逐文件起进程：曲库是几十首量级、
    扫描是低频操作，这个开销可接受——换批量方案（一次 ffprobe 多输入）省不了
    多少复杂度，先把诚实的简单版落地。
    """
    if not bgm_dir.is_dir():
        return ScanResult(tracks=[], skipped=[])
    manifest = _load_manifest(bgm_dir)
    tracks: list[BgmTrack] = []
    skipped: list[tuple[Path, str]] = []

    # 收集 (文件, 情绪键, 留痕)：先子目录（情绪第一真相源），再根目录平铺（前缀兜底）
    candidates: list[tuple[Path, str, str | None]] = []
    for child in sorted(bgm_dir.iterdir()):
        if child.is_dir():
            folder_emotion = _emotion_from_folder(child.name)
            note = None
            if folder_emotion is None:
                folder_emotion = "default"
                note = f"子目录名 {child.name!r} 不是合法情绪键，归 default"
            for f in sorted(child.iterdir()):
                if f.is_file() and f.suffix.lower() in _AUDIO_SUFFIXES:
                    candidates.append((f, folder_emotion, note))
        elif child.is_file() and child.suffix.lower() in _AUDIO_SUFFIXES:
            candidates.append((child, _emotion_from_filename(child.stem), None))

    for path, emotion, note in candidates:
        if note is not None:
            _LOGGER.info("bgm 扫描留痕: %s（%s）", path.name, note)
        try:
            duration = audio_duration_s(path)
        except Exception as exc:  # noqa: BLE001 - 坏文件跳过留痕，一颗坏文件不炸整库
            skipped.append((path, f"时长测量失败: {type(exc).__name__}: {exc}"))
            continue
        if duration <= 0:
            skipped.append((path, f"时长非正（{duration:g}s），疑似坏文件"))
            continue
        meta = manifest.get(path.relative_to(bgm_dir).as_posix(), {})
        tracks.append(
            BgmTrack(
                file=path,
                emotion=emotion,
                duration_s=round(duration, 3),
                bpm=_measure_bpm(path),
                license=meta.get("license", ""),
                attribution=meta.get("attribution", ""),
                source_url=meta.get("source_url", ""),
            )
        )
    return ScanResult(tracks=tracks, skipped=skipped)

"""BGM 生成请求构建：情绪 → 生成参数（纯函数，零 IO）。

情绪预设是「纯器乐叙事床」的英文 caption（上游 DiT 的音乐标签以英文训练语料
为主），配 ``[Instrumental]`` 歌词位与 ``instrumental=True`` 双保险出无人声；
bpm 直接取 selector 的目标档位——生成曲天然落在选曲目标附近，pick_track 的
最近匹配一拍即合。自定义 caption 覆盖预设（用户在引擎中心填了描述就听用户的）。
"""

from __future__ import annotations

from dataclasses import dataclass

from dramaclip.engines.bgm.selector import target_bpm

#: 情绪 → 器乐 caption 预设（英文音乐标签；每种情绪一种可复现的配乐气质）
EMOTION_CAPTIONS: dict[str, str] = {
    "default": (
        "Cinematic underscore, warm strings and soft piano, steady neutral "
        "narrative bed, gentle momentum, no vocals"
    ),
    "suspense": (
        "Tense suspense underscore, pulsing low strings, ticking percussion, "
        "dark atmospheric drones, rising unease, no vocals"
    ),
    "anger": (
        "Aggressive action score, driving percussion, brass stabs, intense "
        "orchestral momentum, confrontational energy, no vocals"
    ),
    "triumph": (
        "Heroic uplifting orchestral score, soaring brass, triumphant strings, "
        "epic build and peak, no vocals"
    ),
    "sadness": (
        "Melancholic emotional score, slow piano, mournful strings, sparse "
        "gentle and heartfelt, no vocals"
    ),
}

#: 纯器乐的歌词位占位（上游约定：[Instrumental] = 无人声）
INSTRUMENTAL_LYRICS = "[Instrumental]"

#: BGM 床的合法时长档（秒）：曲库交接口径 90s+，两档都远超铺轨需求
DURATION_CHOICES = (120, 180)


@dataclass(frozen=True)
class GenerateRequest:
    """一次单曲生成的完整参数（engine.generate 的输入形状）。"""

    caption: str
    lyrics: str
    duration_s: float
    bpm: float | None
    emotion: str  # 落库归类用（生成参数本身不消费它）


def build_request(
    emotion: str,
    duration_s: float,
    caption_override: str | None = None,
    bpm: float | None = None,
) -> GenerateRequest:
    """情绪+时长 → 生成请求。caption 覆盖为空串时回退预设（不生成无描述请求）。"""
    caption = (caption_override or "").strip() or EMOTION_CAPTIONS.get(
        emotion, EMOTION_CAPTIONS["default"]
    )
    return GenerateRequest(
        caption=caption,
        lyrics=INSTRUMENTAL_LYRICS,
        duration_s=float(duration_s),
        bpm=float(bpm) if bpm is not None else target_bpm(emotion),
        emotion=emotion,
    )

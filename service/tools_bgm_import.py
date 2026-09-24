"""把散落的 BGM 文件归置进 data/bgm/<emotion>/ 并登记 manifest（一次性小工具）。

用法（service/ 下）：
    ../.venv/Scripts/python.exe tools_bgm_import.py <情绪> <文件...>
    例：../.venv/Scripts/python.exe tools_bgm_import.py suspense ~/Downloads/epic.mp3

- 情绪 ∈ default/anger/triumph/suspense/sadness
- 文件被复制（不是移动）进 data/bgm/<emotion>/<emotion>_NN.<ext>，NN 自动续号
- bgm_manifest.json 自动追加登记：license/attribution/source_url 默认给
  Pixabay Content License 口径（Pixabay 下载用这个工具就不用再手填）；
  其他来源的曲子请事后手改 manifest 对应条目
- 重跑安全：同名已存在则跳过该文件

之后跑扫描入库（第二波 RPC 没接之前手动跑一次）：
    ../.venv/Scripts/python.exe -c "
    import sys; sys.path.insert(0, '.')
    from pathlib import Path
    from dramaclip.engines.bgm.library import scan_library
    from dramaclip.infra.storage import db
    from dramaclip.infra.storage.repos import bgm
    res = scan_library(Path('../data/bgm'))
    conn = db.connect()
    db.migrate(conn)
    for t in res.tracks:
        bgm.upsert_track(conn, file_path=str(t.file), emotion=t.emotion,
                         duration_s=t.duration_s, bpm=t.bpm, license=t.license,
                         attribution=t.attribution, source_url=t.source_url)
    conn.close()
    print('入库', len(res.tracks), '首; 跳过', len(res.skipped))
    for p, why in res.skipped: print('  SKIP', p.name, why)
    "
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

EMOTIONS = {"default", "anger", "triumph", "suspense", "sadness"}
BGM_DIR = Path(__file__).resolve().parent.parent / "data" / "bgm"
MANIFEST = BGM_DIR / "bgm_manifest.json"
AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".ogg"}

PIXABAY_LICENSE = "Pixabay Content License (free for commercial use, no attribution required)"
PIXABAY_URL = "https://pixabay.com/service/license-summary/"


def _next_index(emotion_dir: Path, emotion: str) -> int:
    existing = [
        int(m.group(1))
        for f in emotion_dir.glob(f"{emotion}_*.??*")
        if (m := re.match(rf"^{emotion}_(\d+)\.", f.name))
    ]
    return max(existing, default=0) + 1


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    emotion = argv[1].strip().lower()
    if emotion not in EMOTIONS:
        print(f"情绪 {emotion!r} 不在 5 键内: {sorted(EMOTIONS)}")
        return 2
    sources = [Path(a).expanduser() for a in argv[2:]]

    emotion_dir = BGM_DIR / emotion
    emotion_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, str]] = {}
    if MANIFEST.is_file():
        try:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"警告: {MANIFEST} 解析失败，将重建（旧文件备份为 .bak）")
            MANIFEST.rename(MANIFEST.with_suffix(".json.bak"))
            manifest = {}

    idx = _next_index(emotion_dir, emotion)
    imported = 0
    for src in sources:
        if not src.is_file():
            print(f"跳过（不是文件）: {src}")
            continue
        if src.suffix.lower() not in AUDIO_SUFFIXES:
            print(f"跳过（不是音频后缀）: {src.name}")
            continue
        target = emotion_dir / f"{emotion}_{idx:02d}{src.suffix.lower()}"
        if target.exists():
            print(f"跳过（已存在）: {target.name}")
            continue
        shutil.copy2(src, target)
        manifest[f"{emotion}/{target.name}"] = {
            "license": PIXABAY_LICENSE,
            "attribution": "",  # Pixabay 不要求署名；其他来源请手填
            "source_url": PIXABAY_URL,
        }
        print(f"已入库: {src.name} -> {target.relative_to(BGM_DIR.parent)}")
        idx += 1
        imported += 1

    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"完成: 新增 {imported} 首到 {emotion}/; manifest 共 {len(manifest)} 条登记")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

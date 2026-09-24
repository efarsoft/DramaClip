"""把 data/bgm 曲库扫描入库（一次性运行：migrate 019 → scan → upsert）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dramaclip.engines.bgm.library import scan_library
from dramaclip.infra import paths
from dramaclip.infra.storage import db
from dramaclip.infra.storage.repos import bgm

data_dir = paths.resolve_data_dir({"DRAMACLIP_DATA_DIR": r"D:\PersonProjects\DramaClip\data"})
applied = []
conn = db.connect(data_dir / "data.db")
try:
    applied = db.migrate(conn)
    print("migrate applied:", applied or "(无新迁移)")
    res = scan_library(data_dir / "bgm")
    for t in res.tracks:
        bgm.upsert_track(
            conn,
            file_path=str(t.file),
            emotion=t.emotion,
            duration_s=t.duration_s,
            bpm=t.bpm,
            license=t.license,
            attribution=t.attribution,
            source_url=t.source_url,
        )
    print(f"入库 {len(res.tracks)} 首; 跳过 {len(res.skipped)}")
    for p, why in res.skipped:
        print("  SKIP", p.name, why)
    # 读回验证（写后必读）
    rows = bgm.list_all(conn)
    print("库内曲目:", len(rows))
    for r in rows:
        print(
            f"  {r['emotion']:9s} bpm={r['bpm']!s:6s} {r['duration_s']:6.1f}s "
            f"lic={'Y' if r['license'] else '-'} {Path(r['file_path']).name}"
        )
finally:
    conn.close()
print("DONE")

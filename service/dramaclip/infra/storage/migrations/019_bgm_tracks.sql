-- 019: BGM 曲库（C 项第一波）——扫描一次、机器测的索引落库，运行时选曲只读表。
-- 三层分工见 engines/bgm/library.py 模块 docstring：子文件夹=情绪（人摆），
-- bgm_manifest.json=资产说明（license/署名/出处，跟素材走），本表=机器索引。
-- file_path UNIQUE：重扫同目录幂等（同路径覆盖元数据，不重复插行）。
CREATE TABLE IF NOT EXISTS bgm_tracks (
  id          TEXT PRIMARY KEY,
  file_path   TEXT NOT NULL UNIQUE,
  emotion     TEXT NOT NULL,
  duration_s  REAL NOT NULL,
  bpm         REAL,
  license     TEXT NOT NULL DEFAULT '',
  attribution TEXT NOT NULL DEFAULT '',
  source_url  TEXT NOT NULL DEFAULT '',
  added_at    INTEGER NOT NULL
);

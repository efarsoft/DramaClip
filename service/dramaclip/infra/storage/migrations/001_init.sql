-- v2 初始 schema。权威定义：docs/service/04-数据模型.md
-- 约定：主键=UUID hex；时间戳=Unix 毫秒；复杂结构=JSON 存 TEXT。

CREATE TABLE IF NOT EXISTS projects (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  source_path TEXT NOT NULL UNIQUE,
  status      TEXT NOT NULL DEFAULT 'created',   -- created|analyzing|ready|exporting
  created_at  INTEGER NOT NULL,
  updated_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
  id             TEXT PRIMARY KEY,
  project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  episode_number INTEGER NOT NULL,
  source_path    TEXT NOT NULL,
  duration       REAL,
  status         TEXT NOT NULL DEFAULT 'pending', -- pending|prescreened|analyzing|done|failed
  created_at     INTEGER NOT NULL,
  UNIQUE (project_id, episode_number)
);
CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes(project_id);

CREATE TABLE IF NOT EXISTS episode_prescreen (
  episode_id           TEXT PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
  audio_peak_density   REAL NOT NULL,
  scene_cut_density    REAL NOT NULL,
  voice_activity_ratio REAL NOT NULL,
  motion_intensity     REAL NOT NULL,
  prescreen_score      REAL NOT NULL,
  recommended          INTEGER NOT NULL,
  created_at           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS episode_analysis (
  id              TEXT PRIMARY KEY,
  episode_id      TEXT NOT NULL UNIQUE REFERENCES episodes(id) ON DELETE CASCADE,
  asr_segments    TEXT NOT NULL,   -- JSON
  scene_data      TEXT,            -- JSON
  conflict_scores TEXT,            -- JSON
  highlights      TEXT,            -- JSON
  genre           TEXT,
  characters      TEXT,            -- JSON
  analyzed_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS narration_plans (
  id             TEXT PRIMARY KEY,
  project_id     TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  narration_mode TEXT NOT NULL,    -- 九种模式枚举值
  episode_ids    TEXT NOT NULL,    -- JSON array
  plan_data      TEXT NOT NULL,    -- JSON 编排方案
  tts_segments   TEXT,             -- JSON
  status         TEXT NOT NULL DEFAULT 'pending',  -- pending|generating|ready|failed
  created_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS export_jobs (
  id                TEXT PRIMARY KEY,
  project_id        TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  narration_plan_id TEXT REFERENCES narration_plans(id),
  narration_mode    TEXT,
  subtitle_preset   TEXT,
  output_path       TEXT,
  status            TEXT NOT NULL DEFAULT 'pending', -- pending|running|completed|failed|cancelled
  progress          REAL NOT NULL DEFAULT 0,
  created_at        INTEGER NOT NULL,
  completed_at      INTEGER
);

CREATE TABLE IF NOT EXISTS tts_cache (
  id         TEXT PRIMARY KEY,
  text_hash  TEXT NOT NULL UNIQUE,
  engine     TEXT NOT NULL,
  voice_id   TEXT NOT NULL,
  audio_path TEXT NOT NULL,
  duration   REAL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS subtitle_presets (
  id             TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  base_preset_id TEXT,             -- 派生自哪个内置预设（ADR-008）
  data           TEXT NOT NULL,    -- JSON 四维度覆盖
  created_at     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id         TEXT PRIMARY KEY,
  type       TEXT NOT NULL,        -- prescreen|analysis|narration|tts|export|model_download
  ref_id     TEXT,
  status     TEXT NOT NULL,        -- pending|running|completed|failed|cancelled
  progress   REAL NOT NULL DEFAULT 0,
  error      TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

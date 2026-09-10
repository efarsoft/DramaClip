-- 007: 引擎配置多实例（云端/服务端点按域管理，单启用）
CREATE TABLE IF NOT EXISTS engine_configs (
    id         TEXT PRIMARY KEY,
    domain     TEXT NOT NULL,      -- llm | tts_cloud | asr_cloud | image | video
    name       TEXT NOT NULL,      -- 用户命名（如 "token-plan qwen"）
    base_url   TEXT DEFAULT '',
    api_key    TEXT DEFAULT '',
    model      TEXT DEFAULT '',
    enabled    INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_engine_configs_domain ON engine_configs(domain);

-- 迁移存量 LLM 端点为一条已启用配置（仅当曾配置过且该域尚无配置）
INSERT INTO engine_configs (id, domain, name, base_url, api_key, model, enabled, created_at)
SELECT
    'llm-migrated',
    'llm',
    '默认配置',
    (SELECT value FROM settings WHERE key = 'llm.base_url'),
    (SELECT value FROM settings WHERE key = 'llm.api_key'),
    (SELECT value FROM settings WHERE key = 'llm.model'),
    1,
    strftime('%s', 'now') * 1000
WHERE (
    SELECT COALESCE((SELECT value FROM settings WHERE key = 'llm.base_url'), '')
) != ''
  AND NOT EXISTS (SELECT 1 FROM engine_configs WHERE domain = 'llm');

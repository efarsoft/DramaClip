-- P-1 地基：队列页需要人读标签与项目级参数覆盖。
-- 权威定义同步更新 docs/service/04-数据模型.md。
ALTER TABLE jobs ADD COLUMN label TEXT;
ALTER TABLE projects ADD COLUMN settings TEXT NOT NULL DEFAULT '{}';

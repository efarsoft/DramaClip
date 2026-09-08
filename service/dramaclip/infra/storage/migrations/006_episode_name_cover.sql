-- 素材列表展示与排序：集名称（扫描时取文件名）+ 封面缩略图
ALTER TABLE episodes ADD COLUMN name TEXT NOT NULL DEFAULT '';
ALTER TABLE episodes ADD COLUMN cover_path TEXT;

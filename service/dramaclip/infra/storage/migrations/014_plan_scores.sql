-- B10 六维文案评分：软信号三列（NULL=未评分）。
-- 评分只做排序信号+改进建议，绝不参与 grade/defects 硬门禁——所以三列全可空，
-- 老行/评分失败的行保持 NULL，list_plans 对其逐字节降级为现状顺序。
ALTER TABLE narration_plans ADD COLUMN score_total REAL;
ALTER TABLE narration_plans ADD COLUMN score_dims TEXT;
ALTER TABLE narration_plans ADD COLUMN suggestion TEXT;

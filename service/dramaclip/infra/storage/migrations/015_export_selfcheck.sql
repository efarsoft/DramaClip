-- 成片自检四项（09-10 §4.5 徽章 / 接口改动点 #29，verify_modes.py 判据产品化）：
--   selfcheck       度量成绩单 JSON（复杂结构存 TEXT，001_init 头注的既有约定）。
--                   逐项 pass 三态：true=实测过线 / false=实测不过 / null=量不到
--                   （宁灰勿假绿：徽章显示「—」，不发未验证绿勾）。
--   selfcheck_state 汇总列 passed|failed|partial，由 engines.exporter.selfcheck.
--                   overall_state 在写侧一次算好——作品库「筛选·自检通过」（#30）
--                   走等值谓词，列表查询零 JSON 解析。
-- 两列皆 NULL = 从未自检：历史成片由 export.selfcheck 补测（jobs.type 词表随之
-- 增加 export_selfcheck，本文件即登记处；001_init 的注释保持历史原样不回改）。
ALTER TABLE export_jobs ADD COLUMN selfcheck TEXT;
ALTER TABLE export_jobs ADD COLUMN selfcheck_state TEXT;

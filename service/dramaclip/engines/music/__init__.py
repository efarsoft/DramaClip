"""配乐生成域（music）：ACE-Step 1.5 本地 BGM 生成。

分层：generator（情绪→请求参数，纯函数）/ engine（双路径装配 + junction 视图）/
workers/acestep_worker（venv 内推理，自包含）。产物是 48kHz wav，由 api/bgm.py
转码入库——本域不碰 bgm_tracks 表与曲库目录。
"""

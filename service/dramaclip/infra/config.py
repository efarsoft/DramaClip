"""设置：代码默认值 + DB 覆盖。DB 为唯一读取源（docs/service/03 第 2 节）。
"""

from __future__ import annotations

import sqlite3

from dramaclip.infra.storage.repos import settings as settings_repo

# 单一真相源（docs/04 §5.2）：以下数值只在此处定义一次，别处一律 import 不再各写一份。
# 放在 infra 而非渲染层，是因为依赖方向恒为 engines → infra——
# 反过来让 encoder 当设置的源会成环，所以设置的默认值与渲染几何同源读这里。
# 画布**上限**而非成片尺寸：成片画幅跟随首集源等比确定（encoder.resolve_canvas，
# 长边贴这里的长边），横屏源出 16:9、竖屏源出 9:16，不足处补黑 —— ADR-010。
# settings 键 export.width/height 可改，设置页「出片」分区有输入框。
EXPORT_WIDTH = 1080
EXPORT_HEIGHT = 1920
PRESCREEN_THRESHOLD = 70  # 预筛推荐线：评分量纲 0-100（prescreen 四项权重和为 100）

DEFAULTS: dict[str, str] = {
    "analysis.full_threshold": "15",
    "analysis.prescreen_threshold": str(PRESCREEN_THRESHOLD),
    "analysis.ocr_enabled": "1",
    "asr.engine": "faster_whisper",
    "asr.model": "small",  # paraformer 用户曾切；默认档见引擎页推荐卡
    # 设备选择：faster-whisper（auto=ctranslate2 按设备挑精度档）与 funasr 双引擎
    # （auto=torch.cuda 探测，CUDA 初始化失败自动回退 CPU）共用这一个键
    "asr.device": "auto",
    # auto = 把精度决定权交给 ctranslate2 按实际设备挑最快可用档（CPU→int8，
    # CUDA→float16/float32），与 faster-whisper 上游默认一致。存量库已落 int8 的
    # 不迁移（load 不覆盖显式值）——由 transcriber 的 _compute_for 映射兜底，
    # 行为与 auto 等价，原因见该处 docstring。
    "asr.compute_type": "auto",
    "asr.language": "zh",
    # 视觉轨档位（P2b）：kind=vision 的 model_id（qwen3-vl-2b/4b/8b）；空 = 视觉轨关闭（分档语义）
    "vision.model": "",
    # 停顿切分（P1 本地 ASR 基础设施）：能量检测找句间停顿，按停顿切片段逐段转写；"0"=整条直喂
    "asr.pause_split": "1",
    # P1 云端引擎凭据（按量计费；空 = 云端引擎不可用，本地引擎不受影响）
    "asr.api_key": "",
    "tts.api_key": "",
    # 云端 TTS 模型名：tts_cloud 域启用即由 engine_configs 镜像写入（同 llm.model）。
    # 不登记在这里，读它的地方就只能靠猜——工厂的 "cosyvoice-v2" 默认值会替业主选模型。
    "tts.model": "",
    # 说话人分离（仅 paraformer 生效）：聚类自动判人数（1~15），num_speakers>0
    # 则经 preset_spk_num 指定。分离模型未下载时 funasr 按别名自行拉取（cam++/
    # fsmn-vad 共约 30MB），资产库登记项可管理下载。
    "asr.diarization": "true",
    "asr.num_speakers": "0",
    "subtitle.default_preset": "conflict-impact",
    "subtitle.smart_match": "true",
    "llm.base_url": "",
    "llm.api_key": "",
    "llm.model": "",
    # 空 = 各调用点自带默认（chat 60s / 文案与金句更长）。不登记就没人能设：
    # settings.update 拒未知键，实测本仓 2026-10-06 之后一直是「代码能读、界面上写不进」。
    "llm.timeout_s": "",
    # 视觉云端会话（OpenAI 兼容端点）：tts/image 域之外由 engine_configs 的 image
    # 域启用即镜像写入（见 api/engine_configs._MIRROR）。原先这四个键只存在于库里、
    # DEFAULTS 里没有——`vision.cloud_api_key` 因而不是「已登记的设置键」，
    # settings.get 的脱敏判据也就没覆盖到它（实测明文回显，本次修）。
    "vision.cloud": "",
    "vision.cloud_base_url": "",
    "vision.cloud_api_key": "",
    "vision.cloud_model": "",
    "tts.engine": "edge",
    # 音色按引擎独立成键：两引擎音色体系互不相通（Kokoro 音色名 / 微软官方名）
    "tts.voice.kokoro": "zf_001",
    "tts.voice.edge": "zh-CN-XiaoxiaoNeural",
    # 语速（"1.1" 这类倍率字符串）：空 = 引擎默认。同 tts.model 的口径——
    # 读它的代码存在，键就必须在这里有名字。
    "tts.speed": "",
    "narration.style_id": "auto",
    # 每模式的方案数 K（规格 §4.3「方案数 K 」的全局默认；项目级覆盖走 projects.settings）
    "narration.variants_per_mode": "1",
    # 复述测试（软质检）：无上下文观众闭卷复述度量可懂度，结论进 trace；"0"=关闭
    "narration.retell_check": "1",
    "download.hf_mirror": "https://hf-mirror.com",
    "download.ms_base": "https://modelscope.cn",
    # 成片响度目标（EBU R128）：Phase C 整片两遍 loudnorm 收口，见 engines/exporter/loudness.py
    "export.loudness_target_lufs": "-14",
    "export.loudness_true_peak_dbtp": "-1.5",
    "export.encoder": "auto",
    "export.width": str(EXPORT_WIDTH),
    "export.height": str(EXPORT_HEIGHT),
    # AI 生成标注（业主裁决 2026-10-15）：默认关闭；开启后成片右上角烧「AI 生成」
    # 字样（engines/exporter/ai_label.py，loudness 之后的独立 drawtext 遍）。
    # 平台标注要求因平台而异，是否标注由使用者按发布平台自行决定——不强制、不代决。
    "export.ai_label": "false",
    "hardware.max_parallel_jobs": "2",
    # Agent 网关（本机 127.0.0.1 HTTP 工具面：外部 agent 调用审查/出稿；api/agent_gateway.py）
    "agent_gateway.enabled": "false",
    "agent_gateway.port": "8340",
    # 空 = 首次启用时自动生成并写回（偏好设置页可见）
    "agent_gateway.token": "",
}

Settings = dict[str, str]


def load(conn: sqlite3.Connection) -> Settings:
    """缺省键全量落库，返回完整设置（默认值 + 用户覆盖）。"""
    stored = settings_repo.get_all(conn)
    for key, value in DEFAULTS.items():
        if key not in stored:
            settings_repo.set_value(conn, key, value)
            stored[key] = value
    return stored


def get_int(settings: Settings, key: str) -> int:
    """按 int 读取；缺失/非法回退默认值（docs/service/03 第 2 节约定）。"""
    try:
        return int(settings[key])
    except (KeyError, ValueError):
        return int(DEFAULTS.get(key, "0"))


def get_float(settings: Settings, key: str) -> float:
    """按 float 读取；settings 里缺失或脏值回退 DEFAULTS。
    """
    try:
        return float(settings[key])
    except (KeyError, ValueError, TypeError):
        return float(DEFAULTS[key])


def get_bool(settings: Settings, key: str) -> bool:
    """按 bool 读取；真值集 {"1","true","on","yes"}（大小写不敏感），其余皆假。"""
    return str(settings.get(key, "")).strip().lower() in {"1", "true", "on", "yes"}

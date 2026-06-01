"""
视频分析管理器 - 向后兼容代理层

原 1365 行 God Module 已拆分为：
    - types.py        → AnalysisTask dataclass、类型别名、配置辅助函数
    - scoring.py      → 高光打分逻辑（多维度评分）
    - pipeline.py     → 子进程工作函数（multiprocessing worker）
    - orchestrator.py → AnalysisManager 核心编排逻辑

此文件仅做 re-export，确保所有已有 import 路径不变：
    from app.services.analyze.manager import AnalysisManager
    from app.services.analyze.manager import get_analysis_manager
    from app.services.analyze.manager import AnalysisTask
"""

# 核心类型（向后兼容）
from .types import (
    AnalysisTask,
    ASRResultUnion,
    _get_asr_config,
    _get_diarization_config,
)

# 编排器（向后兼容）
from .orchestrator import (
    AnalysisManager,
    get_analysis_manager,
)

# 子进程工作函数（向后兼容，pipeline 内部使用 lazy import 指向 AnalysisManager）
from .pipeline import run_process_analysis

# 高光打分（可选导出）
from .scoring import run_highlight_detection

__all__ = [
    "AnalysisTask",
    "ASRResultUnion",
    "AnalysisManager",
    "get_analysis_manager",
    "run_process_analysis",
    "run_highlight_detection",
    "_get_asr_config",
    "_get_diarization_config",
]

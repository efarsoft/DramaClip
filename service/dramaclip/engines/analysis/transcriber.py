"""ASR 引擎族门面：faster-whisper / SenseVoice / Paraformer / Dashscope 云端。

自拆分专项（2026-11）：引擎实现已拆到 engines/analysis/asr/ 子包——
common（Protocol + 设备解析 + 文本工具）、funasr（worker 桥）、
whisper/sensevoice/paraformer/cloud（四个引擎类 + 解析函数）。
本文件只做总 re-export，保持 `from dramaclip.engines.analysis.transcriber
import X` 的既有引用面不变（as 语法显式 re-export，mypy 认得）。
"""

from __future__ import annotations

# ---- pause_split：停顿切分（外部经 transcriber 访问） ----
from dramaclip.engines.analysis import pause_split as pause_split

# ---- cloud ----
from dramaclip.engines.analysis.asr.cloud import (
    DashscopeCloudAsrEngine as DashscopeCloudAsrEngine,
)
from dramaclip.engines.analysis.asr.common import (
    _CUDA_PROBLEM as _CUDA_PROBLEM,
)

# ---- common：Protocol + 设备解析 + 文本工具 ----
from dramaclip.engines.analysis.asr.common import (
    AsrEngine as AsrEngine,
)
from dramaclip.engines.analysis.asr.common import (
    _adopt_loaded_device as _adopt_loaded_device,
)
from dramaclip.engines.analysis.asr.common import (
    _ct2_cuda_available as _ct2_cuda_available,
)
from dramaclip.engines.analysis.asr.common import (
    _ExactMessageFilter as _ExactMessageFilter,
)
from dramaclip.engines.analysis.asr.common import (
    _group_by_gap as _group_by_gap,
)
from dramaclip.engines.analysis.asr.common import (
    _model_device as _model_device,
)
from dramaclip.engines.analysis.asr.common import (
    _pair as _pair,
)
from dramaclip.engines.analysis.asr.common import (
    _probe_cuda_op as _probe_cuda_op,
)
from dramaclip.engines.analysis.asr.common import (
    _punc_false_alarm_silenced as _punc_false_alarm_silenced,
)
from dramaclip.engines.analysis.asr.common import (
    _report_from_state as _report_from_state,
)
from dramaclip.engines.analysis.asr.common import (
    _resolve_torch_device as _resolve_torch_device,
)
from dramaclip.engines.analysis.asr.common import (
    simplify as simplify,
)

# ---- funasr：worker 桥 ----
from dramaclip.engines.analysis.asr.funasr import (
    _FunasrWorker as _FunasrWorker,
)
from dramaclip.engines.analysis.asr.funasr import (
    _inproc_funasr as _inproc_funasr,
)
from dramaclip.engines.analysis.asr.funasr import (
    _spawn_funasr_worker as _spawn_funasr_worker,
)
from dramaclip.engines.analysis.asr.funasr import (
    shutdown_funasr_workers as shutdown_funasr_workers,
)

# ---- paraformer ----
from dramaclip.engines.analysis.asr.paraformer import (
    ParaformerEngine as ParaformerEngine,
)
from dramaclip.engines.analysis.asr.paraformer import (
    _parse_paraformer as _parse_paraformer,
)

# ---- sensevoice ----
from dramaclip.engines.analysis.asr.sensevoice import (
    SenseVoiceEngine as SenseVoiceEngine,
)
from dramaclip.engines.analysis.asr.sensevoice import (
    _parse_sensevoice as _parse_sensevoice,
)

# ---- whisper ----
from dramaclip.engines.analysis.asr.whisper import (
    FasterWhisperEngine as FasterWhisperEngine,
)

# ---- diarize：说话人聚类 ----
from dramaclip.engines.analysis.diarize import (
    _assign_speakers as _assign_speakers,
)
from dramaclip.engines.analysis.diarize import (
    _speaker_label as _speaker_label,
)
from dramaclip.engines.analysis.diarize import (
    _spk_spans as _spk_spans,
)

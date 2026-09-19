"""真机成片回归门禁：真实素材 → 真实编排 → 真实 ffmpeg 渲染 → 实测音轨/时长/冻结帧。

与单元测试的分界线：这里不 mock ffmpeg、不 mock TTS。桩测证明"代码按参数生成命令"，
本脚本证明"命令跑出来的片子真的有声音、响度打到 R128 目标、时长合理、没有静止画面"，
以及"文案确实是编剧模型写的"（逐模式验 `planner`）。

用法：
  .venv/Scripts/python scripts/verify_modes.py --modes full_narration
  .venv/Scripts/python scripts/verify_modes.py --modes all --out D:/tmp/dc-report

隔离：把 data/data.db 复制进临时目录再跑，产物写临时目录，绝不写开发者的真实 data/。

退出码（两档必须分清，否则运维会把环境问题读成产品崩了）：
  0 = 全部断言通过
  1 = 断言失败：产品或门禁本身有问题，逐条看下面的「失败」清单
  2 = 环境未就绪：缺 ffmpeg/素材/模型、TTS 或 LLM 预检不过、预期表与生产模式清单不一致。
      P-1.5 之后解说文案不再有模板兜底，LLM 没配就是七个解说模式必然全红——那是这一档。
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "service"))

from dramaclip.api import export as export_api
from dramaclip.api import narration as narration_api
from dramaclip.api.context import AppContext
from dramaclip.engines.analysis.runtime import AnalysisRuntime
from dramaclip.engines.exporter import encoder, loudness
from dramaclip.engines.narration import pipeline as narration_pipeline
from dramaclip.engines.semantic.llm_client import LlmClient, LlmConfig
from dramaclip.engines.tts.factory import create as create_tts
from dramaclip.infra import config
from dramaclip.infra import jobs as jobs_mod
from dramaclip.infra.storage import db
from dramaclip.transport.notify import Notifier
from dramaclip.transport.rpc import Router, RpcRequest

ALL_MODES = [
    "raw_clip", "intro_narration", "cross_narration", "ultra_short_hook",
    "dialogue_narration", "full_narration", "subtitle_flow",
    "dual_host_chat", "inner_monologue",
]

# 各模式的旁白预期，取自 docs/service/02 §3 与各模式 docstring 的设计定义。
# 写成表是为了不再拿"全局最小时长 + 一律要有旁白"去套所有模式——那会造成假失败。
EXPECT_NARRATION = {
    "raw_clip": "none",          # 零加工：不烧字幕、不遮罩、无旁白
    "subtitle_flow": "none",     # 金句流：只烧句级字幕，无旁白音频
    "intro_narration": "one",    # 片头解说：一段引子旁白 + 正片原声
    "cross_narration": "many",   # 原声/旁白交替
    "ultra_short_hook": "many",  # 钩子 + 收尾 CTA
    "dialogue_narration": "many",
    "full_narration": "many",    # 全片 ducked：每段都要旁白
    "dual_host_chat": "many",
    "inner_monologue": "many",
}

MIN_MEAN_VOLUME_DB = -70.0  # 近乎静音的判据：旁白整条丢失会落在这里
MAX_FREEZE_S = 2.0  # 任一静止段超过这么久即判失败

# 设计上"全程压底"的模式：`engines/narration/modes_w8.py::build_full` 给每一段都写
# `audio="ducked"`，所以这个模式的时间轴里不该出现原声直通段。业主立案④的排查项原话是
# "确认 narration 模式下 original 段全部 ducked"——那正是这段判据要钉住的东西。
ALL_DUCKED_MODES = {"full_narration"}

# 语音避让的段级声学判据（业主立案④「解说与原声同音量叠放」）：混音段的实测响度与
# 「旁白 + 按声明音量压底的原声」两者功率相加的**预测值**之差（下称残差），允许偏离这么多 dB。
# 两侧都是真机量的（素材：小小球神不好惹；TTS=kokoro；full_narration 全部 8 段，
# 干音 ≈−25 LUFS、源窗口 −10.8…−5.2 LUFS，正是"原声比解说响 15–20 dB"的难素材）：
#   · 压底按声明生效（volume=0.08）：残差 −0.87 … −0.05 dB；换一版重新生成的 8 段方案
#     独立复跑，落 −0.92 … −0.17 dB（门禁表格里那一列就是它的带符号最大值）；
#   · 压底彻底失效（同一条生产命令，只把 volume=0.08 换成 1.0）：残差 +8.83 … +9.91 dB。
# 阈值取 2.0：两轮合格侧最差 0.92 之上留一倍余量，失效侧最近 8.83 之下还有 6.8 dB。
# 为什么不用"混音段比干音响多少 dB"当判据：同一批段实测 0.50…2.00 dB，而它的上界完全由
# 素材热度决定（源越响、干音越轻，压底完全正确也能顶过 3 dB）——换个剧就假红。参照物带上
# 源窗口才与素材无关，这也是 `_check_ducking` 要量第三个数的唯一理由。
# 每次跑打出的「压底残差」列是本轮 |残差| 最大那一段的带符号值，逐段数值进 summary.json 的
# `duck_residuals`；要改这个数先看那一列。
DUCK_RESIDUAL_TOL_DB = 2.0

# 编排来源预期：文案真值化（P-1.5）之后，除零加工两模式外必须是 LLM 成稿。
# 这张表不是抄清单，是从代码事实推出来的：
#   · `api/narration.py::_NO_TTS_MODES` 恰好是 raw_clip / subtitle_flow，两者不产旁白槽位，
#     `_generate_one` 只在 `plan.narration_texts` 非空时才调 copywriter，
#     于是 `PlanData.planner` 停在默认值 "rule"（`engines/narration/models.py`）；
#   · dialogue_narration 走 `script_driver`，`build_from_script_episodes` 里直接写
#     `planner="llm_script"`；
#   · 其余五个模式由 `copywriter.write_plan_copy` 置 `planner="llm_script"`，
#     而它已无模板兜底（Task 5），拿不到合格文案就抛，不会悄悄退回 "rule"。
# 九模式清单与 `SUPPORTED_MODES` / `pipeline.MODE_LABELS` 逐名核对一致（main() 里还有一道
# 运行时核对，见那里的注释）。
EXPECT_PLANNER = {
    "raw_clip": "rule",
    "subtitle_flow": "rule",
    "intro_narration": "llm_script",
    "cross_narration": "llm_script",
    "ultra_short_hook": "llm_script",
    "dialogue_narration": "llm_script",
    "full_narration": "llm_script",
    "dual_host_chat": "llm_script",
    "inner_monologue": "llm_script",
}

# 响度窗口（LU）：实测 integrated 与目标的允许偏差。这个数是**实测出来的**，不是拍的：
# Task 8 落地（混音求和挂前瞻限幅 + Phase C 真峰有界重试）后，仓里九部真成片重跑一遍，
# integrated 落在 −15.01…−13.94 LUFS（对 −14 目标最大偏离 1.01 LU）、真峰 −3.77…−2.17 dBTP
# （门限 −1.0）。最差 1.01 LU 之上放到 2.5，一是给 dynamic 模式在更热素材上留余量
# （真峰值钳制时 loudnorm 打不满目标，实测残差 0.03–1.09 LU），二是门禁与 Phase C 用的是
# 两套量法（ebur128 vs loudnorm 内部测量，同一部片子实测差 0.2 LU），门禁比生产复核容差
# 2.0 松 0.5，免得量法差把绿片判红。
LOUDNESS_TOLERANCE_LU = 2.5

FFMPEG = str(REPO / "resources" / "ffmpeg" / "ffmpeg.exe")
FFPROBE = str(REPO / "resources" / "ffmpeg" / "ffprobe.exe")

# 渲染命令插桩：记录每段用的音频角色与是否真的带上了旁白输入
CAPTURED: list[dict[str, Any]] = []
_ORIG_CUT_ARGS = encoder.cut_segment_args


def _capturing_cut_args(*args: Any, **kw: Any) -> list[str]:
    result = _ORIG_CUT_ARGS(*args, **kw)
    audio = str(kw.get("audio") or (args[3] if len(args) > 3 else ""))
    tts = kw.get("tts_audio")
    filter_complex = ""
    if "-filter_complex" in result:
        filter_complex = str(result[result.index("-filter_complex") + 1])
    CAPTURED.append({
        "audio": audio,
        "has_tts_input": bool(tts),
        "tts_path": str(tts) if tts else None,
        "mixed": "-filter_complex" in result,
        "cmd_tail": result[-6:],
        # 压底音量、段文件与**源窗口**都在这一段落地：音量证明滤镜真写了 volume=，
        # 段文件是测量对象，源窗口给出"压底之前那层原声有多响"——业主立案④的声学
        # 判据少这三样里的任何一样都立不起来（理由见 `_check_ducking`）。
        # `-i` 在这条命令里出现两次（源、旁白），`index` 取到的第一个就是源。
        "filter_complex": filter_complex,
        "out_path": str(result[-1]),
        "source": str(result[result.index("-i") + 1]),
        "start": float(result[result.index("-ss") + 1]),
        "end": float(result[result.index("-to") + 1]),
    })
    return result


encoder.cut_segment_args = _capturing_cut_args  # type: ignore[assignment]

# Phase C 真峰重试留痕：只报数，**绝不断言**。
# `loudness.normalize_in_place` 复核专因真峰超标时，换更大滤镜余量从原始成片重编**一次**
# （AAC 过冲对所请求的 TP 不单调，任何固定余量都不可能证明够用）；触发那条是 WARNING，
# 重试后过门那条是 INFO。所以"数这个模块的 WARNING 条数"就等于"数重试次数"。
# 为什么不断言：门禁量的是**最终成片**，靠重试过门的片子照样合格，断言它等于要求首遍必过，
# 会把一条合法路径判红。为什么还是要数：限幅器落地后新渲染的片子重试应当近乎为零，
# 频繁出现说明上游又坏了（见计划 Task 8「增补」末条）——这是给 Task 10 看的信息。
# 按级别数、不按文案匹配：文案会漂，级别不会；哪天真加了第二条 WARNING，
# 这个数就变成"响度模块的告警数"，仍然是信息，不会变成假绿。
_LOUDNESS_LOGGER = "dramaclip.engines.exporter.loudness"


class _LoudnessWarnCounter(logging.Handler):
    """挂在 Phase C 的 logger 上数 WARNING 条数（线程安全由 logging.Handler 自己保证）。"""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


LOUDNESS_WARNS = _LoudnessWarnCounter()


def sh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=False)


def mean_volume_db(video: Path) -> float | None:
    proc = sh([FFMPEG, "-hide_banner", "-i", str(video), "-map", "0:a:0",
               "-af", "volumedetect", "-f", "null", "-"])
    for line in proc.stderr.splitlines():
        if "mean_volume" in line:
            try:
                return float(line.split("mean_volume:")[1].strip().removesuffix(" dB"))
            except ValueError:
                return None
    return None


def ebur128(video: Path) -> tuple[float | None, float | None]:
    """(integrated LUFS, true peak dBFS)；解析不出返回 (None, None)。

    为什么要另开一测：`volumedetect` 的 mean_volume 只是平均样本幅值，与 R128 的
    integrated 不是一回事（一部压得很响但门控掉的片子可以 mean_volume 合格而 LUFS 偏 10 LU），
    而 Phase C 收口的是 LUFS。`ebur128` 才是 R128 权威量法。两个值取同一次运行：
    每调一遍就要整片解码一次音频，为省一行代码跑两遍是白花一分钟。

    命令形态**照真机改过**（`resources/ffmpeg` 8.1.1-essentials）。计划原稿写的是
    `-filter_complex "ebur128=peak=true"` 配 `-map 0:a:0`，在这个版本上直接失败：
    `-map` 先把 0:a:0 占用掉，滤镜图找不到未使用的输入，ffmpeg 报
    `Cannot find an unused audio input stream to feed the unlabeled input pad
    ebur128:default` 并非零退出，stderr 里没有 Summary —— 于是**每部片子都返回
    (None, None)**，九个模式一起报"门禁本身不可信"。改用简单滤镜链 `-af`
    （与上面 `mean_volume_db` 的 `-af volumedetect` 同形态）。
    `framelog=quiet` 只为压掉逐帧行（同一部片子实测 stderr 544 行 → 42 行），Summary 照打。

    真机 Summary 布局（原样捕获，不是从计划里抄的）：

        [Parsed_ebur128_0 @ 0x...] Summary:

          Integrated loudness:
            I:         -29.4 LUFS
            Threshold: -39.6 LUFS

          Loudness range:
            LRA:         3.9 LU
            ...

          True peak:
            Peak:      -10.5 dBFS

    交叉验证：同一部片子另跑 loudnorm 测量遍，`input_i=-29.59` / `input_tp=-10.49`，
    与 ebur128 的 −29.4 / −10.5 差 0.2 LU、0.01 dB（两套实现的门控与过采样细节不同）——
    量法可信，且这点差就是 LOUDNESS_TOLERANCE_LU 比生产容差松 0.5 的理由之一。

    静音片实测（`anullsrc` 造的 5 s 纯静音）：`I: -70.0 LUFS`、`Peak: -inf dBFS`。
    两个都能被 float() 解析，于是响度窗口那条必然变红（−70 对 −14 差 56 LU），
    真峰那条对静音天然通过——静音由响度窗口和 MIN_MEAN_VOLUME_DB 负责判，不需要特例。
    """
    proc = sh([FFMPEG, "-hide_banner", "-nostats", "-i", str(video), "-map", "0:a:0",
               "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"])
    lines = proc.stderr.splitlines()
    integrated: float | None = None
    peak: float | None = None
    for i, line in enumerate(lines):
        if line.strip().startswith("Integrated loudness:"):
            for cand in lines[i + 1:i + 4]:
                if cand.strip().startswith("I:"):
                    try:
                        integrated = float(cand.split("I:")[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
        if line.strip().startswith("True peak:"):
            for cand in lines[i + 1:i + 4]:
                if cand.strip().startswith("Peak:"):
                    try:
                        peak = float(cand.split("Peak:")[1].strip().split()[0])
                    except (ValueError, IndexError):
                        pass
    return integrated, peak


def source_window_lufs(video: Path, start: float, end: float) -> float | None:
    """只量源素材某一个区间的 R128（`-vn` 不重编码，几百毫秒一趟）。

    压底判据的第三条腿：不拿"这一段的原声本身有多响"当参照，就没有办法把
    "原声比解说响 20 dB 的素材"和"压底没生效"分开（见 `DUCK_RESIDUAL_TOL_DB`）。
    区间参数与 `cut_segment_args` 同形（`-ss`/`-to` 都在 `-i` 之前，都是输入时间），
    否则量的就不是渲染吃进去的那一段。
    """
    proc = sh([FFMPEG, "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
               "-i", str(video), "-vn", "-af", "ebur128=peak=true:framelog=quiet",
               "-f", "null", "-"])
    for line in proc.stderr.splitlines():
        if line.strip().startswith("I:"):
            try:
                return float(line.split("I:")[1].strip().split()[0])
            except (ValueError, IndexError):
                return None
    return None


def power_sum_db(*levels: float) -> float:
    """若干路声音按功率相加后的响度（dB）。

    混音不是取最大也不是取平均：`amix=normalize=0` 就是把样本相加，所以"这一段应当有多响"
    = 各路先转功率、相加、再转回 dB。压底是否真生效，判的就是这个数和实测的差。
    """
    return 10.0 * math.log10(sum(10.0 ** (level / 10.0) for level in levels))


def _fmt(value: Any, digits: int = 1) -> str:
    """表格数值列：没测出来打 `-`，绝不拿 0 冒充测量结果。

    0 dB / 0 LUFS / 0 dBTP 在听感上都是"很响"，把 None 印成 0 等于把"没量到"
    伪装成"量到了且合格"——正是本门禁最不能犯的错（历史上它已经假绿过一次）。
    """
    if value is None:
        return "-"
    return f"{float(value):.{digits}f}"


def _pad(text: str, width: int, align: str = ">") -> str:
    """按**显示宽度**补齐一格，align 取 ">"（右对齐）或 "<"（左对齐）。

    为什么不直接用 f"{text:>width}"：表头是中文，一个 CJK 字符在终端占两列而 len() 只算一列，
    用 len() 补出来的表头会比数据行（纯 ASCII/数字）宽出一截，逐列错开。
    """
    display = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    filler = " " * max(0, width - display)
    return text + filler if align == "<" else filler + text


def max_freeze_s(video: Path) -> float:
    proc = sh([FFMPEG, "-hide_banner", "-i", str(video), "-vf",
               "freezedetect=n=-60dB:d=1.0", "-map", "0:v:0", "-an", "-f", "null", "-"])
    values = [float(line.split("duration:")[1].strip())
              for line in proc.stderr.splitlines() if "freeze_duration" in line]
    return max(values, default=0.0)


def probe_duration_s(video: Path) -> float:
    proc = sh([FFPROBE, "-v", "error", "-show_entries", "format=duration",
               "-of", "json", str(video)])
    try:
        return float(json.loads(proc.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001 - 探测失败按 0 处理，交给时长断言去判
        return 0.0


def has_audio_stream(video: Path) -> bool:
    proc = sh([FFPROBE, "-v", "error", "-select_streams", "a", "-show_entries",
               "stream=codec_type", "-of", "csv=p=0", str(video)])
    return "audio" in proc.stdout


def build_context(data_dir: Path, models_dir: Path) -> tuple[AppContext, ThreadPoolExecutor]:
    conn = db.connect(data_dir / "data.db")
    settings = config.load(conn)
    store = jobs_mod.JobStore(conn)
    executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="verify")
    ctx = AppContext(
        conn=conn, settings=settings, notifier=Notifier(lambda _m: None),
        executor=executor, job_store=store,
        analysis_runtime=AnalysisRuntime(settings, models_dir),
        work_dir=data_dir / "cache" / "analysis", data_dir=data_dir,
    )
    return ctx, executor


def wait_job(store: jobs_mod.JobStore, job_id: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        job = store.get(job_id)
        if job and job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.5)
    return {"status": "timeout", "error": f">{timeout_s}s"}


def _same_drive_temp(prefix: str) -> Path:
    """临时目录必须与仓库同盘。

    跨盘时 os.path.relpath 给不出相对路径，ass 滤镜的盘符冒号转义随之失效
    （实测 ffmpeg 把路径当 original_size 解析而整段渲染失败）。
    """
    for base in (REPO, Path(tempfile.gettempdir())):
        try:
            target = Path(tempfile.mkdtemp(prefix=f"{prefix}_", dir=str(base)))
        except OSError:
            continue
        if target.exists():
            return target
    raise RuntimeError("无法创建临时目录")


def _mode_table_drift() -> list[str]:
    """门禁自己手抄的模式清单必须与生产清单逐名对上，返回不一致的说明列表。

    为什么要这道核对：三张预期表都用 `EXPECT_*.get(mode, 默认值)` 取值，新增一个模式而
    忘了登记时，它会**按默认值悄悄判绿**（新解说模式被当成 "rule" 来源、被当成 "many" 段旁白），
    这正是 `api/narration.py` 里明令"绝不另立第四份手抄模式清单"要防的事——而门禁手上就抄了
    三份。宁可开跑前就红，也不要一份过期预期表把 Task 10 的出口判据变成假绿。
    """
    authoritative = set(narration_api.SUPPORTED_MODES)
    problems: list[str] = []
    for name, table in (
        ("ALL_MODES", ALL_MODES),
        ("EXPECT_NARRATION", EXPECT_NARRATION),
        ("EXPECT_PLANNER", EXPECT_PLANNER),
        ("pipeline.MODE_LABELS", narration_pipeline.MODE_LABELS),
    ):
        missing = authoritative - set(table)
        extra = set(table) - authoritative
        if missing or extra:
            problems.append(
                f"{name} 与 SUPPORTED_MODES 不一致："
                + (f"缺 {sorted(missing)}" if missing else "")
                + ("、" if missing and extra else "")
                + (f"多出 {sorted(extra)}" if extra else "")
            )
    return problems


def _check_ducking(mode: str, captured: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    """语音避让（业主立案④「解说与原声同音量叠放」）的段级判据。

    三道一起才成立：
    · 编排道——设计上"全程压底"的模式（`ALL_DUCKED_MODES`）不允许有原声直通段。业主立案④
      的原话形状就是"解说与原声同音量叠放"，而那是 timeline 段标记层面的问题：命令与声学
      两条道都只查"已经混音的段"，一段压根没进混音分支的直通段从它们眼里是漏掉的。
    · 命令道——每个 narration/ducked 段的滤镜串必须带 `volume=<encoder 声明值>`，即"声明的
      音量真的写进了那条命令"。音量常量在 encoder 只定义一次、这里按名字读，所以它抓的是
      滤镜少没少，而不是数值对不对——变异实测把 ducked 音量改成 1.0 时这一道照样绿，
      那种失效只有声学道抓得住。
    · 声学道——每段量三个真数：该段自己的 TTS 干音 N、该段**源窗口**的 R128 S（压底之前的
      原声有多响）、混音产物 M。压底按声明生效时 M 应当等于 `power_sum_db(N, S + 20·lg v)`；
      实测与它的差超过 `DUCK_RESIDUAL_TOL_DB` 就是压底没照声明做事。只查命令不够：volume=
      写了但挂错链路、限幅器把整段钳了、amix 又偷偷归一化，都是听得见的事故、看不见的红。
      参照物必须带上 S：单拿 M−N 当判据的话，它的上界由素材热度决定而不是由压底决定。

    量不到一律算红、不算通过：段文件、干音与源窗口都在本次渲染摸得着的地方，读不到就是
    判据覆盖为 0——那正是本门禁历史上「零值空转通过」的形状。
    """
    bed_volumes = {
        "narration": encoder._NARRATION_BED_VOLUME,
        "ducked": encoder._DUCKED_BED_VOLUME,
    }
    failures: list[str] = []
    passthrough = [c for c in captured if c["audio"] == "original"]
    if mode in ALL_DUCKED_MODES and passthrough:
        failures.append(
            f"{mode}: 设计上全程压底，却有 {len(passthrough)}/{len(captured)} 段"
            "原声直通（audio=original，不走混音分支）—— 立案④的残留形状"
        )
    mixed = [c for c in captured if c["mixed"] and c["has_tts_input"]]
    residuals: list[float] = []
    for record in mixed:
        segment = Path(str(record["out_path"]))
        declared = bed_volumes.get(str(record["audio"]))
        if declared and f"volume={declared}" not in str(record["filter_complex"]):
            failures.append(
                f"{mode}: 段 {segment.name}（角色 {record['audio']}）滤镜里没有 "
                f"volume={declared} —— 压底参数没落地"
            )
        dry = Path(str(record["tts_path"]))
        source = Path(str(record["source"]))
        if not segment.is_file() or not dry.is_file() or not source.is_file():
            failures.append(f"{mode}: 量不到压底（{segment.name} / {dry.name} /"
                            f" {source.name} 有不在的）")
            continue
        voiced, _ = ebur128(segment)
        dry_lufs, _ = ebur128(dry)
        bed_lufs = source_window_lufs(source, float(record["start"]), float(record["end"]))
        if voiced is None or dry_lufs is None or bed_lufs is None:
            failures.append(f"{mode}: {segment.name} 三处响度没量齐（段={voiced}"
                            f" 干音={dry_lufs} 源窗口={bed_lufs}），压底判据本轮不可信")
            continue
        if declared is None:
            failures.append(f"{mode}: {segment.name} 角色 {record['audio']} 没有声明压底音量，"
                            "压底判据量不了它")
            continue
        bed_gain = 20.0 * math.log10(float(declared))
        residuals.append(voiced - power_sum_db(dry_lufs, bed_lufs + bed_gain))
    if mixed and not residuals:
        failures.append(f"{mode}: {len(mixed)} 段混音一段都没量到 —— 本行压底结论无效")
    worst = max(residuals, key=abs) if residuals else None
    if worst is not None and abs(worst) > DUCK_RESIDUAL_TOL_DB:
        # 不拿方向当诊断写进结论：正残差实测是压底失效（+8.83…+9.91），但负残差既可能是
        # amix 偷偷归一化、也可能是这条段本来就热到撞上限幅器——三种都是听得见的事故，
        # 区分它们要看的不是符号而是 `duck_residuals` 逐段值（全体一致 = 命令级问题，
        # 个别段炸开 = 素材级）。这里只负责把"偏离了声明"报出来。
        failures.append(
            f"{mode}: 混音段实测响度与「干音 + 按声明音量压底的原声」的预测值最大偏差 "
            f"{worst:+.2f} dB（容差 ±{DUCK_RESIDUAL_TOL_DB} dB，两侧实测值见该常量注释）"
            " —— 压底没照声明做事"
        )
    return failures, {
        "duck_segments": len(mixed),
        "duck_measured": len(residuals),
        "duck_residuals": [round(r, 2) for r in residuals],
        "duck_max_residual_db": None if worst is None else round(worst, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--media", default=r"D:\BaiduNetdiskDownload\小小球神不好惹")
    ap.add_argument("--modes", default="full_narration", help="逗号分隔，或 all")
    ap.add_argument("--out", default="")
    ap.add_argument("--job-timeout", type=float, default=1800.0)
    ap.add_argument(
        "--require-cross-episode",
        action="store_true",
        help="每部成片必须真的用到 ≥2 集素材（P-2a 定案做真跨集；默认只记录不判）",
    )
    args = ap.parse_args()

    modes = ALL_MODES if args.modes == "all" else [m.strip() for m in args.modes.split(",")]
    for exe in (FFMPEG, FFPROBE):
        if not Path(exe).is_file():
            print(f"缺少可执行文件：{exe}（随包 resources/ffmpeg/ 缺失，请重新安装或补齐）", file=sys.stderr)
            return 2
    # 预期表核对排在最前面（连临时目录都不建）：表都过期了，跑出来的绿是假绿。
    drift = _mode_table_drift()
    if drift:
        for line in drift:
            print(f"门禁不可信：{line}", file=sys.stderr)
        print("先修门禁里的模式清单，再谈产品结论", file=sys.stderr)
        return 2
    out_dir = Path(args.out) if args.out else _same_drive_temp("tmp_dc-verify")
    out_dir.mkdir(parents=True, exist_ok=True)

    src_db = REPO / "data" / "data.db"
    if not src_db.is_file():
        print("缺少 data/data.db，无法复用已完成的分析结果", file=sys.stderr)
        return 2
    work = _same_drive_temp("tmp_dc-verify-data")
    for suffix in ("", "-wal", "-shm"):
        f = src_db.with_name(src_db.name + suffix)
        if f.is_file():
            shutil.copy2(f, work / ("data.db" + suffix))
    # 模型目录必须是 <data_dir>/models —— _generate_one 就是这么拼路径的。
    # 用目录联接（mklink /J）而非符号链接：后者在 Windows 需要管理员特权。
    models_dir = (REPO / "data" / "models").resolve()
    link = work / "models"
    made_link = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(models_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    ).returncode == 0
    if not made_link and not link.exists():
        print(f"无法建立模型联接，TTS 会静默全批失败：{models_dir} -> {link}", file=sys.stderr)
        return 2

    media = Path(args.media)
    if not media.is_dir():
        print(f"素材目录不存在：{media}", file=sys.stderr)
        return 2

    ctx, executor = build_context(work, link)
    # 预检：先确认 TTS 真能出声，否则后面所有"零旁白"都可能是脚手架问题而不是产品缺陷
    try:
        probe_engine = create_tts(ctx.settings.get("tts.engine", "edge"), link)
        sample = probe_engine.synthesize(
            "预检", "zf_001", work / "preflight.mp3"
        )
        if not sample.is_file() or sample.stat().st_size == 0:
            print("预检失败：TTS 未产出音频，环境未就绪", file=sys.stderr)
            return 2
    except Exception as exc:  # noqa: BLE001 - 预检就是要吞下一切环境问题
        print(f"预检失败：TTS 不可用（{type(exc).__name__}: {exc}），环境未就绪", file=sys.stderr)
        return 2
    print(f"预检通过：TTS={ctx.settings.get('tts.engine', 'edge')} 可出声")
    # 预检 LLM（与上面 TTS 预检同构，同为"环境未就绪"= 退出码 2）。
    # P-1.5 之后解说文案只有 LLM 一条路：copywriter 未配置就抛，不再有模板兜底。
    # 少了这道预检，"七个解说模式全红"会被读成产品崩了，而真实原因可能只是没配模型——
    # 那是运维要修的环境问题，不是研发要查的回归。
    llm_config = LlmConfig.from_settings(ctx.settings)
    if not llm_config.configured:
        print("预检失败：LLM 未配置（llm.base_url/llm.model）——"
              "P-1.5 后解说文案不降级，七个解说模式必然全红，先在「引擎」页配置文本模型",
              file=sys.stderr)
        return 2
    try:
        took = LlmClient(llm_config, timeout_s=30.0).ping()
    except Exception as exc:  # noqa: BLE001 - 预检就是要吞下一切环境问题
        print(f"预检失败：LLM 不可达（{type(exc).__name__}: {exc}），环境未就绪",
              file=sys.stderr)
        return 2
    print(f"预检通过：LLM={llm_config.model} 往返 {took:.2f}s")
    # 挂上 Phase C 的告警计数（只报数不断言，理由见 LOUDNESS_WARNS 的定义处）。
    # 渲染跑在本进程的 executor 线程里，模块 logger 是同一个，挂一次即可覆盖全部模式。
    logging.getLogger(_LOUDNESS_LOGGER).addHandler(LOUDNESS_WARNS)
    project = ctx.conn.execute("select id from projects limit 1").fetchone()
    if project is None:
        print("库里没有项目", file=sys.stderr)
        return 2
    project_id = str(project[0])
    done = ctx.conn.execute(
        "select count(*) from episodes where status='done'"
    ).fetchone()[0]
    print(f"项目 {project_id[:8]} · 已分析 {done} 集 · 素材 {media.name} · 隔离副本 {work.name}")
    # 响度规格读设置（与 Phase C 同一个访问器，两边不可能各漂各的），一次解析全程复用。
    loudness_target = loudness.LoudnessTarget.from_settings(ctx.settings)
    print(f"响度规格：目标 {loudness_target.integrated_lufs:.1f} LUFS"
          f" ± {LOUDNESS_TOLERANCE_LU} LU · 真峰门限 "
          f"{loudness_target.true_peak_dbtp + loudness._TP_GATE_MARGIN_DB:.2f} dBTP"
          f"（目标 {loudness_target.true_peak_dbtp:.1f} + "
          f"{loudness._TP_GATE_MARGIN_DB} dB 余量，取自设置页）")
    print(f"待跑模式：{', '.join(modes)}\n")

    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    for mode in modes:
        CAPTURED.clear()
        warns_before = LOUDNESS_WARNS.count
        router = Router()
        narration_api.register(router, ctx)
        export_api.register(router, ctx)
        started = time.time()
        resp = router.dispatch(RpcRequest(id=mode, method="narration.plan_variants",
                                          params={"project_id": project_id, "modes": [mode], "k": 1}))
        if resp.error is not None:
            failures.append(f"{mode}: RPC 失败 {resp.error.message}")
            rows.append({"mode": mode, "status": "rpc-error", "error": resp.error.message})
            continue
        plan_job = wait_job(ctx.job_store, str(resp.result["job_id"]), args.job_timeout)
        if plan_job["status"] != "completed":
            failures.append(f"{mode}: 规划失败（{plan_job['status']} · {plan_job.get('error')}）")
            rows.append({"mode": mode, "status": "plan-error", "error": plan_job.get("error")})
            continue
        plan_row = ctx.conn.execute(
            "SELECT id FROM narration_plans WHERE project_id = ? AND narration_mode = ?"
            " ORDER BY created_at DESC LIMIT 1", (project_id, mode)
        ).fetchone()
        resp = router.dispatch(RpcRequest(id=mode, method="export.submit",
                                          params={"plan_ids": [plan_row[0]]}))
        if resp.error is not None:
            failures.append(f"{mode}: submit 失败 {resp.error.message}")
            rows.append({"mode": mode, "status": "submit-error", "error": resp.error.message})
            continue
        job = wait_job(ctx.job_store, str(resp.result["exports"][0]["job_id"]), args.job_timeout)
        rec: dict[str, Any] = {"mode": mode, "status": job["status"],
                               "elapsed_s": round(time.time() - started, 1),
                               "loudness_retry_hints": LOUDNESS_WARNS.count - warns_before}
        if job["status"] != "completed":
            rec["error"] = job.get("error")
            failures.append(f"{mode}: 任务未完成（{job['status']} · {job.get('error')}）")
            # Phase C 现在会**硬失败**整条导出（LoudnessError）：打不到响度规格的片子不许交付。
            # 这是设计意图，不是门禁要绕开的麻烦——点出来是为了防止下一个人
            # 拿"放宽容差"当修法（放宽只是把超规格的片子放出去）。
            if any(word in str(job.get("error") or "")
                   for word in ("响度", "真峰值", "没有音轨")):
                failures.append(f"{mode}: ↑ 疑似 Phase C 响度硬失败——这是真发现，"
                                "查上游混音/素材热度，不要靠放宽门禁容差绕过")
            rows.append(rec)
            continue

        row = ctx.conn.execute(
            "select output_path, narration_plan_id, narration_mode from export_jobs"
            " where status='completed' order by created_at desc limit 1").fetchone()
        if row is None or not row[0]:
            failures.append(f"{mode}: 没有成品记录")
            rows.append(rec)
            continue
        # 这条查询取的是"最新一条已完成出片记录"，不带模式条件。对不上就说明量到的
        # 是别的模式的片子——那么本行所有实测（含响度与 planner）都在描述错误的对象，
        # 必须当场红，不能拿它下结论。
        if str(row[2]) != mode:
            failures.append(f"{mode}: 取到的成品记录属于 {row[2]}——本行结果不可信，"
                            "先修门禁的成品定位再下结论")
            rows.append(rec)
            continue
        clip = Path(str(row[0]))
        plan_row = ctx.conn.execute("select plan_data from narration_plans where id=?",
                                    (row[1],)).fetchone()
        plan = json.loads(str(plan_row[0])) if plan_row else {}
        timeline = plan.get("timeline", [])
        texts = plan.get("narration_texts", [])
        roles: dict[str, int] = {}
        for seg in timeline:
            role = str(seg.get("audio", "?"))
            roles[role] = roles.get(role, 0) + 1
        tts_ok = sum(1 for t in texts
                     if t.get("audio_path") and Path(str(t["audio_path"])).is_file()
                     and Path(str(t["audio_path"])).stat().st_size > 0)
        # 跨集度只在这一处定义：时间轴上的不重复集数。业主对这条的定案是"不做强制守卫"
        # （不拿它判红），所以默认走记录——但记录也得有个唯一来源，否则"看起来跨集了"这种
        # 印象会被当成事实。真机实测（2026-09-19）：full_narration 8 段跨 2 集、
        # intro_narration 60 段跨 2 集、ultra_short_hook 3 段只用 1 集——开关管的就是最后那种。
        episodes_used = len({str(s.get("episode_id")) for s in timeline
                             if s.get("episode_id")})
        # 量一次取两值：ebur128 每跑一遍就要把整片音频解码一次。
        integrated, true_peak = ebur128(clip)
        rec.update({
            "clip": clip.name, "size_mb": round(clip.stat().st_size / 1e6, 1),
            "duration_s": round(probe_duration_s(clip), 2),
            "has_audio": has_audio_stream(clip),
            "mean_volume_db": mean_volume_db(clip),
            "integrated_lufs": integrated,
            "true_peak_dbtp": true_peak,
            "max_freeze_s": round(max_freeze_s(clip), 2),
            "planner": plan.get("planner"),
            "segments": len(timeline),
            "episodes_used": episodes_used,
            "audio_roles": roles,
            "narration_texts": len(texts),
            "tts_files_ok": tts_ok,
            "segments_captured": len(CAPTURED),
            "segments_with_tts": sum(1 for c in CAPTURED if c["has_tts_input"]),
            "segments_mixed": sum(1 for c in CAPTURED if c["mixed"]),
            "tts_files_missing": sum(1 for c in CAPTURED
                                      if c["tts_path"] and not Path(c["tts_path"]).is_file()),
            "tts_files_empty": sum(1 for c in CAPTURED
                                   if c["tts_path"] and Path(c["tts_path"]).is_file()
                                   and Path(c["tts_path"]).stat().st_size == 0),
        })

        # 断言
        # 插桩自身要先可信：抓到 0 段时，下面所有"该有旁白"的断言都会空转通过
        if rec["segments_captured"] != rec["segments"]:
            failures.append(f"{mode}: 插桩只覆盖 {rec['segments_captured']}/{rec['segments']} 段"
                            "——本行结果不可信，先修门禁再下结论")
        if not rec["has_audio"]:
            failures.append(f"{mode}: 成片无音轨")
        # 文案来源：P-1.5 之后解说模式必须是 LLM 成稿，"rule" 说明它还在走模板
        # 或编剧链根本没接上（copywriter 无兜底，接上了就不会退回 rule）。
        expected_planner = EXPECT_PLANNER.get(mode, "rule")
        if rec["planner"] != expected_planner:
            failures.append(f"{mode}: 文案来源 planner={rec['planner']}，预期 {expected_planner}"
                            "（说明该模式仍在走模板或剧本链没接上）")
        # 响度窗口：Phase C 收口的是整片 R128 integrated，量的是**最终成片**（靠真峰重试
        # 过门的片子照样合格——那是合法路径，不该要求首遍必过）。
        # 目标值读设置而不是写死 −14：这个数进设置页就是为了让用户能改，门禁跟着改。
        got_lufs = rec["integrated_lufs"]
        if got_lufs is None:
            # 没测出来必须响：一条"读得到 None 也算过"的断言就是本门禁历史上那次假绿的形状。
            failures.append(f"{mode}: ebur128 未测出 integrated 响度（门禁本身不可信，先修测量）")
        elif abs(got_lufs - loudness_target.integrated_lufs) > LOUDNESS_TOLERANCE_LU:
            failures.append(
                f"{mode}: 响度 {got_lufs:.1f} LUFS 偏离目标 "
                f"{loudness_target.integrated_lufs:.1f} 超过 {LOUDNESS_TOLERANCE_LU} LU"
            )
        # 真峰值门限与 Phase C 的复核门限同构（目标 + 同一个余量常量，直接从生产模块读，
        # 两边不可能各漂各的）。九部真成片实测 −3.77…−2.17 dBTP 对门限 −1.0，余量 ≥ 1.17 dB；
        # 同一部片子 ebur128 的真峰比 loudnorm 自报低 0.01 dB，量法差不会把绿片判红。
        # 不设"Phase C 之前"的真峰断言：original-only 段带着源素材自身的热度
        # （仓里 raw_clip 实测整片 +2.98 dBTP），限幅器有意不碰它，由 Phase C 的门限与重试负责。
        got_peak = rec["true_peak_dbtp"]
        peak_gate = loudness_target.true_peak_dbtp + loudness._TP_GATE_MARGIN_DB
        if got_peak is None:
            failures.append(f"{mode}: ebur128 未测出真峰值（门禁本身不可信，先修测量）")
        elif got_peak > peak_gate:
            failures.append(
                f"{mode}: 真峰值 {got_peak:.2f} dBTP 超门限 {peak_gate:.2f}"
                f"（目标 {loudness_target.true_peak_dbtp:.1f} dBTP + "
                f"{loudness._TP_GATE_MARGIN_DB} dB 余量）——削顶是听得见的失真，不许交付"
            )
        # mean_volume 保留：它防的是"整条音轨没声"（静音片实测 −70.0 LUFS 也够响度窗口判红，
        # 但两条判据量的是不同东西，多一层保险不亏）。
        if rec["mean_volume_db"] is None or rec["mean_volume_db"] < MIN_MEAN_VOLUME_DB:
            failures.append(f"{mode}: 近乎静音（mean_volume={rec['mean_volume_db']} dB）")
        if rec["duration_s"] <= 0:
            failures.append(f"{mode}: 成片时长为 0")
        if rec["duration_s"] > float(ctx.settings.get("strategy.max_duration_s", "300")):
            failures.append(f"{mode}: 时长 {rec['duration_s']}s 超上限")
        # 不在此 enforce 最小时长：超短悬念版本就该十几秒、金句流随句数浮动，
        # 每模式的目标区间是产品参数（生产线默认值），门禁不该发明它。
        if rec["max_freeze_s"] >= MAX_FREEZE_S:
            failures.append(f"{mode}: 存在 {rec['max_freeze_s']}s 冻结画面")
        wants_tts = sum(1 for c in CAPTURED if c["audio"] in ("narration", "ducked"))
        expected = EXPECT_NARRATION.get(mode, "many")
        if expected == "none":
            if wants_tts or rec["segments_mixed"]:
                failures.append(f"{mode}: 该模式设计上无旁白，却混入 {wants_tts} 段")
        else:
            planned = sum(v for k, v in roles.items() if k in ("narration", "ducked"))
            floor = 1 if expected == "one" else 2
            if planned < floor:
                failures.append(
                    f"{mode}: 预期至少 {floor} 段旁白，编排里只有 {planned} 段（角色={roles}）"
                )
            elif rec["segments_with_tts"] == 0:
                failures.append(
                    f"{mode}: 应有 {planned} 段旁白，实际混入 0 段 —— "
                    f"TTS 产出 {rec['tts_files_ok']}/{rec['narration_texts']} 个可用音频文件"
                    + ("（TTS 未出声，属环境问题）" if rec["tts_files_ok"] == 0
                       else "（TTS 出了音频却没接到段上，属管道断链）"))
            elif rec["segments_with_tts"] != wants_tts:
                failures.append(f"{mode}: {wants_tts} 段该有旁白，实际 {rec['segments_with_tts']} 段拿到")
        if rec["tts_files_missing"] or rec["tts_files_empty"]:
            failures.append(f"{mode}: 旁白音频文件缺失/为空 "
                            f"(missing={rec['tts_files_missing']}, empty={rec['tts_files_empty']})")
        if args.require_cross_episode and rec["episodes_used"] < 2:
            failures.append(
                f"{mode}: 只用了 {rec['episodes_used']} 集素材，--require-cross-episode "
                "要求成片真的跨集（默认不加这个开关，见上方注释）"
            )
        duck_failures, duck_rec = _check_ducking(mode, CAPTURED)
        failures.extend(duck_failures)
        rec.update(duck_rec)
        rows.append(rec)

    executor.shutdown(wait=True, cancel_futures=True)

    # 列宽只在这一处定义，表头与数据行都从它取值——两边各写一份就迟早对不上。
    columns: list[tuple[str, int, str]] = [
        ("模式", 18, "<"), ("状态", 11, "<"), ("时长s", 8, ">"), ("均量dB", 9, ">"),
        ("LUFS", 8, ">"), ("峰dB", 8, ">"), ("冻结s", 7, ">"), ("来源", 11, ">"),
        ("段", 4, ">"), ("插桩", 5, ">"), ("TTS", 5, ">"), ("带旁白", 7, ">"),
        ("已混音", 7, ">"), ("压底残差", 9, ">"), ("跨集", 6, ">"), ("耗时s", 7, ">"),
    ]
    print("".join(_pad(title, width, align) for title, width, align in columns))
    print("-" * sum(width for _, width, _ in columns))
    for r in rows:
        values = [
            str(r["mode"]), str(r["status"]),
            f"{r.get('duration_s', 0)}",
            _fmt(r.get("mean_volume_db")),
            _fmt(r.get("integrated_lufs")),
            _fmt(r.get("true_peak_dbtp"), 2),
            f"{r.get('max_freeze_s', 0)}",
            str(r.get("planner", "-")),
            f"{r.get('segments', 0)}", f"{r.get('segments_captured', 0)}",
            f"{r.get('tts_files_ok', 0)}", f"{r.get('segments_with_tts', 0)}",
            f"{r.get('segments_mixed', 0)}",
            _fmt(r.get("duck_max_residual_db"), 2),
            f"{r.get('episodes_used', 0)}",
            f"{r.get('elapsed_s', 0)}",
        ]
        print("".join(
            _pad(value, width, align)
            for value, (_, width, align) in zip(values, columns, strict=True)
        ))
        if r.get("audio_roles"):
            print(f"{'':<29}音频角色：{r['audio_roles']}")
        # 重试留痕只报数不断言：靠重试过门的片子照样合格（门禁量的是最终成片），
        # 但限幅器落地后新渲染的片子它应当近乎为零，频繁出现说明上游混音又坏了。
        if r.get("loudness_retry_hints"):
            print(f"{'':<29}Phase C 真峰重试留痕：{r['loudness_retry_hints']} 条（信息，不是失败）")

    (out_dir / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
    print(f"\n明细：{out_dir / 'summary.json'}")
    if failures:
        print("\n失败：")
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print("\n全部断言通过。")
    return 0


if __name__ == "__main__":
    # 必须重定向到文件也能跑：Windows 上重定向后的 stdout 用 ANSI 代码页（本机实测 gbk），
    # 打印失败清单里那个 "✗" 会直接 UnicodeEncodeError——退出码是 1，但那是**崩溃**的 1，
    # 不是"断言失败"的 1，而且运维最想看的失败那一行根本没进日志。
    # 下面这行 setdefault 救不了本进程（解释器启动时编码就定了），只影响子进程；
    # 真正的修法是进程内 reconfigure。
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            # line_buffering：九模式跑 15-25 分钟，重定向到文件时默认是块缓冲，
            # 运维盯着日志会一直看不到进度，直到进程退出才一次性倒出来。
            _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.exit(main())

"""模型多源下载：ModelScope / HF 镜像 / HF 官方，所选源优先 + 国内优先降级。

落盘形态纪律（whisper 系）：**下载产物必须就是体检认可的合规资产**——下载前解析
默认分支提交号（HF 系 API），落 ``snapshots/<提交号>/``，全部文件落齐后补写
``refs/main`` 与 ``trees/<提交号>.json``；解析不到提交号才退化 ``snapshots/main``
（体检如实报「无从对账」，warn 不 fail）。存量走 :func:`relayout_whisper_cache`
就地迁移，零重新下载。

``trees/<提交号>.json`` 是 huggingface_hub 的**保留地**（``_tree_cache.py``，官方
形状 ``{"format_version": 1, "files": {...}}``）：faster_whisper 加载模型经
``snapshot_download`` 会解析它，写自家形状会把 hf_hub 崩在
``data.get("format_version")``（AttributeError 不在其捕获表里——2026-09-24
data-scale 实测：应用内下载的 Whisper 文件层体检通过、引擎加载必炸）。
本模块只写 hf 兼容形状，判据见 :func:`_write_hf_metadata`。
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager import fetch, registry
from dramaclip.infra.model_manager.fetch import DownloadCancelled
from dramaclip.infra.model_manager.registry import ModelSpec, builtin_specs
from dramaclip.transport.notify import Notifier

Endpoints = dict[str, str]

#: 仓库文件清单条目：(相对路径, 大小字节, 内容 SHA256 或 None, git blob SHA1 或空串)。
#: sha256 来源：HF 的 ``lfs.oid``、ModelScope 的 ``Sha256``；小文件 API 不给就是 None，
#: 此时完整性只由字节数兜底——够不够诚实由体检的 manifest 判据说，不在这里假装。
#: blob_id 来源：HF tree API 的 ``oid``（git blob SHA1）——trees 清单是 hf_hub 保留地，
#: 官方条目 ``size``+``blob_id`` 必填；ModelScope 没有这个概念，恒为空串（whisper 系
#: 只挂 HF 源，写 trees 时 blob_id 总是取得到）。
FileEntry = tuple[str, int, str | None, str]

_HEX = "0123456789abcdef"

# 国内优先的规范源序（所选源排第一由 source_chain 负责）
SOURCE_ORDER: tuple[str, ...] = ("modelscope", "hf_mirror", "huggingface")
_SKIP_RE = re.compile(
    r"\.(wav|mp3|flac|m4a|aac|ogg|jpg|jpeg|png|gif|webp|mp4|avi|mkv|zip|gz|xz|7z|md|pdf)$",
    re.I,
)


def spec_by_id(model_id: str) -> ModelSpec | None:
    return next((spec for spec in builtin_specs() if spec.model_id == model_id), None)


def source_chain(selected: str, spec: ModelSpec) -> list[tuple[str, str]]:
    """下载源序列：所选源排第一，其余按国内优先补齐。"""
    repos = dict(spec.sources())
    chain = [kind for kind in SOURCE_ORDER if kind in repos]
    if selected in chain:
        chain.remove(selected)
        chain.insert(0, selected)
    return [(kind, repos[kind]) for kind in chain]


def web_url(kind: str, repo: str, endpoints: Endpoints) -> str:
    """源的仓库主页（复制链接用）。"""
    if kind == "modelscope":
        return f"{endpoints['modelscope'].rstrip('/')}/models/{repo}"
    host = endpoints["hf_mirror"] if kind == "hf_mirror" else endpoints["huggingface"]
    return f"{host.rstrip('/')}/{repo}"


def download_in_background(
    spec: ModelSpec,
    models_dir: Path,
    notifier: Notifier,
    cancel: threading.Event,
    on_done: threading.Event,
    *,
    endpoints: Endpoints,
    source: str = "auto",
    on_result: Callable[[str, str], None] | None = None,
) -> threading.Thread:
    """后台线程逐文件下载；所选源失败自动降级其余源（国内优先）。

    ``on_result(status, message)``：在 ``on_done`` 置位**之前**回报结局
    （done / failed / cancelled，failed 附分类后的原因）——作业收尾据此走
    mark_failed/mark_cancelled，而不是把失败也收成了 completed。
    """

    def _work() -> None:
        try:
            _run_chain(spec, models_dir, notifier, cancel, endpoints, source)
            notifier.model_download(spec.model_id, 100.0, status="done")
            if on_result is not None:
                on_result("done", "")
        except DownloadCancelled:
            notifier.log("warn", f"{spec.name} 下载已取消")
            if on_result is not None:
                on_result("cancelled", "已取消")
        except Exception as exc:
            reason = classify_failure(exc)
            notifier.model_download(spec.model_id, 0.0, status="failed", message=reason)
            notifier.log(
                "warn",
                f"{spec.name} 下载失败：{reason}。也可手动下载后放入 "
                f"{models_dir / spec.placement} 并点击「重新检测」导入（原始错误：{exc}）",
            )
            if on_result is not None:
                on_result("failed", reason)
        finally:
            on_done.set()

    thread = threading.Thread(target=_work, name=f"dl-{spec.model_id}", daemon=True)
    thread.start()
    return thread


def classify_failure(exc: Exception) -> str:
    """异常 → 业主看得懂、做得动的一句话（§10.5：现象 + 动作，不说正确的废话）。

    分类只按**可证的信号**（errno、校验文案、超时/连接类异常），猜不出类别就
    原样带出异常名与原文——错误的归因比不归因更坏。
    """
    if isinstance(exc, DownloadCancelled):
        return "已取消"
    text = str(exc)
    lowered = text.lower()
    errno = getattr(exc, "errno", None)
    if errno in (28, 112) or "no space left" in lowered:
        return "磁盘空间不足——清理磁盘后重试（「环境」段可看各盘剩余空间）"
    if "大小校验失败" in text or "SHA256 校验失败" in text:
        return "下载内容校验失败（半成品已删，不会污染续传）——直接重试；反复失败请换下载源"
    if isinstance(exc, (TimeoutError, ConnectionError)) or "timed out" in lowered:
        return "网络超时或连接被断——稍后重试，或在下载气泡里换个源"
    if (
        "urlopen error" in lowered
        or "getaddrinfo" in lowered
        or "name or service not known" in lowered
    ):
        return "网络不通/域名解析失败——检查网络或代理后重试，或换个源"
    if "http error 4" in lowered:
        return "源站说没有这个文件（404/403）——仓库可能已迁移，换个源或手动下载后导入"
    if "http error 5" in lowered:
        return "源站临时故障（5xx）——稍后重试，或换个源"
    if "仓库文件清单为空" in text:
        return "仓库清单为空——源站临时故障或仓库已迁移，换个源试试"
    if "全部来源失败" in text:
        return f"所有下载源都失败了——{text.removeprefix('全部来源失败：')}"
    return f"{type(exc).__name__}: {text}"


_SIZE_LABEL_RE = re.compile(r"([\d.]+)\s*(kb|mb|gb|tb)", re.I)


def estimated_bytes(spec: ModelSpec) -> int | None:
    """从 size_label（如 "~1.5GB"）解析标称体积；解析不出返回 None（未知不瞎猜）。"""
    match = _SIZE_LABEL_RE.search(spec.size_label)
    if match is None:
        return None
    units = {"kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}
    return int(float(match.group(1)) * units[match.group(2).lower()])


class _RateMeter:
    """EMA 速率与剩余时间：有速度没 ETA 等于让用户干等（§4 进度三件套）。"""

    def __init__(self, total: int) -> None:
        self._total = total
        self._last_t = time.monotonic()
        self._last_bytes = 0
        self._speed = 0.0

    def update(self, done_bytes: int) -> tuple[float, float | None]:
        now = time.monotonic()
        elapsed = now - self._last_t
        if elapsed >= 0.4:  # 采样要够一个时间窗，否则瞬时值抖得没法看
            instant = (done_bytes - self._last_bytes) / elapsed
            self._speed = instant if self._speed <= 0 else self._speed * 0.6 + instant * 0.4
            self._last_t, self._last_bytes = now, done_bytes
        remaining = max(self._total - done_bytes, 0)
        return self._speed, (remaining / self._speed if self._speed > 0 else None)


def _fmt_speed(bps: float) -> str:
    if bps >= 1024 * 1024:
        return f"{bps / 1024 / 1024:.1f}MB/s"
    return f"{max(bps / 1024, 1):.0f}KB/s"


def _fmt_eta(seconds: float) -> str:
    total = int(round(seconds))
    if total >= 3600:
        return f"{total // 3600}小时{total % 3600 // 60:02d}分"
    if total >= 60:
        return f"{total // 60}分{total % 60:02d}秒"
    return f"{total}秒"


def _run_chain(
    spec: ModelSpec,
    models_dir: Path,
    notifier: Notifier,
    cancel: threading.Event,
    endpoints: Endpoints,
    source: str,
) -> None:
    last_error: Exception | None = None
    for kind, repo in source_chain(source, spec):
        try:
            _download_from(kind, repo, spec, models_dir, endpoints, notifier, cancel)
            notifier.log("info", f"{spec.name} 下载完成（来源：{kind}）")
            return
        except DownloadCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - 单源失败降级下一来源
            last_error = exc
            if cancel.is_set():
                raise DownloadCancelled from exc
            notifier.log("warn", f"源 {kind} 下载失败（{exc}），尝试下一来源")
    raise RuntimeError(f"全部来源失败：{last_error}")


def resolve_revision(kind: str, repo: str, endpoints: Endpoints) -> str | None:
    """解析仓库默认分支当前提交号（40 位十六进制）；解析不到返回 None。

    只有 HF 系 API 有这个形状（``GET /api/models/{repo}`` 顶层 ``sha``），而需要提交号
    落盘的 whisper 系模型恰好只挂 HF 系源；ModelScope 直接 None。失败不抛——退化路径
    （``snapshots/main`` + 体检报「无从对账」）是设计内行为，由调用方如实告知用户。
    """
    if kind == "modelscope":
        return None
    host = endpoints["hf_mirror"] if kind == "hf_mirror" else endpoints["huggingface"]
    try:
        data = fetch.fetch_json(f"{host.rstrip('/')}/api/models/{repo}")
    except Exception:  # noqa: BLE001 - 解析不到就退化，不让布局问题挡下载
        return None
    sha = data.get("sha") if isinstance(data, dict) else None
    sha = str(sha).strip().lower() if sha is not None else ""
    if len(sha) == 40 and all(c in _HEX for c in sha):
        return sha
    return None


def _download_from(
    kind: str,
    repo: str,
    spec: ModelSpec,
    models_dir: Path,
    endpoints: Endpoints,
    notifier: Notifier,
    cancel: threading.Event,
) -> None:
    revision: str | None = None
    if spec.engine == "faster_whisper":
        revision = resolve_revision(kind, repo, endpoints)
        if revision is None:
            notifier.log(
                "warn",
                f"{spec.name}：解析不到提交号，按 snapshots/main 落盘"
                "（体检将报「无从对账」，权重齐仍可用；恢复网络后可就地迁移）",
            )
    layout_rev = revision or "main"
    files = list_tree(kind, repo, endpoints)
    if not files:
        raise RuntimeError("仓库文件清单为空")
    notifier.log("info", f"开始从 {kind} 下载 {spec.name}（{len(files)} 个文件）")
    total = sum(size for _rel, size, _sha, _blob in files)
    state = {"done": 0, "base": 0, "percent": -1}
    meter = _RateMeter(total)

    def _report(position: int) -> None:
        done_bytes = state["base"] + position
        percent = done_bytes / total * 100 if total > 0 else 0
        whole = int(percent)
        if whole != state["percent"]:
            state["percent"] = whole
            extra: dict[str, Any] = {"status": "downloading"}
            speed, eta = meter.update(done_bytes)
            if speed > 0:
                extra["speed"] = _fmt_speed(speed)
            if eta is not None:
                extra["eta"] = _fmt_eta(eta)
            notifier.model_download(spec.model_id, min(percent, 99.0), **extra)

    manifest: list[dict[str, Any]] = []
    for rel, size, sha256, blob_id in files:
        dest = _dest(models_dir, spec, rel, layout_rev)
        if dest.is_file() and (size <= 0 or dest.stat().st_size == size):
            state["done"] += size
            manifest.append(
                {"path": rel, "size": dest.stat().st_size, "sha256": sha256, "blob_id": blob_id}
            )
            continue
        url = file_url(kind, repo, rel, endpoints)
        state["base"] = state["done"]
        for attempt in (1, 2):
            try:
                fetch.download_file(
                    url, dest, size, expected_sha256=sha256, cancel=cancel, on_progress=_report
                )
                break
            except DownloadCancelled:
                raise
            except Exception:
                if attempt == 2:
                    raise
                notifier.log("warn", f"{rel} 下载或校验失败（第 1 次），重试")
        state["done"] += size
        manifest.append(
            {"path": rel, "size": dest.stat().st_size, "sha256": sha256, "blob_id": blob_id}
        )
    if revision is not None:
        _write_hf_metadata(models_dir, spec, revision, manifest)


def _write_hf_metadata(
    models_dir: Path, spec: ModelSpec, revision: str, manifest: list[dict[str, Any]]
) -> None:
    """全部文件落齐后才写 refs/trees：半截下载不得拥有权威修订元数据。

    trees 形状必须是 huggingface_hub 官方的（``_tree_cache.py``：顶层
    ``{"format_version": 1, "files": {相对路径: 条目}}``，条目 ``size``+``blob_id``
    必填，LFS 文件再带 ``lfs_sha256``/``lfs_size``）——faster_whisper 加载会经
    ``snapshot_download`` 解析这个文件，自家 list 形状会让 hf_hub 崩在
    ``data.get("format_version")``（AttributeError 不在其捕获表里）。

    诚实降级：blob_id 形状不对的条目**宁缺毋滥**——hf_hub 读到缺条目只会把该文件
    当未展开重拉（KeyError 在其捕获表里，整份坏清单也只会被忽略），是安全退化
    不是崩溃；一条都凑不齐就整个不写 trees（体检报「无清单，无从对账」，不冒充）。
    """
    files: dict[str, Any] = {}
    for entry in manifest:
        blob_id = str(entry.get("blob_id") or "")
        if len(blob_id) != 40 or not all(c in _HEX for c in blob_id):
            continue
        size = int(entry.get("size") or 0)
        info: dict[str, Any] = {"size": size, "blob_id": blob_id}
        lfs_sha256 = entry.get("sha256")
        if lfs_sha256:
            info["lfs_sha256"] = lfs_sha256
            info["lfs_size"] = size
        files[str(entry["path"])] = info
    cache = models_dir / spec.placement / f"models--{spec.repo_id.replace('/', '--')}"
    refs = cache / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(revision, encoding="utf-8")
    if not files:
        return
    trees = cache / "trees"
    trees.mkdir(parents=True, exist_ok=True)
    (trees / f"{revision}.json").write_text(
        json.dumps({"format_version": 1, "files": files}, ensure_ascii=False), encoding="utf-8"
    )


def relayout_whisper_cache(
    spec: ModelSpec, models_dir: Path, endpoints: Endpoints
) -> dict[str, Any]:
    """把存量 ``snapshots/main`` 就地迁移成提交号布局：改名 + 补 refs/trees，零重新下载。

    返回 ``{"path": 迁移后快照目录, "migrated": 本次是否真动了盘}``——已是目标布局时
    幂等空操作（migrated=False），不触网。

    诚实边界：
    - 提交号必须在线解析得到——网络不通/仓库没了就如实报错，**不造假提交号**；
    - 目标快照目录已存在（本机两份修订）时不自动合并，报出来交人工裁决；
    - trees 清单的 sha256/blob_id 按本机文件现算（git blob SHA1 本机可算，不抄上游）：
      它证明「今后能逐文件对账」，不证明「当年下载没坏」——那是上游清单才有的信息，
      拿不到就不假装。
    """
    if spec.engine != "faster_whisper":
        raise ValueError(f"{spec.model_id} 不是 whisper 系缓存布局，无从迁移")
    base = models_dir / spec.placement
    cache = registry.whisper_cache(base, spec)
    if cache is None:
        raise ValueError(f"{base} 下没有 whisper 缓存目录，无从迁移（缺模型请直接下载）")
    snapshot = registry.whisper_snapshot(cache)
    if snapshot is None:
        raise ValueError(f"{cache} 没有快照目录，无从迁移（缺模型请直接下载）")
    name = snapshot.name
    refs_main = cache / "refs" / "main"
    has_trees = (cache / "trees").is_dir() and any((cache / "trees").glob("*.json"))
    if (
        len(name) == 40
        and all(c in _HEX for c in name.lower())
        and refs_main.is_file()
        and refs_main.read_text(encoding="utf-8", errors="replace").strip() == name
        and has_trees
    ):
        return {"path": str(snapshot), "migrated": False}
    revision: str | None = None
    for kind in ("hf_mirror", "huggingface"):
        revision = resolve_revision(kind, spec.repo_id, endpoints)
        if revision is not None:
            break
    if revision is None:
        raise ValueError(
            "在线解析不到提交号——无从对账迁移。恢复网络后重试；"
            "或「强制重新下载」，下载器会直接落成合规布局"
        )
    target = cache / "snapshots" / revision
    if target.exists():
        raise ValueError(f"目标快照已存在：{target}——两份修订并存，请人工裁决保留哪份")
    snapshot.rename(target)
    manifest: list[dict[str, Any]] = []
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        sha256, blob_id = fetch.sha256_and_blob_id_of(path)
        manifest.append(
            {
                "path": path.relative_to(target).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256,
                "blob_id": blob_id,
            }
        )
    _write_hf_metadata(models_dir, spec, revision, manifest)
    return {"path": str(target), "migrated": True}


def list_tree(kind: str, repo: str, endpoints: Endpoints) -> list[FileEntry]:
    """列仓库文件清单 [(相对路径, 大小字节, sha256 或 None)]（过滤隐藏/文档/媒体/归档杂项）。"""

    def _wanted(rel: str) -> bool:
        hidden = rel.startswith(".") or Path(rel).name.startswith(".")
        return not hidden and not _SKIP_RE.search(rel)

    if kind == "modelscope":
        base = endpoints["modelscope"].rstrip("/")
        api = f"{base}/api/v1/models/{repo}/repo/files?Revision=master&Recursive=true"
        data = fetch.fetch_json(api)
        files = (data.get("Data") or {}).get("Files") if isinstance(data, dict) else None
        return [
            (
                str(item["Path"]),
                int(item.get("Size") or 0),
                _sha_or_none(item.get("Sha256") or item.get("sha256")),
                "",  # ModelScope 没有 git blob 概念；whisper 系不挂 ms 源，trees 用不到
            )
            for item in (files or [])
            if item.get("Type") == "blob" and _wanted(str(item["Path"]))
        ]
    host = endpoints["hf_mirror"] if kind == "hf_mirror" else endpoints["huggingface"]
    data = fetch.fetch_json(f"{host.rstrip('/')}/api/models/{repo}/tree/main?recursive=true")
    if not isinstance(data, list):
        return []
    out: list[FileEntry] = []
    for item in data:
        if not isinstance(item, dict) or item.get("type") != "file":
            continue
        path = str(item.get("path", ""))
        if not _wanted(path):
            continue
        lfs = item.get("lfs") or {}
        size = int(lfs.get("size") or item.get("size") or 0)
        out.append((path, size, _sha_or_none(lfs.get("oid")), _blob_or_empty(item.get("oid"))))
    return out


def _sha_or_none(value: object) -> str | None:
    """API 给的哈希只认 64 位十六进制；形状不对宁缺毋滥（缺了退字节数校验）。"""
    text = str(value).strip().lower() if value is not None else ""
    if len(text) == 64 and all(c in _HEX for c in text):
        return text
    return None


def _blob_or_empty(value: object) -> str:
    """HF tree API 的 ``oid``（git blob SHA1）只认 40 位十六进制；形状不对给空串
    ——trees 清单里缺 blob_id 的条目宁可不写（hf_hub 会把该文件当未展开重拉），
    也不能塞个假身份进去。"""
    text = str(value).strip().lower() if value is not None else ""
    if len(text) == 40 and all(c in _HEX for c in text):
        return text
    return ""


def file_url(kind: str, repo: str, rel: str, endpoints: Endpoints) -> str:
    quoted = urllib.parse.quote(rel, safe="/")
    if kind == "modelscope":
        return f"{endpoints['modelscope'].rstrip('/')}/models/{repo}/resolve/master/{quoted}"
    host = endpoints["hf_mirror"] if kind == "hf_mirror" else endpoints["huggingface"]
    return f"{host.rstrip('/')}/{repo}/resolve/main/{quoted}"


def _dest(models_dir: Path, spec: ModelSpec, rel: str, revision: str) -> Path:
    """落盘路径：faster-whisper 保持 HF 缓存布局（snapshots/<提交号>），其余平铺。

    ``revision`` 由 :func:`resolve_revision` 解析；解析不到时调用方传 "main"，
    落出体检能认出的退化形态（warn「无从对账」），不再冒充提交号。
    """
    root = models_dir / spec.placement
    if spec.engine == "faster_whisper":
        cache = f"models--{spec.repo_id.replace('/', '--')}"
        return root / cache / "snapshots" / revision / rel
    return root / rel

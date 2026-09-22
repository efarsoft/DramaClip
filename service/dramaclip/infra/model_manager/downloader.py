"""模型多源下载：ModelScope / HF 镜像 / HF 官方，所选源优先 + 国内优先降级。

落盘形态纪律（whisper 系）：**下载产物必须就是体检认可的合规资产**。历史版本把快照
写死成 ``snapshots/main``、不解析提交号、不写 ``refs/``/``trees/``——自家下载器批量
制造「体检判 fail、界面禁激活」的异常缓存，修复动作永远在替下载器擦地。本模块现在：
下载前解析默认分支提交号（HF 系 API），落 ``snapshots/<提交号>/``，全部文件落齐后
补写 ``refs/main`` 与 ``trees/<提交号>.json``（逐文件 path/size/sha256 清单）；
解析不到提交号才退化 ``snapshots/main``（体检如实报「无从对账」，warn 不 fail）。
存量 ``snapshots/main`` 走 :func:`relayout_whisper_cache` 就地迁移，零重新下载。
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Any

from dramaclip.infra.model_manager import fetch, registry
from dramaclip.infra.model_manager.fetch import DownloadCancelled
from dramaclip.infra.model_manager.registry import ModelSpec, builtin_specs
from dramaclip.transport.notify import Notifier

Endpoints = dict[str, str]

#: 仓库文件清单条目：(相对路径, 大小字节, 内容 SHA256 或 None)。
#: sha256 来源：HF 的 ``lfs.oid``、ModelScope 的 ``Sha256``；小文件 API 不给就是 None，
#: 此时完整性只由字节数兜底——够不够诚实由体检的 manifest 判据说，不在这里假装。
FileEntry = tuple[str, int, str | None]

_HEX = "0123456789abcdef"

# 国内优先的规范源序；用户所选源永远排第一
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
) -> threading.Thread:
    """后台线程逐文件下载；所选源失败自动降级其余源（国内优先）。"""

    def _work() -> None:
        try:
            _run_chain(spec, models_dir, notifier, cancel, endpoints, source)
            notifier.model_download(spec.model_id, 100.0, status="done")
        except DownloadCancelled:
            notifier.log("warn", f"{spec.name} 下载已取消")
        except Exception as exc:
            notifier.model_download(spec.model_id, 0.0, status="failed")
            notifier.log(
                "warn",
                f"{spec.name} 下载失败。可手动下载后放入 {models_dir / spec.placement} "
                f"并点击「重新检测」导入（{exc}）",
            )
        finally:
            on_done.set()

    thread = threading.Thread(target=_work, name=f"dl-{spec.model_id}", daemon=True)
    thread.start()
    return thread


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
    total = sum(size for _rel, size, _sha in files)
    state = {"done": 0, "base": 0, "percent": -1}

    def _report(position: int) -> None:
        percent = (state["base"] + position) / total * 100 if total > 0 else 0
        whole = int(percent)
        if whole != state["percent"]:
            state["percent"] = whole
            notifier.model_download(spec.model_id, min(percent, 99.0), status="downloading")

    manifest: list[dict[str, Any]] = []
    for rel, size, sha256 in files:
        dest = _dest(models_dir, spec, rel, layout_rev)
        if dest.is_file() and (size <= 0 or dest.stat().st_size == size):
            state["done"] += size
            manifest.append({"path": rel, "size": dest.stat().st_size, "sha256": sha256})
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
        manifest.append({"path": rel, "size": dest.stat().st_size, "sha256": sha256})
    if revision is not None:
        _write_hf_metadata(models_dir, spec, revision, manifest)


def _write_hf_metadata(
    models_dir: Path, spec: ModelSpec, revision: str, manifest: list[dict[str, Any]]
) -> None:
    """全部文件落齐后才写 refs/trees：半截下载不得拥有权威修订元数据。"""
    cache = models_dir / spec.placement / f"models--{spec.repo_id.replace('/', '--')}"
    refs = cache / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(revision, encoding="utf-8")
    trees = cache / "trees"
    trees.mkdir(parents=True, exist_ok=True)
    (trees / f"{revision}.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
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
    - trees 清单的 sha256 按本机文件现算：它证明「今后能逐文件对账」，
      不证明「当年下载没坏」——那是上游清单才有的信息，拿不到就不假装。
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
    manifest = [
        {
            "path": path.relative_to(target).as_posix(),
            "size": path.stat().st_size,
            "sha256": fetch.sha256_of(path),
        }
        for path in sorted(target.rglob("*"))
        if path.is_file()
    ]
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
        out.append((path, size, _sha_or_none(lfs.get("oid"))))
    return out


def _sha_or_none(value: object) -> str | None:
    """API 给的哈希只认 64 位十六进制；形状不对宁缺毋滥（缺了退字节数校验）。"""
    text = str(value).strip().lower() if value is not None else ""
    if len(text) == 64 and all(c in _HEX for c in text):
        return text
    return None


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

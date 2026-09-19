"""导入向导：识别 + 体检（第 ② 步），落位（第 ③ 步）见 commit。

设计定稿见 docs/design/engines-ui-options-2026-09-19.html 的 D4 节，核心约束是
**第 ② 步不通过就不进第 ③ 步**。因此这里的每一条判据都必须是实测：文件在不在、权重
实际多大、目标盘还剩多少。识别只承认两种证据——HF 缓存目录名与引擎各自的必需文件集；
认不出来就报「未识别」，绝不猜一个模型名把业主骗过闸门。

必需文件集、权重扩展名、快照解析规则都取自 registry，不在这里抄第二份。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from dramaclip.infra.model_manager import registry
from dramaclip.infra.model_manager.registry import ModelSpec

_NOMINAL = re.compile(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB|TB)", re.IGNORECASE)
_UNITS = {"kb": 1024.0, "mb": 1024.0**2, "gb": 1024.0**3, "tb": 1024.0**4}
# 体积标签是人工写的近似值，留 10% 余量；再少就是真的少东西了。
_SIZE_TOLERANCE = 0.9
_HF_CACHE_PREFIX = "models--"


@dataclass(frozen=True)
class _Match:
    """识别结论：这个目录是哪个内置模型、模型根目录在哪一层。"""

    spec: ModelSpec
    root: Path
    cache: Path | None
    basis: str


def inspect(models_dir: Path, source: Path) -> dict[str, Any]:
    """只读地认一个目录：是什么模型、能不能进库。不搬文件，也不写任何登记。"""
    src = _validated_source(models_dir, source)
    files = _walk_files(src)
    total = _total_bytes(files)
    match = _identify(src)
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    add("目录内容", "pass" if files else "fail", f"{len(files)} 个文件 · {human_bytes(total)}")
    missing = _requirements_check(match, add)
    _cache_layout_check(match, add)
    _size_check(match, add)
    _residue_check(files, add)
    free = _free_bytes(models_dir)
    _disk_check(match, total, free, add)
    _engine_check(match, add)

    return {
        "source_path": str(src),
        "file_count": len(files),
        "total_bytes": total,
        "recognized": match is not None,
        "model_id": match.spec.model_id if match else None,
        "name": match.spec.name if match else None,
        "kind": match.spec.kind if match else None,
        "engine": match.spec.engine if match else None,
        "engine_ready": registry.engine_ready(match.spec) if match else False,
        "model_root": str(match.root) if match else None,
        "cache_path": str(match.cache) if match is not None and match.cache is not None else None,
        "basis": match.basis if match else _unrecognized_basis(src),
        "missing_files": missing,
        "target": None if match is None else _target(models_dir, match.spec, free),
        "conflict": None if match is None else _conflict(models_dir, match.spec),
        "checks": checks,
        "ok": not any(check["status"] == "fail" for check in checks),
    }


def _validated_source(models_dir: Path, source: Path) -> Path:
    target = source.expanduser()
    if not target.is_dir():
        raise ValueError(f"来源目录不存在或不是目录：{target}")
    resolved = target.resolve()
    root = models_dir.resolve()
    if root == resolved or root in resolved.parents:
        raise ValueError(f"来源在模型目录内，拒绝把自己拷给自己：{resolved}")
    return resolved


def _requirements_check(match: _Match | None, add: Any) -> list[str]:
    if match is None:
        add("必需文件", "fail", "未识别出模型，无法按引擎清单核对")
        return []
    required = registry.requirements(match.spec.engine)
    missing = registry.missing_requirements(match.root, required)
    if missing:
        add("必需文件", "fail", f"缺 {len(missing)} 项：{', '.join(missing)}")
    else:
        add("必需文件", "pass", f"{len(required)} 项齐全")
    return missing


def _cache_layout_check(match: _Match | None, add: Any) -> None:
    """faster-whisper 按 HF 缓存寻址：平铺目录引擎读不到，缺 refs/main 随时会少文件。"""
    if match is None or match.spec.engine != "faster_whisper":
        return
    if match.cache is None:
        add("缓存布局", "fail", "平铺目录不是 HF 缓存：请导入 models--<org>--<模型名> 整份缓存目录")
        return
    snapshot = registry.whisper_snapshot(match.cache)
    if snapshot is None:
        add("缓存布局", "fail", f"{match.cache.name} 下没有 snapshots/<提交号> 目录")
        return
    ref = match.cache / "refs" / "main"
    content = ref.read_text(encoding="utf-8").strip() if ref.is_file() else ""
    if content != snapshot.name:
        add("缓存布局", "fail", f"refs/main={content!r} 与快照 {snapshot.name[:12]} 不一致")
    else:
        add("缓存布局", "pass", f"snapshots/{snapshot.name[:12]}")


def _size_check(match: _Match | None, add: Any) -> None:
    if match is None:
        add("权重尺寸对账", "skip", "未识别出模型，没有可比对的标称体积")
        return
    weights = registry.weight_files(match.root)
    if not weights:
        add("权重尺寸对账", "fail", "目录里没有任何权重文件")
        return
    largest = max(weights, key=lambda path: path.stat().st_size)
    measured = largest.stat().st_size
    nominal = _nominal_bytes(match.spec.size_label)
    if nominal is None:
        add("权重尺寸对账", "pass", f"{largest.name} {human_bytes(measured)}（清单未标称体积）")
        return
    ratio = measured / nominal
    detail = f"{largest.name} {human_bytes(measured)}，标称 {match.spec.size_label}"
    add("权重尺寸对账", "pass" if ratio >= _SIZE_TOLERANCE else "fail", detail)


def _residue_check(files: list[Path], add: Any) -> None:
    leftovers = [path for path in files if path.suffix == ".incomplete"]
    if leftovers:
        lost = _total_bytes(leftovers)
        add("中断残留", "fail", f"{len(leftovers)} 个 .incomplete 半截文件（{human_bytes(lost)}）")
    else:
        add("中断残留", "pass", "无 .incomplete 残留")


def _disk_check(match: _Match | None, needed: int, free: int, add: Any) -> None:
    if match is None:
        add("磁盘可容纳", "skip", "未识别的资产只做登记，不占库内空间")
        return
    if free < needed:
        add("磁盘可容纳", "fail", f"需 {human_bytes(needed)}，目标盘仅余 {human_bytes(free)}")
    else:
        add("磁盘可容纳", "pass", f"需 {human_bytes(needed)}，目标盘余 {human_bytes(free)}")


def _engine_check(match: _Match | None, add: Any) -> None:
    if match is None:
        add("引擎接入", "skip", "未识别的资产只能作为外部资产留在库里，不参与生效")
        return
    if registry.engine_ready(match.spec):
        add("引擎接入", "pass", f"{match.spec.engine} 已接入工厂")
    else:
        add("引擎接入", "warn", f"{match.spec.engine} 尚未接入，只能作为储备资产")


def _target(models_dir: Path, spec: ModelSpec, free: int) -> dict[str, Any]:
    return {
        "placement": spec.placement,
        "path": str(models_dir / spec.placement),
        "free_bytes": free,
    }


def _conflict(models_dir: Path, spec: ModelSpec) -> dict[str, Any] | None:
    """库里已有同一件资产：业主必须知道「覆盖会动到哪一份、它现在完不完整」。"""
    status = registry.detect_status(models_dir, spec)
    if status["status"] != "installed" or status["path"] is None:
        return None
    existing = Path(status["path"])
    report = registry.verify(models_dir, spec)
    return {
        "model_id": spec.model_id,
        "path": str(existing),
        "size_bytes": _total_bytes(_walk_files(existing)),
        "ok": report["ok"],
        "failed_checks": [
            check["name"] for check in report["checks"] if check["status"] == "fail"
        ],
    }


def _identify(source: Path) -> _Match | None:
    cache = _cache_root(source)
    if cache is not None:
        spec = _spec_by_repo(_repo_of_cache(cache.name))
        if spec is not None:
            snapshot = registry.whisper_snapshot(cache)
            shown = snapshot.name[:12] if snapshot is not None else "未解析"
            return _Match(
                spec,
                snapshot if snapshot is not None else cache,
                cache,
                f"依据：HF 缓存目录名 {cache.name} → 仓库 {spec.repo_id} · 快照 {shown}",
            )
    hits = _signature_matches(source)
    if hits:
        preferred = _best_name_matches(source, [hit.spec for hit in hits])
        chosen = [hit for hit in hits if hit.spec in preferred]
        return chosen[0] if len(chosen) == 1 else None
    named = _best_name_matches(source, registry.builtin_specs())
    return _by_directory_name(source, named[0]) if len(named) == 1 else None


def _by_directory_name(source: Path, spec: ModelSpec) -> _Match:
    """半截目录常常文件不齐：这时目录名是唯一的线索，缺项交给体检逐项说。"""
    root = next(
        (
            candidate
            for candidate in _candidate_roots(source)
            if candidate != source.parent and registry.weight_files(candidate)
        ),
        source,
    )
    return _Match(spec, root, None, f"依据：目录名命中内置模型 {spec.model_id}（必需文件逐项核对）")


def _best_name_matches(source: Path, specs: list[ModelSpec]) -> list[ModelSpec]:
    """目录名命中多个内置模型时，只认最具体那一个。

    为什么不能「命中即算」：四个 whisper 档位的 placement 尾巴都是 ``faster-whisper``，
    按子串匹配会把 ``faster-whisper-medium`` 同时认成 base/small/large-v3。
    """
    haystack = _haystack(source)
    scored = [(spec, _best_needle_score(spec, haystack)) for spec in specs]
    top = max((score for _spec, score in scored), default=0)
    return [spec for spec, score in scored if score == top and score > 0]


def _best_needle_score(spec: ModelSpec, haystack: str) -> int:
    tokens = (spec.model_id, spec.repo_id.rsplit("/", 1)[-1], spec.placement.rsplit("/", 1)[-1])
    lengths = [len(norm) for token in tokens if (norm := _norm(token)) and norm in haystack]
    return max(lengths, default=0)


def _haystack(source: Path) -> str:
    return _norm(" ".join([source.name, *[path.name for path in _subdirs(source)]]))


def _norm(token: str) -> str:
    return token.lower().replace("_", "-").replace("/", "-").strip()


def _signature_matches(source: Path) -> list[_Match]:
    hits: list[_Match] = []
    for root in _candidate_roots(source):
        for spec in registry.builtin_specs():
            required = registry.requirements(spec.engine)
            if required and not registry.missing_requirements(root, required):
                basis = _signature_basis(source, root, spec, required)
                hits.append(_Match(spec, root, None, basis))
    return hits


def _signature_basis(source: Path, root: Path, spec: ModelSpec, required: tuple[str, ...]) -> str:
    where = "." if root == source else root.name
    tail = f" · 目录名命中 {spec.model_id}" if _best_name_matches(source, [spec]) else ""
    return f"依据：{where}/ 内必需文件齐全（{len(required)} 项）{tail}"


def _unrecognized_basis(source: Path) -> str:
    hits = _signature_matches(source)
    if not hits:
        return "未匹配到任何内置模型：目录里没有一项内置清单的必需文件组合"
    names = ", ".join(dict.fromkeys(hit.spec.model_id for hit in hits))
    return f"未匹配到唯一的内置模型：文件特征同时命中 {names}，请改判或选能力登记为外部资产"


def _cache_root(source: Path) -> Path | None:
    if source.name.startswith(_HF_CACHE_PREFIX):
        return source
    children = [path for path in _subdirs(source) if path.name.startswith(_HF_CACHE_PREFIX)]
    return children[0] if len(children) == 1 else None


def _candidate_roots(source: Path) -> list[Path]:
    """模型可能在业主点的那一层、里面一层，或解压目录的外面一层。"""
    roots = [source.parent, source, *_subdirs(source)]
    return [root for root in roots if root.is_dir()]


def _repo_of_cache(name: str) -> str:
    """``models--Systran--faster-whisper-medium`` → ``Systran/faster-whisper-medium``。"""
    return name.removeprefix(_HF_CACHE_PREFIX).replace("--", "/", 1)


def _spec_by_repo(repo: str) -> ModelSpec | None:
    return next((spec for spec in registry.builtin_specs() if spec.repo_id == repo), None)


def _subdirs(source: Path) -> list[Path]:
    try:
        return sorted(path for path in source.iterdir() if _is_dir(path))
    except OSError:
        return []


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _walk_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in root.rglob("*"):
        try:
            if path.is_file():
                out.append(path)
        except OSError:
            continue
    return out


def _total_bytes(paths: list[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            continue
    return total


def _free_bytes(models_dir: Path) -> int:
    """目标盘余量：库目录可能还不存在，向上找到存在的祖先再问系统。"""
    probe = models_dir
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    return int(shutil.disk_usage(probe).free)


def _nominal_bytes(label: str) -> int | None:
    match = _NOMINAL.search(label)
    if match is None:
        return None
    return int(float(match.group(1)) * _UNITS[match.group(2).lower()])


def human_bytes(nbytes: float) -> str:
    size = float(nbytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


# --------------------------------------------------------------------------- 落位（第 ③ 步）

_MODES = ("copy", "move", "register")
_KINDS = ("asr", "tts")
_MANIFEST = "imported.json"
Progress = Callable[[int, int], None]


def commit(
    models_dir: Path,
    source: Path,
    *,
    mode: str,
    on_conflict: str = "",
    allow_incomplete: bool = False,
    external_kind: str = "",
    label: str = "",
    on_progress: Progress | None = None,
) -> dict[str, Any]:
    """把一个目录落进资产库：复制 / 移动 / 仅登记，冲突时按业主给的裁决办。

    两条铁律：第 ② 步不通过就不落位（业主显式 ``allow_incomplete`` 除外，且回来的报告
    仍然写着不通过）；任何情况下都不动业主原来的字节——覆盖先改名留后路，移动只在落位
    体检通过之后才清源，未识别的目录不允许猜 placement。
    """
    if mode not in _MODES:
        raise ValueError(f"未知的落位方式 mode={mode!r}，只支持 {' / '.join(_MODES)}")
    src = _validated_source(models_dir, source)
    report = inspect(models_dir, src)
    if not report["recognized"]:
        return _commit_external(models_dir, src, mode, external_kind, label, report)
    spec = _spec_by_id(str(report["model_id"]))
    if spec is None:  # recognized 为真时必然命中内置清单，这里只兜类型
        raise ValueError(f"识别结果对不上内置清单: {report['model_id']}")
    if mode == "register":
        return _record(models_dir, spec, src, src, mode, "", report, not report["ok"], label=label)
    if not report["ok"] and not allow_incomplete:
        failed = "、".join(item["name"] for item in report["checks"] if item["status"] == "fail")
        raise ValueError(f"体检未通过，不能落位（{failed}）")
    cache = Path(report["cache_path"]) if report["cache_path"] is not None else None
    unit = cache if cache is not None else Path(str(report["model_root"]))
    placement = models_dir / spec.placement
    landed = placement / unit.name if cache is not None else placement
    action = _settle_conflict(
        models_dir, spec, unit, placement, cache is not None, on_conflict, report, label
    )
    if isinstance(action, dict):
        return action
    moved = (
        _copy_tree(
            unit, placement, contents=cache is None, skip_existing=True, on_progress=on_progress
        )
        if action == "merge"
        else _land(unit, placement, cache is None, on_progress)
    )
    post = registry.verify(models_dir, spec)
    if mode == "move" and post["ok"]:
        shutil.rmtree(src, ignore_errors=True)
    return _record(
        models_dir, spec, landed, src, mode, action, report, not post["ok"], moved, post,
        label=label,
    )


def _commit_external(
    models_dir: Path,
    source: Path,
    mode: str,
    external_kind: str,
    label: str,
    report: dict[str, Any],
) -> dict[str, Any]:
    """未识别的目录：只登记，不猜 placement，也就不给「选为生效」的入口。"""
    if mode != "register":
        raise ValueError(f"未识别的目录不能{mode}进库：不知道它该放到哪个 placement")
    if external_kind not in _KINDS:
        raise ValueError(
            f"未识别的资产必须指定能力 external_kind（{' / '.join(_KINDS)}），"
            f"实得 {external_kind!r}：{report['basis']}"
        )
    return _record(
        models_dir, None, source, source, mode, "external", report, False,
        external_kind=external_kind, label=label,
    )


def _settle_conflict(
    models_dir: Path,
    spec: ModelSpec,
    unit: Path,
    placement: Path,
    in_cache: bool,
    on_conflict: str,
    report: dict[str, Any],
    label: str,
) -> str | dict[str, Any]:
    """库里已有同一件资产时的三种裁决：改名让位 / 只补缺项 / 并存登记。"""
    conflict = report["conflict"]
    if conflict is None:
        return ""
    if on_conflict == "coexist":
        return _record(
            models_dir,
            spec,
            Path(str(report["source_path"])),
            placement,
            "copy",
            "coexist",
            report,
            False,
            label=label,
        )
    if on_conflict == "merge":
        return "merge"
    if on_conflict != "overwrite":
        raise ValueError(
            f"{spec.name} 已在库中（{conflict['path']} · {human_bytes(conflict['size_bytes'])}"
            f"{'，且体检不通过' if not conflict['ok'] else ''}），需要先裁决冲突"
        )
    _retire(placement / unit.name if in_cache else placement, whole_dir=not in_cache)
    return "backup"


def _retire(target: Path, *, whole_dir: bool) -> None:
    """把库内那一份改名留下，绝不 rmtree——业主的字节只能由他自己处置。

    ``whole_dir`` 是「按内容落位」那类模型的形态：placement 本身就是模型的家，所以要让位
    的是里面的每一项，而不是把 placement 目录本身搬走。
    """
    if not target.is_dir():
        return
    leaves = sorted(target.iterdir()) if whole_dir else [target]
    for path in leaves:
        stamp = 1
        while (path.parent / f"{path.name}_backup_{stamp}").exists():
            stamp += 1
        path.rename(path.parent / f"{path.name}_backup_{stamp}")


def _land(unit: Path, placement: Path, contents: bool, on_progress: Progress | None) -> int:
    """先复制进同盘的临时目录，再整体换到位：半途失败不会留下半份资产。"""
    staging = placement / f".import-{uuid4().hex[:8]}"
    staging.mkdir(parents=True)
    try:
        moved = _copy_tree(
            unit, staging, contents=contents, skip_existing=False, on_progress=on_progress
        )
        for child in sorted(staging.iterdir()):
            os.replace(child, placement / child.name)
        staging.rmdir()
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return moved


def _copy_tree(
    src: Path,
    dst: Path,
    *,
    contents: bool,
    skip_existing: bool,
    on_progress: Progress | None,
) -> int:
    """把 src（或其内容）铺进 dst；``skip_existing`` 就是「只补缺项」的合并语义。"""
    root_dst = dst if contents else dst / src.name
    files = sorted(_walk_files(src), key=lambda path: str(path))
    total = _total_bytes(files)
    done = copied = 0
    for path in files:
        target = root_dst / path.relative_to(src)
        if skip_existing and target.exists():
            done += path.stat().st_size
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            done += target.stat().st_size
            copied += target.stat().st_size
        if on_progress is not None:
            on_progress(done, total)
    return copied


def _spec_by_id(model_id: str) -> ModelSpec | None:
    return next((spec for spec in registry.builtin_specs() if spec.model_id == model_id), None)


def _record(
    models_dir: Path,
    spec: ModelSpec | None,
    placed: Path,
    source: Path,
    mode: str,
    action: str,
    report: dict[str, Any],
    incomplete: bool,
    moved: int = 0,
    post: dict[str, Any] | None = None,
    external_kind: str = "",
    label: str = "",
) -> dict[str, Any]:
    """写一条「本地导入」登记，并把结果原样交回给向导第 ④ 步。"""
    entry = {
        "model_id": spec.model_id if spec else None,
        "kind": spec.kind if spec else external_kind,
        "engine": spec.engine if spec else "",
        "path": str(placed),
        "source_path": str(source),
        "mode": mode,
        "label": label or (spec.name if spec else placed.name),
        "incomplete": incomplete,
        "imported_at": int(time.time() * 1000),
    }
    _upsert_record(models_dir, entry)
    return {
        "model_id": entry["model_id"],
        "path": entry["path"],
        "mode": mode,
        "bytes_moved": moved,
        "external": mode == "register" or action == "coexist",
        "conflict_action": action or ("backup" if report["conflict"] is not None else ""),
        "incomplete": incomplete,
        "post": post,
    }


# ------------------------------------------------------------------------- 登记本（来源标记）


def manifest_path(models_dir: Path) -> Path:
    return models_dir / _MANIFEST


def records(models_dir: Path) -> list[dict[str, Any]]:
    """本地导入的登记项；文件坏了回空表，坏在哪由 ``records_error`` 说。"""
    return _read_manifest(models_dir)[0]


def records_error(models_dir: Path) -> str:
    return _read_manifest(models_dir)[1]


def forget(models_dir: Path, path: Path) -> None:
    """按路径撤销登记（只删记录，不动业主的文件）。"""
    target = str(path)
    kept = [record for record in records(models_dir) if record["path"] != target]
    _write_manifest(models_dir, kept)


def _read_manifest(models_dir: Path) -> tuple[list[dict[str, Any]], str]:
    path = manifest_path(models_dir)
    if not path.is_file():
        return [], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], f"{path} 读不出来：{type(exc).__name__}: {exc}"
    if not isinstance(data, list):
        return [], f"{path} 不是记录列表，已按空登记处理"
    return [item for item in data if isinstance(item, dict)], ""


def _upsert_record(models_dir: Path, entry: dict[str, Any]) -> None:
    existing, _error = _read_manifest(models_dir)
    kept = [item for item in existing if item.get("path") != entry["path"]]
    kept.append(entry)
    _write_manifest(models_dir, kept)


def _write_manifest(models_dir: Path, entries: list[dict[str, Any]]) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_path(models_dir)
    staging = path.with_name(f"{path.name}.{uuid4().hex[:8]}.part")
    staging.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(staging, path)

"""说话人聚类的小样本兜底：funasr「嵌入<20 全判一人」门槛的修复。

0.2.5 装测实锤的形状：重 BGM 的微短剧集 VAD 检出语音不足 ~15 秒，嵌入不到
20 条，funasr 1.4.16 的聚类后端直接全员判 0 号（角色A）——连 `asr.num_speakers`
指定的人数都被忽略。12 秒真机 clip 复现：15 条嵌入、强制 2 人、返回全零。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dramaclip.engines.analysis import diarize
from dramaclip.engines.analysis.diarize import (
    _SmallSampleClustering,
    install_small_sample_clustering,
)
from dramaclip.engines.tts.workers import funasr_worker


class _Backend:
    """记录调用并按预设返回的聚类后端替身。"""

    def __init__(self, result: Any = None) -> None:
        self.calls: list[tuple[int, int | None]] = []
        self._result = result

    def __call__(self, X: Any, oracle_num: int | None = None) -> Any:
        self.calls.append((int(X.shape[0]), oracle_num))
        return self._result if self._result is not None else np.zeros(int(X.shape[0]), "int")

    kmeans_cluster = __call__
    spectral_cluster = __call__


def _X(n: int) -> Any:
    return np.zeros((n, 4))


def test_plenty_of_embeddings_take_the_funasr_path() -> None:
    inner = _Backend(result=np.zeros(25, "int"))
    wrapper = _SmallSampleClustering(inner)

    out = wrapper(_X(25), oracle_num=None)

    assert inner.calls == [(25, None)] and (out == 0).all(), "≥20 条：原路径原样委托"


def test_few_embeddings_with_a_set_number_kmeans_the_k_clusters() -> None:
    inner = _Backend(result=np.array([0, 1, 0, 1]))
    wrapper = _SmallSampleClustering(inner)

    out = wrapper(_X(4), oracle_num=2)

    assert inner.calls == [(4, 2)], "指定人数：KMeans 直聚，不吃门槛"
    assert list(out) == [0, 1, 0, 1]


def test_more_speakers_than_embeddings_clamps() -> None:
    inner = _Backend()
    wrapper = _SmallSampleClustering(inner)

    wrapper(_X(3), oracle_num=8)

    assert inner.calls == [(3, 3)], "k 被样本数钳住：sklearn 不接受 k>n"


def test_few_embeddings_without_a_number_take_spectral_without_merging() -> None:
    inner = _Backend(result=np.array([0, 1, 0]))
    wrapper = _SmallSampleClustering(inner)

    out = wrapper(_X(3), oracle_num=None)

    assert inner.calls == [(3, None)] and list(out) == [0, 1, 0], (
        "自动估：谱聚类；0.78 余弦合并不做——BGM 下它会把仅有的几簇抹成一个"
    )


def test_failing_fallback_falls_back_to_single_speaker_not_a_crash() -> None:
    class _Broken:
        def __call__(self, X: Any, oracle_num: int | None = None) -> Any:
            raise RuntimeError("sklearn 缺席")

        kmeans_cluster = __call__
        spectral_cluster = __call__

    out = _SmallSampleClustering(_Broken())(_X(5), oracle_num=2)

    assert list(out) == [0] * 5, "聚类炸了回全零（与旧行为一致）：转写不受影响"


def test_install_wraps_a_backend_and_skips_models_without_one() -> None:
    class _Model:
        def __init__(self) -> None:
            self.cb_model: Any = None

    plain = _Model()
    assert install_small_sample_clustering(plain) is False
    assert plain.cb_model is None, "没挂 spk 的模型：不装也无害"

    shaped = _Model()
    shaped.cb_model = _Backend()
    assert install_small_sample_clustering(shaped) is True
    assert isinstance(shaped.cb_model, _SmallSampleClustering)


def test_engine_wires_the_patch_into_ensure_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """进程内路径：_ensure_model 建完模型必须装兜底（漏接线这条修复就是死码）。"""
    import dramaclip.engines.analysis.asr.paraformer as paraformer_mod
    from dramaclip.engines.analysis.transcriber import ParaformerEngine

    class _FakeAutoModel:
        instances: list[Any] = []

        def __init__(self, model: str, **kw: Any) -> None:
            self.cb_model = _Backend()
            _FakeAutoModel.instances.append(self)

    monkeypatch.setitem(sys.modules, "funasr", type("m", (), {"AutoModel": _FakeAutoModel}))
    monkeypatch.setattr(paraformer_mod, "_inproc_funasr", lambda: _FakeAutoModel)

    spk = tmp_path / "asr" / "campplus"
    spk.mkdir(parents=True)
    engine = ParaformerEngine(models_dir=tmp_path, spk_model_dir=spk)
    engine._ensure_model()

    assert isinstance(_FakeAutoModel.instances[0].cb_model, _SmallSampleClustering)


def test_worker_mirror_matches_the_canonical_semantics() -> None:
    """worker 是独立脚本（venv 里不 import dramaclip）：镜像实现逐分支对拍。"""
    from dramaclip.engines.tts.workers import funasr_worker

    inner = _Backend(result=np.array([1, 0, 1]))

    class _Model:
        cb_model: Any = inner

    model = _Model()
    funasr_worker._install_small_sample_clustering(model)

    assert model.cb_model is not inner, "装上了"
    assert list(model.cb_model(_X(3), oracle_num=2)) == [1, 0, 1]
    assert inner.calls == [(3, 2)]

    bare = _Model()
    bare.cb_model = None
    funasr_worker._install_small_sample_clustering(bare)
    assert bare.cb_model is None


def test_min_embeddings_matches_the_funasr_floor() -> None:
    assert diarize._FUNASR_MIN_EMBEDDINGS == 20
    assert funasr_floor_is_20()
    assert funasr_worker._SMALL_SAMPLE_MIN_EMBEDDINGS == 20


def funasr_floor_is_20() -> bool:
    """锁死我们对 funasr 行为的假设：版本漂移时这里先红。"""
    try:
        from funasr.models.campplus import cluster_backend
    except ImportError:
        pytest.skip("本进程没有 funasr（CI 主环境）")
    source_ok = hasattr(cluster_backend.ClusterBackend, "forward")
    return source_ok and "20" in _forward_source(cluster_backend.ClusterBackend.forward)


def _forward_source(forward: Any) -> str:
    import inspect

    return inspect.getsource(forward)

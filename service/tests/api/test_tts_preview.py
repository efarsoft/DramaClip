"""api/tts.preview：配音域的即时反馈——用当前引擎+音色合成一句短句给业主听。

试听的全部价值在于「听到的就是选的那一件」。而引擎侧对不认识的音色是**静默回退**的
（edge → Yunxi、kokoro → zf_001，见 engines/tts/engines/edge.py:28、kokoro.py:33），
储备引擎（IndexTTS2 等）压根没接进工厂。所以本接口的首要职责是把这些情况挡下来并
说清原因，而不是想办法出声。合成全程打桩：不触网、不加载真模型。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dramaclip.api import tts as tts_api
from dramaclip.engines.tts import factory
from dramaclip.infra import config


class FakeEngine:
    """替身引擎：记下每次调用与 create 收到的引擎名，并按 `payload` 写产物。"""

    def __init__(self, payload: bytes = b"audio-bytes") -> None:
        self.name = "fake"
        self.payload = payload
        self.calls: list[tuple[str, str, Path]] = []
        self.created: list[str] = []

    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        self.calls.append((text, voice, out_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(self.payload)
        return out_path


class ExplodingEngine(FakeEngine):
    def synthesize(self, text: str, voice: str, out_path: Path) -> Path:
        self.calls.append((text, voice, out_path))
        raise RuntimeError("模型文件读不出来")


def _context(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        data_dir=tmp_path,
        work_dir=tmp_path / "cache" / "analysis",
        settings=dict(config.DEFAULTS),
    )


def _install_kokoro_voice(models_dir: Path, voice: str) -> None:
    base = factory.model_dir(models_dir, "kokoro")
    (base / "voices").mkdir(parents=True, exist_ok=True)
    (base / "voices" / f"{voice}.pt").write_bytes(b"\x00")


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    """替身工厂：create 返回同一个替身，被要求的引擎名记在 `created`。"""
    stub = FakeEngine()

    def _create(name: str, models_dir: Path | None = None) -> FakeEngine:
        stub.created.append(name)
        return stub

    monkeypatch.setattr(tts_api, "create_tts", _create)
    monkeypatch.setattr(tts_api, "audio_duration_s", lambda _path: 2.5)
    monkeypatch.setattr(tts_api, "audio_container", lambda _path: "mp3")
    return stub


def test_preview_uses_engine_and_voice_from_settings(
    tmp_path: Path, fake_engine: FakeEngine
) -> None:
    context = _context(tmp_path)
    _install_kokoro_voice(context.data_dir / "models", "zf_001")

    result = tts_api.preview(context, {})

    assert context.settings["tts.engine"] == "kokoro"
    assert [voice for (_text, voice, _path) in fake_engine.calls] == ["zf_001"]
    assert result["engine"] == "kokoro"
    assert result["voice"] == "zf_001"
    assert result["duration_s"] == 2.5
    assert result["text"].strip() != ""
    assert Path(result["path"]).is_file()


def test_preview_params_override_settings(tmp_path: Path, fake_engine: FakeEngine) -> None:
    context = _context(tmp_path)

    result = tts_api.preview(
        context, {"engine": "edge", "voice": "zh-CN-YunjianNeural", "text": "这一句我自己写"}
    )

    assert fake_engine.created == ["edge"]
    assert fake_engine.calls[0][:2] == ("这一句我自己写", "zh-CN-YunjianNeural")
    assert result["engine"] == "edge"


def test_preview_rejects_reserve_engine_without_touching_factory(
    tmp_path: Path, fake_engine: FakeEngine
) -> None:
    """储备引擎点了试听就出声 = 骗业主说这能力已经能用。"""
    context = _context(tmp_path)

    with pytest.raises(Exception, match="未接入"):
        tts_api.preview(context, {"engine": "indextts2", "voice": "default"})

    assert fake_engine.created == []


def test_preview_rejects_voice_the_engine_would_swap_silently(
    tmp_path: Path, fake_engine: FakeEngine
) -> None:
    """kokoro 拿到不存在的音色会换成 zf_001——业主听到的就不是他选的那把嗓子。"""
    context = _context(tmp_path)
    _install_kokoro_voice(context.data_dir / "models", "zf_001")

    with pytest.raises(Exception, match="音色"):
        tts_api.preview(context, {"engine": "kokoro", "voice": "zf_999"})

    assert fake_engine.created == []


def test_preview_rejects_edge_voice_the_engine_would_swap(
    tmp_path: Path, fake_engine: FakeEngine
) -> None:
    context = _context(tmp_path)

    with pytest.raises(Exception, match="音色"):
        tts_api.preview(context, {"engine": "edge", "voice": "zf_001"})

    assert fake_engine.created == []


def test_preview_rejects_missing_local_model(tmp_path: Path, fake_engine: FakeEngine) -> None:
    """本地引擎没下载模型时不该闷着合成——下载入口在资产库里，这里要说清缺什么。"""
    context = _context(tmp_path)

    with pytest.raises(Exception, match="未下载"):
        tts_api.preview(context, {"engine": "kokoro", "voice": "zf_001"})

    assert fake_engine.created == []


def test_preview_rejects_blank_text(tmp_path: Path, fake_engine: FakeEngine) -> None:
    context = _context(tmp_path)

    with pytest.raises(Exception, match="试听文案"):
        tts_api.preview(context, {"engine": "edge", "text": "   "})

    assert fake_engine.created == []


def test_preview_caps_text_length(tmp_path: Path, fake_engine: FakeEngine) -> None:
    """不限量会让一句「试听」变成几分钟的本地推理，占着执行池还不一定出得来。"""
    context = _context(tmp_path)

    with pytest.raises(Exception, match="字以内"):
        tts_api.preview(context, {"engine": "edge", "text": "字" * 200})

    assert fake_engine.created == []


def test_preview_reports_engine_failure_instead_of_swapping_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配音失败就是失败：绝不换个引擎再试一次（那是拿假声音冒充业主选的引擎）。"""
    context = _context(tmp_path)
    stub = ExplodingEngine()
    created: list[str] = []

    def _create(name: str, models_dir: Path | None = None) -> ExplodingEngine:
        created.append(name)
        return stub

    monkeypatch.setattr(tts_api, "create_tts", _create)

    with pytest.raises(Exception, match="模型文件读不出来") as exc:
        tts_api.preview(context, {"engine": "edge", "voice": "zh-CN-YunxiNeural"})

    assert created == ["edge"]
    assert "edge" in str(exc.value)


def test_preview_rejects_empty_output_file(tmp_path: Path, fake_engine: FakeEngine) -> None:
    """0 字节产物在浏览器里就是「点了没声」，必须在服务端判死。"""
    context = _context(tmp_path)
    fake_engine.payload = b""

    with pytest.raises(Exception, match="空"):
        tts_api.preview(context, {"engine": "edge", "voice": "zh-CN-YunxiNeural"})


def test_preview_rejects_invalid_duration(
    tmp_path: Path, fake_engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    monkeypatch.setattr(tts_api, "audio_duration_s", lambda _path: 0.0)

    with pytest.raises(Exception, match="时长"):
        tts_api.preview(context, {"engine": "edge", "voice": "zh-CN-YunxiNeural"})


def test_preview_caches_by_engine_voice_text(tmp_path: Path, fake_engine: FakeEngine) -> None:
    """同样的引擎+音色+文案不必重复合成；换任一要素必须重合成。"""
    context = _context(tmp_path)

    first = tts_api.preview(context, {"engine": "edge", "voice": "zh-CN-YunxiNeural"})
    second = tts_api.preview(context, {"engine": "edge", "voice": "zh-CN-YunxiNeural"})
    third = tts_api.preview(context, {"engine": "edge", "voice": "zh-CN-XiaoxiaoNeural"})

    assert first["path"] == second["path"]
    assert len(fake_engine.calls) == 2
    assert third["path"] != first["path"]
    assert Path(first["path"]).parent == context.work_dir / "tts-preview"


def test_preview_names_the_file_by_the_container_the_engine_wrote(
    tmp_path: Path, fake_engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """扩展名要按落盘字节真实的容器写：kokoro/sherpa 出的是 WAV，Edge 出的才是 MP3。

    浏览器只按 Content-Type（我们按扩展名给）决定能不能播，名字骗人等于点了没声。
    """
    context = _context(tmp_path)
    _install_kokoro_voice(context.data_dir / "models", "zf_001")
    monkeypatch.setattr(tts_api, "audio_container", lambda _path: "wav")

    result = tts_api.preview(context, {"engine": "kokoro", "voice": "zf_001"})

    assert Path(result["path"]).suffix == ".wav"
    assert list((context.work_dir / "tts-preview").iterdir()) == [Path(result["path"])]


def test_preview_reuses_the_cached_file_whatever_its_container(
    tmp_path: Path, fake_engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path)
    _install_kokoro_voice(context.data_dir / "models", "zf_001")
    monkeypatch.setattr(tts_api, "audio_container", lambda _path: "wav")

    first = tts_api.preview(context, {"engine": "kokoro", "voice": "zf_001"})
    second = tts_api.preview(context, {"engine": "kokoro", "voice": "zf_001"})

    assert first["path"] == second["path"]
    assert len(fake_engine.calls) == 1


def test_preview_refuses_a_container_name_that_is_not_a_filename(
    tmp_path: Path, fake_engine: FakeEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """探测到的格式名会拼进文件名：非字母数字一律剔除，落点不得越出缓存目录。"""
    context = _context(tmp_path)
    _install_kokoro_voice(context.data_dir / "models", "zf_001")
    monkeypatch.setattr(tts_api, "audio_container", lambda _path: "../../escape")
    root = context.work_dir / "tts-preview"

    result = tts_api.preview(context, {"engine": "kokoro", "voice": "zf_001"})

    assert Path(result["path"]).parent == root
    assert Path(result["path"]).suffix == ".escape"


def test_preview_declares_container_probing() -> None:
    """探测函数与 audio_duration_s 同源（ffprobe），这里只钉它是可替换的单点。"""
    assert callable(tts_api.audio_container)


def test_preview_params_declared_in_schema(repo_root: Path) -> None:
    """RPC 参数只有 schema 一份真相源：这里钉住 result 的必填字段形状与字数上限。

    `maxLength` 与运行时常量的对账抄的是 jobs.list 的先例——Router 不校验 schema，
    钳制必须由 handler 自己做，而 schema 不随 sidecar 打包，两处漂移只能靠用例钉。
    """
    import json

    path = repo_root / "protocol" / "schemas" / "tts.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    method = next(m for m in schema["x-methods"] if m["name"] == "tts.preview")

    assert sorted(method["result"]["required"]) == ["duration_s", "engine", "path", "text", "voice"]
    assert set(method["params"]["properties"]) == {"engine", "voice", "text"}
    assert method["params"]["properties"]["text"]["maxLength"] == tts_api.MAX_PREVIEW_CHARS

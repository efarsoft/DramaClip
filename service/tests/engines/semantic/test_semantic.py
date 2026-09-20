"""engines.semantic：LLM 协议、降级链、排序。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dramaclip.engines.analysis.models import AsrSegment, AudioFeatures, SceneInfo
from dramaclip.engines.semantic import conflict, genre, ranker
from dramaclip.engines.semantic.llm_client import LlmUnavailable, parse_json_blob
from dramaclip.engines.semantic.models import ConflictScore


class FakeLlm:
    """chat_json 可编程的假客户端（只实现被测接口）。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    @property
    def model(self) -> str:
        return "fake-model"

    def chat_json(self, system: str, user: str) -> dict | list:
        self.calls.append((system, user))
        return parse_json_blob(self.reply)


def test_parse_json_blob_plain_and_fenced() -> None:
    assert parse_json_blob('[{"a":1}]') == [{"a": 1}]
    assert parse_json_blob('```json\n{"b":2}\n```') == {"b": 2}
    assert parse_json_blob('结果如下：{"c":3} 完毕') == {"c": 3}
    with pytest.raises(LlmUnavailable):
        parse_json_blob("不是 JSON")


def test_conflict_llm_path() -> None:
    scenes = [SceneInfo(start=0, end=10), SceneInfo(start=10, end=20)]
    segments = [AsrSegment(start=1, end=3, text="你给我滚出去")]
    reply = json.dumps(
        [
            {"scene_index": 0, "score": 88, "reason":"激烈争吵"},
            {"scene_index": 1, "score": 12, "reason":"平静"},
        ],
        ensure_ascii=False,
    )
    scores = conflict.score_scenes(segments, scenes, FakeLlm(reply))
    assert [s.score for s in scores] == [88, 12]
    assert scores[0].reason == "激烈争吵"


def test_conflict_falls_back_without_llm() -> None:
    scenes = [SceneInfo(start=0, end=10), SceneInfo(start=10, end=20)]
    segments = [
        AsrSegment(start=1, end=3, text="你给我滚！你这个骗子！"),
        AsrSegment(start=11, end=13, text="今天天气不错。"),
    ]
    scores = conflict.score_scenes(segments, scenes, None)
    assert scores[0].score > scores[1].score, "冲突对白场景应显著高于平静场景"
    assert scores[1].score >= 0


def test_conflict_llm_failure_falls_back() -> None:
    class Broken(FakeLlm):
        def chat_json(self, system: str, user: str) -> dict | list:
            raise LlmUnavailable("网络炸了")

    scenes = [SceneInfo(start=0, end=10)]
    segments = [AsrSegment(start=1, end=3, text="我要报仇！")]
    scores = conflict.score_scenes(segments, scenes, Broken(""))
    assert len(scores) == 1 and scores[0].score > 30, "LLM 失败应走关键词降级"


def test_genre_llm_and_fallback() -> None:
    assert genre.classify("全部", FakeLlm('{"genre":"复仇"}')) == "复仇"
    assert genre.classify("她要为母亲报仇雪恨", None) == "复仇"
    assert genre.classify("无关键词文本", None) == "其他"


def test_ranker_orders_and_truncates() -> None:
    scenes_scores = [
        ConflictScore(scene_index=0, start=0, end=10, score=30),
        ConflictScore(scene_index=1, start=10, end=20, score=90),
        ConflictScore(scene_index=2, start=20, end=30, score=60),
        ConflictScore(scene_index=3, start=30, end=40, score=20),
    ]
    audio = AudioFeatures(energy_curve=[[0, 0.2], [10, 0.25], [20, 0.1], [30, 0.05]])
    segments = [AsrSegment(start=11, end=19, text="震惊！竟然是他！疯了！")]
    highlights = ranker.rank_highlights(scenes_scores, audio, segments, top_ratio=0.5)
    assert len(highlights) == 2
    assert highlights[0].score >= highlights[1].score
    assert highlights[0].start == 10 and highlights[0].end == 20, "冲突+情绪双高的场景应排第一"


# --------------------------------------------------------------------------- 留痕
# 冲突打分与题材判定是整条链上最"悄悄变差"的两处：LLM 挂了退回关键词、模型漏答
# 场景补 50 分，界面上一格都不显示。留痕是唯一能被复核的证据。

_SCENES = [SceneInfo(start=0, end=10), SceneInfo(start=10, end=20)]
_SEGMENTS = [AsrSegment(start=1, end=3, text="你给我滚出去")]


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_conflict_trace_keeps_the_round_trip(tmp_path: Path) -> None:
    trace = tmp_path / "conflict_ep1.json"
    reply = json.dumps(
        [
            {"scene_index": 0, "score": 88, "reason": "激烈争吵"},
            {"scene_index": 1, "score": 12, "reason": "平静"},
        ],
        ensure_ascii=False,
    )
    conflict.score_scenes(_SEGMENTS, _SCENES, FakeLlm(reply), trace_path=trace)
    blob = _read(trace)
    assert blob["degraded"] is False
    assert blob["raw"][0]["score"] == 88, "留痕没记下模型到底回了什么"
    assert blob["scene_count"] == 2 and blob["answered"] == 2


def test_conflict_trace_counts_scenes_the_model_left_unanswered(tmp_path: Path) -> None:
    """漏答的场景拿 50 分补数——分数照旧，但补了几个必须看得见。"""
    trace = tmp_path / "conflict.json"
    reply = json.dumps([{"scene_index": 0, "score": 88, "reason": "吵"}], ensure_ascii=False)
    scores = conflict.score_scenes(_SEGMENTS, _SCENES, FakeLlm(reply), trace_path=trace)
    blob = _read(trace)
    assert scores[1].score == 50
    assert blob["answered"] == 1 and blob["missing_scenes"] == 1


def test_conflict_trace_records_why_it_degraded(tmp_path: Path) -> None:
    class Broken(FakeLlm):
        def chat_json(self, system: str, user: str) -> dict | list:
            raise LlmUnavailable("网络炸了")

    trace = tmp_path / "conflict.json"
    conflict.score_scenes(_SEGMENTS, _SCENES, Broken(""), trace_path=trace)
    blob = _read(trace)
    assert blob["degraded"] is True
    assert "网络炸了" in blob["error"]


def test_conflict_without_client_writes_no_trace(tmp_path: Path) -> None:
    """没发请求就没有往返可留——降级路本身不该造一个空壳文件充数。"""
    trace = tmp_path / "conflict.json"
    conflict.score_scenes(_SEGMENTS, _SCENES, None, trace_path=trace)
    assert not trace.exists()


def test_genre_trace_keeps_round_trip_and_verdict(tmp_path: Path) -> None:
    trace = tmp_path / "genre.json"
    assert genre.classify("她要为母亲报仇", FakeLlm('{"genre":"复仇"}'), trace_path=trace) == "复仇"
    blob = _read(trace)
    assert blob["raw"] == {"genre": "复仇"}
    assert blob["matched"] is True and blob["degraded"] is False


def test_genre_trace_exposes_the_silent_fallback(tmp_path: Path) -> None:
    """模型答了个库外题材：界面看到的"家庭伦理"其实来自关键词，留痕必须说明这点。"""
    trace = tmp_path / "genre.json"
    text = "婆婆儿媳争家产"
    assert genre.classify(text, FakeLlm('{"genre":"武侠"}'), trace_path=trace) == "家庭伦理"
    blob = _read(trace)
    assert blob["raw"] == {"genre": "武侠"}
    assert blob["matched"] is False and blob["degraded"] is True

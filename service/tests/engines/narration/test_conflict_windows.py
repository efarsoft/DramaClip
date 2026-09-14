"""规则类两模式的条数来源：全剧 top-K 冲突窗（规格 §4.3 ④）+ 轮转发窗成 K 手。

夹具手搓 ConflictScore，不跑分析层也不跑编排器：这两个函数都是纯函数，把上游拉进来
只会让"榜单排错了"与"冲突分算错了"两种失败混在一起。

`top_conflict_windows` 钉四件事，每件都对应一个真实的坏法：
① 跨集排序（`ConflictScore` 不带集身份，排完不知道那一窗属于谁就没法用）；
② 按集去重（同一集的两窗喂进 `build_raw_clip` 会得到逐字节相同的方案，
   那不是 K 条互异，是 1 条复制 K 份，还会被重叠闸门判成 100% 重叠）；
③ 同分时的确定性（分析层给的是 0-100 的**整数**分，全剧尺度上同分很常见——
   活库实测 333 个场景只有 19 个不同分值；不确定就意味着"整组重规划"两次取到不同的集）；
④ limit < 1 即抛（与 `angles.select_angles` 的 `k < 1` 同一口径）。

`deal_windows` 钉的是**规格 §1 的跨集要求与 §4.3 ④ 的条数要求怎么同时成立**：
一集一条满足条数、违反跨集；把窗轮转发成 K 手、每手若干集，两者都满足，
而且手与手不共集 ⇒ 取材重叠恒为 0。
"""

from __future__ import annotations

import pytest

from dramaclip.engines.narration import pipeline
from dramaclip.engines.semantic.models import ConflictScore


def _scene(index: int, score: int, start: float = 0.0) -> ConflictScore:
    return ConflictScore(scene_index=index, start=start, end=start + 8.0, score=score)


def test_picks_the_highest_scoring_window_across_episodes() -> None:
    """榜单是全剧的、也是全集内的：不看"每集第一个场景"，看"每集最狠的那一窗"。

    三集、limit=2，且第 1 集的最高分窗（95）刻意放在场景表的**第二位**：
    只扫每集首个场景的实现会拿它的 70 分去比，把这一集挤出前二——那是"按集取头"
    而不是"全剧取顶"。三集配 limit=2 也让"取满就停"这条可观察（见 Step 5 的 #4）。
    """
    episodes = [
        (1, [_scene(0, 70), _scene(1, 95, 10.0)]),
        (2, [_scene(0, 85)]),
        (3, [_scene(0, 90), _scene(1, 60, 10.0)]),
    ]
    picked = pipeline.top_conflict_windows(episodes, 2)
    assert [(number, scene.score) for number, scene in picked] == [(1, 95), (3, 90)]


def test_one_window_per_episode_so_the_plans_are_not_copies() -> None:
    """同一集的两个高分窗只留一个：留两个就会产出两条逐字节相同的方案。"""
    episodes = [(1, [_scene(0, 95), _scene(1, 94, 10.0), _scene(2, 93, 20.0)])]
    picked = pipeline.top_conflict_windows(episodes, 3)
    assert [number for number, _scene in picked] == [1], "一集出了两条，那不是互异是复制"
    assert picked[0][1].score == 95, "留的必须是该集排名最高的那一窗"


def test_returns_fewer_than_limit_when_episodes_run_out() -> None:
    """规格 §1 允许「每模式产出 1..K 条」：集不够就少出，不许凑数、也不许抛。"""
    episodes = [(1, [_scene(0, 90)]), (2, [_scene(0, 80)])]
    assert len(pipeline.top_conflict_windows(episodes, 5)) == 2


def test_ties_are_broken_deterministically() -> None:
    """同分按 (集号, scene_index) 定序：整组重规划必须可复现。

    分析层的分是 0-100 的整数（`ConflictScore.score: int`），80 集的剧里同分是常态。
    只按 -score 排时 Python 的 sorted 虽然稳定，但稳定于**输入顺序**，而输入顺序来自
    `episodes_repo.list_by_project` —— 那个顺序本身没有契约。故必须显式给次键。
    """
    shuffled = [(2, [_scene(5, 70)]), (1, [_scene(9, 70)]), (2, [_scene(1, 70)])]
    reordered = [(1, [_scene(9, 70)]), (2, [_scene(1, 70)]), (2, [_scene(5, 70)])]
    assert pipeline.top_conflict_windows(shuffled, 2) == pipeline.top_conflict_windows(
        reordered, 2
    )
    assert [(n, s.scene_index) for n, s in pipeline.top_conflict_windows(shuffled, 2)] == [
        (1, 9),
        (2, 1),
    ]


def test_episodes_without_scenes_are_skipped_not_fatal() -> None:
    """某集分析过但一个冲突场景都没出：跳过它，不要抛，也不要塞一个空窗进去。"""
    episodes = [(1, []), (2, [_scene(0, 50)])]
    assert [(n, s.score) for n, s in pipeline.top_conflict_windows(episodes, 3)] == [(2, 50)]


def test_no_episodes_at_all_gives_an_empty_list() -> None:
    """空榜是"无从取窗"，由调用方（api 层）决定怎么响；纯函数不发明错误语义。"""
    assert pipeline.top_conflict_windows([], 3) == []


def test_limit_below_one_raises() -> None:
    with pytest.raises(ValueError, match="limit 必须"):
        pipeline.top_conflict_windows([(1, [_scene(0, 90)])], 0)


def test_deal_windows_deals_round_robin_into_disjoint_hands() -> None:
    """轮转发窗：第 j 手拿排名 j, j+hands, j+2·hands…，手与手**不共集**。

    不共集是这条设计的承重点：规则类两模式的编排器是 (取材集, 该集场景表) 的确定性
    纯函数，两手共集就会共画面，取材重叠直接顶到 60% 阈值上，K 条里只有第一条能落库。
    夹具的输入名次刻意打乱（4,1,9,2,7,3），断言的是**发完之后每手内部升序**。
    """
    windows = [(number, _scene(0, 90 - number)) for number in (4, 1, 9, 2, 7, 3)]
    assert pipeline.deal_windows(windows, 3) == [[2, 4], [1, 7], [3, 9]]


def test_deal_windows_gives_every_hand_a_strong_episode() -> None:
    """轮转而不是切块：切块会让第 1 手独占全剧最狠的几集，三条片的强弱差一个量级。"""
    windows = [(number, _scene(0, 90 - number)) for number in range(1, 7)]
    hands = pipeline.deal_windows(windows, 3)
    assert [hand[0] for hand in hands] == [1, 2, 3], "每手都该拿到一个高分窗"


def test_deal_windows_returns_fewer_hands_than_asked_when_episodes_run_out() -> None:
    """规格 §1 允许「每模式产出 1..K 条」：集不够就少发几手，不许凑数、也不许抛。"""
    windows = [(1, _scene(0, 90)), (2, _scene(0, 80))]
    assert pipeline.deal_windows(windows, 5) == [[1], [2]]


def test_deal_windows_on_an_empty_ranking_is_empty() -> None:
    """空榜是"无从取窗"，由调用方决定怎么响；纯函数不发明错误语义（与上面同一条口径）。"""
    assert pipeline.deal_windows([], 3) == []


def test_deal_windows_below_one_hand_raises() -> None:
    with pytest.raises(ValueError, match="手数 hands 必须"):
        pipeline.deal_windows([(1, _scene(0, 90))], 0)

"""narration_plans 的角度五列：落库、读回、按 batch 取组。

五列的存在理由见 P-2a 计划《定案三》。这里只钉一件事：写进去的角度信息必须
原样读得回来——`plan_data` 是 JSON 文本、这五列是真列，读回路径（`_row_to_dict`
的 zip）漏一列不会报错，只会静默少一个字段。
"""

from __future__ import annotations

import sqlite3

from dramaclip.infra.storage.repos import plans as plans_repo
from dramaclip.infra.storage.repos import projects as projects_repo


def _seed_project(conn: sqlite3.Connection) -> str:
    return str(projects_repo.create(conn, "角度剧", "D:/media/角度剧")["id"])


def test_create_persists_the_five_angle_columns(memory_db: sqlite3.Connection) -> None:
    project_id = _seed_project(memory_db)
    row = plans_repo.create(
        memory_db,
        project_id,
        "full_narration",
        ["ep1"],
        {"mode": "full_narration", "timeline": []},
        angle="复仇线",
        angle_reason="全剧最狠的一次反杀落在第 3 集",
        variant_index=2,
        overlap_max=0.31,
        batch_id="batch-a",
    )
    assert row["angle"] == "复仇线"
    assert row["angle_reason"] == "全剧最狠的一次反杀落在第 3 集"
    assert row["variant_index"] == 2
    assert row["overlap_max"] == 0.31
    assert row["batch_id"] == "batch-a"

    fetched = plans_repo.get(memory_db, str(row["id"]))
    assert fetched is not None
    assert fetched["angle"] == "复仇线"
    assert fetched["angle_reason"] == "全剧最狠的一次反杀落在第 3 集"
    assert fetched["variant_index"] == 2
    assert fetched["overlap_max"] == 0.31
    assert fetched["batch_id"] == "batch-a"


def test_angle_columns_default_to_the_migration_defaults(
    memory_db: sqlite3.Connection,
) -> None:
    """不传角度信息也要能建（迁移的 DEFAULT 就是这条契约），且首条方案 overlap_max 为空。"""
    project_id = _seed_project(memory_db)
    row = plans_repo.create(
        memory_db, project_id, "raw_clip", ["ep1"], {"mode": "raw_clip", "timeline": []}
    )
    assert row["angle"] == "" and row["angle_reason"] == ""
    assert row["variant_index"] == 1
    assert row["overlap_max"] is None, "首条方案没有兄弟，重叠率是「无从比」而不是 0"
    assert row["batch_id"] is None


def test_list_by_batch_returns_only_that_batch_in_mode_then_variant_order(
    memory_db: sqlite3.Connection,
) -> None:
    """一个 batch 通常跨多个模式，阶段③ 要按模式分组显示 → 排序键必须带 narration_mode。

    夹具刻意做成**两模式 + 变体号交错**（raw_clip 的 1 号先插、full_narration 的
    2 号次之、1 号最后）：只按 variant_index 排会把 raw_clip·1 排到最前，
    只按 created_at 排会照抄插入顺序，两者都与 (模式, 变体号) 不同——
    于是排序键的两半**各有一条变异能把它打红**（Step 7 的 #3 与 #3b）。
    原夹具是单模式 + 变体号递增，那两个变异一个都红不了（实测过）。
    """
    project_id = _seed_project(memory_db)
    seeded = (
        ("batch-a", "raw_clip", 1),
        ("batch-a", "full_narration", 2),
        ("batch-a", "full_narration", 1),
        ("batch-b", "full_narration", 1),
    )
    created: list[str] = []
    for batch, mode, index in seeded:
        row = plans_repo.create(
            memory_db,
            project_id,
            mode,
            ["ep1"],
            {"mode": mode, "timeline": []},
            angle=f"角度{mode}{index}",
            variant_index=index,
            batch_id=batch,
        )
        created.append(str(row["id"]))
    # created_at 是毫秒精度，背靠背插入实测 2000/2000 撞同一个值（见《计划修订记录》B4）。
    # 显式拉开时间戳：`ORDER BY created_at` 这条变异必须因为**顺序**而红，
    # 不能靠 SQLite 在并列值上的扫描顺序来红——那是实现细节，换个版本就变。
    memory_db.executemany(
        "UPDATE narration_plans SET created_at = ? WHERE id = ?",
        [(1_700_000_000_000 + offset, plan_id) for offset, plan_id in enumerate(created)],
    )
    memory_db.commit()

    group = plans_repo.list_by_batch(memory_db, project_id, "batch-a")
    assert [(row["narration_mode"], row["variant_index"]) for row in group] == [
        ("full_narration", 1),
        ("full_narration", 2),
        ("raw_clip", 1),
    ]
    assert plans_repo.list_by_batch(memory_db, project_id, "batch-缺") == []


def test_list_by_project_still_carries_the_angle_columns(
    memory_db: sqlite3.Connection,
) -> None:
    """`list_by_project` 走的是同一个 `_row_to_dict`：新五列必须在**列表**路径上也读得回来。

    **不断顺序**。原用例断言 `[:2] == ["新角度", "旧角度"]`，靠 `ORDER BY created_at DESC`；
    实测背靠背两次 `_now_ms()` 有 2000/2000 撞同一个毫秒值，而并列时该排序
    200/200 返回**先插入**那一行——也就是说那条断言在落地那天就是红的（B4）。
    顺序由下一条用例按"并列必须确定性"这个真实不变量去钉。
    """
    project_id = _seed_project(memory_db)
    plans_repo.create(
        memory_db, project_id, "raw_clip", [], {"mode": "raw_clip"}, angle="旧角度"
    )
    plans_repo.create(
        memory_db, project_id, "raw_clip", [], {"mode": "raw_clip"}, angle="新角度"
    )
    listed = plans_repo.list_by_project(memory_db, project_id)
    assert {row["angle"] for row in listed} == {"旧角度", "新角度"}
    assert len(listed) == 2


def test_list_by_project_breaks_created_at_ties_by_id(
    memory_db: sqlite3.Connection,
) -> None:
    """并列时间戳必须有确定性兜底：`ORDER BY created_at DESC, id`。

    `infra/jobs.py::list_recent` 为同一件事补过 `created_at, id`（理由写在它的
    docstring 里：同毫秒内变更的任务否则顺序随机，队列页每次刷新可能跳行）。
    阶段③ 的"最近方案"列表有完全一样的症状。

    夹具用 raw SQL 直插两个**自己挑的** id，且插入顺序与 id 升序**相反**：
    `DESC` 只作用于 created_at，并列时 id 是升序，故兜底给出 ["aaa","zzz"]、
    不兜底给出插入顺序 ["zzz","aaa"]——两者必然不同，Step 7 的变异 #5 才红得下来。
    """
    project_id = _seed_project(memory_db)
    for plan_id in ("zzz", "aaa"):
        memory_db.execute(
            "INSERT INTO narration_plans (id, project_id, narration_mode, episode_ids,"
            " plan_data, status, created_at, angle) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                plan_id,
                project_id,
                "raw_clip",
                "[]",
                '{"mode": "raw_clip"}',
                "ready",
                1_700_000_000_000,
                plan_id,
            ),
        )
    memory_db.commit()
    listed = plans_repo.list_by_project(memory_db, project_id)
    assert [row["id"] for row in listed] == ["aaa", "zzz"], (
        "并列 created_at 的顺序不确定：阶段③ 每次刷新可能跳行"
    )

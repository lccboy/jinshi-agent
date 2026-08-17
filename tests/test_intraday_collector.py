# V0.3 任务 3：盘中快照采集器测试（TDD）
# 依据 docs/DATA_MODEL.md §5：snapshots.ndjson 每行一个快照，只增不改；phase 节奏 auction/open/tail
import json
import os

from services.collector.intraday_collector import (
    append_snapshot,
    build_snapshot,
    cadence_for_time,
    phase_for_time,
    read_snapshots,
    run_market_session,
    write_meta,
)


def test_phase_for_time():
    assert phase_for_time("09:20:00") == "auction"    # 竞价 09:15-09:30
    assert phase_for_time("09:30:00") == "open"       # 开盘 09:30-10:30
    assert phase_for_time("10:00:00") == "open"
    assert phase_for_time("10:31:00") == "tail"       # 尾盘 10:31-15:00
    assert phase_for_time("14:59:59") == "tail"
    assert phase_for_time("15:20:00") == "tail"


def test_cadence_for_market_time():
    assert cadence_for_time("09:14:59") == ("closed", None)
    assert cadence_for_time("09:15:00") == ("auction", 3)
    assert cadence_for_time("09:30:00") == ("open", 3)
    assert cadence_for_time("10:31:00") == ("tail", 30)
    assert cadence_for_time("11:31:00") == ("lunch", None)
    assert cadence_for_time("13:00:00") == ("tail", 30)
    assert cadence_for_time("15:00:01") == ("closed", None)


def test_build_snapshot_shape():
    snap = build_snapshot("2026-08-14 09:31:03", "open",
                          indexes={"SH000001": {"price": 3205.2, "change_pct": 0.47}},
                          sectors=[{"id": "801001", "name": "芯片", "strength": 23819}],
                          ladder={"total_limit_up": 12, "max_consecutive": 4},
                          stocks={"SZ300487": {"price": 66.9, "change": 0.51, "volRatio": 0.98}})
    assert snap["ts"] == "2026-08-14 09:31:03"
    assert snap["phase"] == "open"
    assert snap["indexes"]["SH000001"]["price"] == 3205.2
    assert snap["sectors"][0]["id"] == "801001"
    assert snap["ladder"]["max_consecutive"] == 4
    assert snap["stocks"]["SZ300487"]["volRatio"] == 0.98
    # 可 JSON 序列化（ndjson 行）
    json.dumps(snap, ensure_ascii=False)


def test_append_snapshot_append_only(tmp_path):
    day = tmp_path / "2026-08-14"
    day.mkdir()
    ndjson = day / "snapshots.ndjson"

    append_snapshot(str(day), {"ts": "2026-08-14 09:31:03", "phase": "open", "stocks": {}})
    append_snapshot(str(day), {"ts": "2026-08-14 09:31:06", "phase": "open", "stocks": {}})
    append_snapshot(str(day), {"ts": "2026-08-14 09:31:09", "phase": "open", "stocks": {}})

    snaps = read_snapshots(str(day))
    assert len(snaps) == 3
    assert [s["ts"] for s in snaps] == ["2026-08-14 09:31:03", "2026-08-14 09:31:06", "2026-08-14 09:31:09"]
    # 追加后历史行不变（只增不改）
    append_snapshot(str(day), {"ts": "2026-08-14 09:31:12", "phase": "open", "stocks": {}})
    snaps = read_snapshots(str(day))
    assert len(snaps) == 4
    assert snaps[0]["ts"] == "2026-08-14 09:31:03"


def test_append_snapshot_creates_dir(tmp_path):
    day = tmp_path / "2026-08-15"
    append_snapshot(str(day), {"ts": "2026-08-15 09:31:00", "phase": "open"})
    assert (day / "snapshots.ndjson").exists()
    assert len(read_snapshots(str(day))) == 1


def test_read_snapshots_missing(tmp_path):
    assert read_snapshots(str(tmp_path / "nope")) == []


def test_write_meta(tmp_path):
    day = tmp_path / "2026-08-14"
    write_meta(str(day), "2026-08-14", cadence="3s", status="running", extra={"note": "x"})
    meta = json.load(open(str(day / "meta.json"), encoding="utf-8"))
    assert meta["date"] == "2026-08-14"
    assert meta["cadence"] == "3s"
    assert meta["status"] == "running"
    assert meta["note"] == "x"


def test_run_market_session_switches_cadence_and_stops(tmp_path):
    import datetime
    times = iter([
        datetime.datetime(2026, 8, 17, 9, 15),
        datetime.datetime(2026, 8, 17, 9, 30),
        datetime.datetime(2026, 8, 17, 11, 31),
        datetime.datetime(2026, 8, 17, 13, 0),
        datetime.datetime(2026, 8, 17, 15, 0, 1),
    ])
    sleeps = []
    scanned = []

    def fake_collect(codes, phase="open"):
        return {"ts": "x", "phase": phase, "stocks": {}}, {"SH600000": {"price": 10}}

    count = run_market_session(str(tmp_path), "2026-08-17", ["600000"],
                               now_fn=lambda: next(times), sleep_fn=sleeps.append,
                               collect_fn=fake_collect, on_quotes=lambda quotes: scanned.append(quotes))
    assert count == 3
    assert [s["phase"] for s in read_snapshots(str(tmp_path / "2026-08-17"))] == ["auction", "open", "tail"]
    meta = json.loads((tmp_path / "2026-08-17/meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == "done" and meta["snapshots"] == 3
    assert len(scanned) == 3

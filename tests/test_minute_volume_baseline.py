import json
import gzip
import struct

import pytest

from services.collector.minute_volume_baseline import (
    build_minute_baseline,
    build_vipdoc_lc1_baseline,
    archive_vipdoc_lc1_day,
    generate_vipdoc_lc1_baseline,
    write_minute_baseline_once,
)


def _snap(ts, volume, amount, source_ts=None):
    return {
        "ts": ts,
        "phase": "auction" if ts[11:16] < "09:30" else "open",
        "stocks": {
            "SH600001": {
                "volume": volume,
                "amount": amount,
                "source_ts": source_ts or ts.replace("-", "").replace(":", "").replace(" ", ""),
            }
        },
    }


def test_build_minute_baseline_diffs_cumulative_facts_by_natural_minute():
    snapshots = [
        _snap("2026-08-26 09:25:00", 100, 1000),
        _snap("2026-08-26 09:30:20", 130, 1450),
        _snap("2026-08-26 09:30:58", 150, 1750),
        _snap("2026-08-26 09:31:58", 230, 2950),
        _snap("2026-08-26 09:32:58", 270, 3550),
    ]

    result = build_minute_baseline(
        snapshots, "2026-08-26", min_stock_minutes=3,
        expected_minutes=3, min_coverage=1.0, max_missing_minutes=0,
    )

    row = result["stocks"]["SH600001"]
    assert row["auction_volume"] == 100
    assert row["auction_amount"] == 1000
    assert row["auction_source_ts"].endswith("09:25:00+08:00")
    assert row["max_1m_volume"] == 80
    assert row["max_1m_volume_time"] == "09:32"
    assert row["max_1m_amount"] == 1200
    assert row["max_1m_amount_time"] == "09:32"
    assert row["day_volume"] == 270
    assert row["day_amount"] == 3550
    assert result["quality"]["status"] == "pass"


@pytest.mark.parametrize("bad_field", ["volume", "amount", "source_ts"])
def test_build_minute_baseline_fails_closed_on_missing_required_fact(bad_field):
    snapshots = [
        _snap("2026-08-26 09:25:00", 100, 1000),
        _snap("2026-08-26 09:30:58", 150, 1750),
    ]
    snapshots[1]["stocks"]["SH600001"][bad_field] = None

    result = build_minute_baseline(
        snapshots, "2026-08-26", min_stock_minutes=1,
        expected_minutes=1, min_coverage=1.0, max_missing_minutes=0,
    )

    assert "SH600001" not in result["stocks"]
    assert result["quality"]["status"] == "fail"
    assert result["quality"]["invalid_stocks"] == 1


def test_build_minute_baseline_rejects_cumulative_reset_and_time_reversal():
    snapshots = [
        _snap("2026-08-26 09:25:00", 100, 1000, "20260826092500"),
        _snap("2026-08-26 09:30:58", 150, 1700, "20260826093058"),
        _snap("2026-08-26 09:31:58", 140, 1900, "20260826092958"),
    ]

    result = build_minute_baseline(
        snapshots, "2026-08-26", min_stock_minutes=1,
        expected_minutes=2, min_coverage=1.0, max_missing_minutes=0,
    )

    assert result["quality"]["status"] == "fail"
    assert result["quality"]["invalid_stocks"] == 1
    assert "SH600001" not in result["stocks"]


def test_write_minute_baseline_is_append_only(tmp_path):
    first = {"data_date": "2026-08-26", "quality": {"status": "pass"}, "stocks": {}}
    path = write_minute_baseline_once(first, tmp_path)
    write_minute_baseline_once({**first, "source": "must_not_replace"}, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == first


LC1_RECORD = struct.Struct("<HHfffffII")


def _lc1_date(year, month, day):
    return (year - 2004) * 2048 + month * 100 + day


def _write_lc1(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(LC1_RECORD.pack(
        _lc1_date(*row[0]), row[1], row[2], row[3], row[4], row[5], row[6], row[7], 0,
    ) for row in rows))


def test_build_vipdoc_lc1_baseline_uses_previous_complete_day_and_stock_whitelist(tmp_path):
    vipdoc = tmp_path / "vipdoc"
    complete = [
        ((2026, 8, 26), 571, 10.0, 10.1, 9.9, 10.0, 1000.0, 100),
        ((2026, 8, 26), 572, 10.0, 10.2, 10.0, 10.1, 5000.0, 500),
        ((2026, 8, 26), 900, 10.1, 10.2, 10.0, 10.1, 3000.0, 300),
    ]
    # 目标日存在，但绝不能进入目标日前基线。
    current = [((2026, 8, 27), 571, 11.0, 11.0, 11.0, 11.0, 9999.0, 999)]
    _write_lc1(vipdoc / "sh" / "minline" / "sh600001.lc1", complete + current)
    _write_lc1(vipdoc / "sh" / "minline" / "sh000001.lc1", complete)

    result = build_vipdoc_lc1_baseline(
        vipdoc, "2026-08-27", ["SH600001"], expected_minutes=3, min_coverage=1.0,
    )

    assert result["data_date"] == "2026-08-26"
    assert result["source"] == "tdx_vipdoc_lc1"
    assert result["private"] is True
    assert result["quality"] == {
        "status": "pass", "coverage": 1.0, "missing_minutes": 0,
        "valid_stocks": 1, "invalid_stocks": 0,
    }
    assert set(result["stocks"]) == {"SH600001"}
    row = result["stocks"]["SH600001"]
    assert row["bar_count"] == 3
    assert row["max_1m_volume"] == 500
    assert row["max_1m_volume_time"] == "09:32"
    assert row["max_1m_amount"] == 5000
    assert row["day_volume"] == 900
    assert row["day_amount"] == 9000


def test_build_vipdoc_lc1_baseline_fails_closed_for_incomplete_stock(tmp_path):
    vipdoc = tmp_path / "vipdoc"
    rows = [
        ((2026, 8, 26), 571, 10.0, 10.1, 9.9, 10.0, 1000.0, 100),
        ((2026, 8, 26), 572, 10.0, 10.2, 10.0, 10.1, 5000.0, 500),
    ]
    _write_lc1(vipdoc / "sz" / "minline" / "sz000001.lc1", rows)

    result = build_vipdoc_lc1_baseline(
        vipdoc, "2026-08-27", ["SZ000001"], expected_minutes=3, min_coverage=1.0,
    )

    assert result["quality"]["status"] == "fail"
    assert result["quality"]["invalid_stocks"] == 1
    assert result["stocks"] == {}


def test_generate_vipdoc_lc1_baseline_writes_only_member_private_facts_once(tmp_path):
    vipdoc = tmp_path / "vipdoc"
    rows = [
        ((2026, 8, 26), 571, 10.0, 10.1, 9.9, 10.0, 1000.0, 100),
        ((2026, 8, 26), 572, 10.0, 10.2, 10.0, 10.1, 5000.0, 500),
        ((2026, 8, 26), 900, 10.1, 10.2, 10.0, 10.1, 3000.0, 300),
    ]
    _write_lc1(vipdoc / "bj" / "minline" / "bj920001.lc1", rows)
    member_root = tmp_path / "members" / "vip_001"

    document, path = generate_vipdoc_lc1_baseline(
        vipdoc, "2026-08-27", ["BJ920001"], member_root,
        expected_minutes=3, min_coverage=1.0,
    )
    first = path.read_text(encoding="utf-8")
    generate_vipdoc_lc1_baseline(
        vipdoc, "2026-08-27", ["BJ920001"], member_root,
        expected_minutes=3, min_coverage=1.0,
    )

    assert path == member_root / "facts" / "2026-08-26" / "minute_baseline.json"
    assert document["private"] is True
    assert path.read_text(encoding="utf-8") == first


def test_archive_lc1_day_is_isolated_complete_and_immutable(tmp_path):
    vipdoc = tmp_path / "vipdoc"
    rows = [
        ((2026, 8, 31), 571, 10, 10, 10, 10, 1000, 100),
        ((2026, 8, 31), 572, 10, 10, 10, 10, 2000, 200),
        ((2026, 8, 31), 573, 10, 10, 10, 10, 3000, 300),
    ]
    path = vipdoc / "sh" / "minline" / "sh600001.lc1"
    _write_lc1(path, rows)
    member = tmp_path / "members" / "U1"

    manifest, manifest_path = archive_vipdoc_lc1_day(
        vipdoc, "2026-08-31", ["SH600001"], member,
        expected_minutes=3, min_coverage=1.0)

    assert manifest["status"] == "complete"
    assert manifest["record_count"] == 3
    archive = member / "archive" / "2026-08-31"
    assert manifest_path == archive / "minute_manifest.json"
    assert (archive / "minute_events.ndjson.gz").is_file()
    with gzip.open(archive / "minute_volume.ndjson.gz", "rt", encoding="utf-8") as handle:
        assert len(handle.readlines()) == 3
    baseline = json.loads((member / "facts" / "2026-08-31" / "minute_baseline.json").read_text())
    assert baseline["quality"]["status"] == "pass"

    first = manifest_path.read_text(encoding="utf-8")
    _write_lc1(path, [*rows[:-1], ((2026, 8, 31), 573, 10, 10, 10, 10, 9999, 999)])
    archive_vipdoc_lc1_day(vipdoc, "2026-08-31", ["SH600001"], member,
                           expected_minutes=3, min_coverage=1.0)
    assert manifest_path.read_text(encoding="utf-8") == first
    assert list(archive.glob("minute_volume.divergent-*.ndjson.gz"))

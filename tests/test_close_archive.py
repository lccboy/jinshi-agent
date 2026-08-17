import json

from services.collector.close_archive import (
    build_limitup_fact,
    validate_close_snapshot,
    write_limitup_fact_once,
)


def test_validate_close_snapshot_requires_full_sector_and_stock_coverage(tmp_path):
    summary = tmp_path / "kpl_2026-08-17.json"
    stocks = tmp_path / "kpl_2026-08-17_stocks.json"
    summary.write_text(json.dumps({"archived": True, "sectors": [{"id": str(i)} for i in range(80)]}), encoding="utf-8")
    stocks.write_text(json.dumps({"stocks": {str(i): [] for i in range(80)}}), encoding="utf-8")
    report = validate_close_snapshot("2026-08-17", tmp_path)
    assert report["complete"] is True
    assert report["sector_count"] == 80 and report["main_plate_count"] == 80


def test_build_limitup_fact_accepts_single_kpl_reason_file():
    source = {"reasons": {"300487": {"reason": "存储", "detail": "原文",
                                      "boards": "首板", "concepts": "存储、芯片",
                                      "name": "蓝晓科技"}}}
    facts = build_limitup_fact(source)
    assert facts["SZ300487"]["primary"] == "kpl"
    assert facts["SZ300487"]["concepts"] == ["存储", "芯片"]


def test_write_limitup_fact_is_append_only(tmp_path):
    first = {"SZ300487": {"reason": "存储"}}
    path = write_limitup_fact_once("2026-08-17", first, tmp_path)
    write_limitup_fact_once("2026-08-17", {"SZ300487": {"reason": "不得覆盖"}}, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == first

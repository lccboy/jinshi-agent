import json
from pathlib import Path


def test_member_history_projection_is_ranked_bounded_and_excludes_auction():
    from services.member_local_service import project_member_history_pools

    alerts = {
        f"SZ{i:06d}": {"stars": i % 4, "score": i, "confirm": {"money_flow": i % 2 == 0}}
        for i in range(45)
    }
    candidates = {
        f"SH{i:06d}": {"stars": i % 3, "score": i, "confirm": {}}
        for i in range(140)
    }
    candidates["SH999999"] = {"stars": 9, "score": 999, "signal_family": "auction_radar"}

    document, summary = project_member_history_pools(
        {"alert": alerts, "candidate": candidates}, "2026-09-03")

    assert document["data_date"] == "2026-09-03"
    assert len(document["pools"]["alert"]) == 30
    assert len(document["pools"]["candidate"]) == 100
    assert "SH999999" not in document["pools"]["candidate"]
    assert summary == {
        "alert": {"total": 45, "shown": 30},
        "candidate": {"total": 140, "shown": 100},
    }
    alert_rows = list(document["pools"]["alert"].values())
    assert [row["stars"] for row in alert_rows] == sorted(
        (row["stars"] for row in alert_rows), reverse=True)
    assert len(json.dumps(document, ensure_ascii=False).encode("utf-8")) < 250_000


def test_frontend_prefers_same_day_member_history_projection():
    js = (Path(__file__).parents[1] / "apps" / "web" / "assets" / "app.js").read_text(
        encoding="utf-8")
    merge = js[js.index("function mergeMemberLocalRealtime"):
               js.index("function postJSON")]

    assert "payload.history_pools = local.history_pools" in merge
    assert "payload.history_pool_summary = local.history_pool_summary" in merge

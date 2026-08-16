# V0.3 任务 1：腾讯行情解析测试（TDD）
# 样例来自真实抓取 qt.gtimg.cn/q=sh600000,sz000001（2026-08-14 收盘）
# fixture: tests/fixtures/tencent_quotes_sample.txt（两行，每行 88 字段 ~ 分隔）
import os

from services.collector.quote_collector import (
    normalize_tencent_code,
    parse_quote_line,
    parse_quote_response,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "tencent_quotes_sample.txt")
LINES = open(FIXTURE, encoding="utf-8").read().strip().split("\n")
SH600000, SZ000001 = LINES[0], LINES[1]


def test_normalize_tencent_code():
    # 腾讯 6 位代码 → stock_id（市场前缀）
    assert normalize_tencent_code("600000") == "SH600000"
    assert normalize_tencent_code("000001") == "SZ000001"
    assert normalize_tencent_code("300487") == "SZ300487"
    assert normalize_tencent_code("688001") == "SH688001"
    assert normalize_tencent_code("830799") == "BJ830799"
    assert normalize_tencent_code("920083") == "BJ920083"


def test_parse_quote_line_required_fields():
    q = parse_quote_line(SH600000)
    assert q["stock_id"] == "SH600000"
    assert q["code"] == "600000"
    assert q["name"] == "浦发银行"
    # 核心价格
    assert q["price"] == 9.10
    assert q["preclose"] == 9.18
    assert q["open"] == 9.14
    assert q["high"] == 9.17
    assert q["low"] == 9.06
    assert q["change"] == -0.08
    assert q["change_pct"] == -0.87
    # 涨停检测关键字段（DATA_MODEL §9.12）
    assert q["limit_up"] == 10.10
    assert q["limit_down"] == 8.26
    assert q["vol_ratio"] == 0.81
    # 量/额/换手/市值
    assert q["volume"] == 436231          # 手
    assert q["amount"] == 397586127       # 元（[35] 拆分第三段）
    assert q["turnover"] == 0.13          # %
    assert q["mktcap"] == 3030.83         # 总市值（亿）
    assert q["timestamp"] == "20260814161455"


def test_parse_quote_line_sz():
    q = parse_quote_line(SZ000001)
    assert q["stock_id"] == "SZ000001"
    assert q["name"] == "平安银行"
    assert q["price"] == 11.11
    assert q["limit_up"] == 12.38
    assert q["limit_down"] == 10.13
    assert q["vol_ratio"] == 1.09


def test_parse_quote_response_multi():
    quotes = parse_quote_response("\n".join(LINES) + "\n")
    assert set(quotes) == {"SH600000", "SZ000001"}
    assert quotes["SH600000"]["name"] == "浦发银行"
    assert quotes["SZ000001"]["name"] == "平安银行"


def test_parse_quote_line_bad_line():
    # 非 v_xxx="..." 行 → 跳过（不抛异常）
    assert parse_quote_line("") is None
    assert parse_quote_line("this is garbage;") is None


def test_parse_quote_line_missing_limit_up():
    # 涨停价字段为 0（新股/停牌）→ 保留 0，交由 limit_detect 规则兜底
    parts = SH600000.split("~")
    parts[47], parts[48], parts[49] = "0", "0", "0"
    q = parse_quote_line("~".join(parts))
    assert q["limit_up"] == 0
    assert q["limit_down"] == 0
    assert q["vol_ratio"] == 0

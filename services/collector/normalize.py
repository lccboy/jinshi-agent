# -*- coding: utf-8 -*-
"""数据清洗纯函数（V0.1a 任务 2）

规则依据：`docs/DATA_MODEL.md` §7——stock_id 统一（规则 1）、涨停原因 4 源合并（规则 6）、来源可追溯（规则 7）。
"""
import re

SOURCE_PRIORITY = ["kpl", "jygs", "ths", "xgb"]


def clean_ps_artifact(text):
    """解析 PowerShell 序列化残留 `@{k=v; k=v}` → dict（防御性兼容）。

    真实数据（kpl_*_limitup_multi.json）的 `sources` 为嵌套 JSON 对象，原样透传；
    若某次生成脚本以 PS 字符串形态落盘，此处兜底解析，保证 sources 原文可追溯。
    """
    if not isinstance(text, str):
        return text
    if not text.startswith("@{"):
        return {"_raw": text}
    body = text[2:-1]
    out = {}
    for part in re.split(r";\s*(?=\w+=)", body):
        if "=" in part:
            key, value = part.split("=", 1)
            out[key.strip()] = value.strip()
    return out


def stock_id(code):
    """6 位代码 → `市场前缀 + 代码`（SH/SZ/BJ），全系统唯一 join 键。"""
    code = str(code).strip().zfill(6)
    if code.startswith(("60", "68")):
        return "SH" + code
    if code.startswith(("00", "30")):
        return "SZ" + code
    return "BJ" + code


def sector_type(sector_id):
    """板块类型：行业板块（8019/803/880 前缀）→ industry，其余 → concept。"""
    sid = str(sector_id)
    return "industry" if sid.startswith(("8019", "803", "880")) else "concept"


def _source_has_reason(entry):
    if not isinstance(entry, dict):
        entry = clean_ps_artifact(entry)
    return bool(entry and str(entry.get("reason", "")).strip())


def merge_limitup_sources(sources):
    """涨停原因 4 源合并。

    - `primary` 按优先级 `kpl > jygs > ths > xgb` 裁决，主源缺失自动降级到下一个有值的源
    - `sources` 保留各源原文（清洗后的 dict，含 `source` 标识）
    - `sourceCount` 为实际命中（有 reason）的源数，≤4
    """
    entries = {}
    for key in SOURCE_PRIORITY:
        raw = (sources or {}).get(key)
        if raw is None:
            continue
        entry = clean_ps_artifact(raw) if isinstance(raw, str) else raw
        if _source_has_reason(entry):
            entries[key] = entry
    if not entries:
        return None
    primary = next((k for k in SOURCE_PRIORITY if k in entries), SOURCE_PRIORITY[0])
    p = entries[primary]
    return {
        "reason": str(p.get("reason", "")),
        "detail": str(p.get("detail", "")),
        "name": str(p.get("name", "")),
        "boards": str(p.get("boards", "")),
        "primary": primary,
        "sourceCount": len(entries),
        "sources": entries,
    }


def normalize_limitup_multi(data):
    """`limitup_multi` 文件 → `facts/<date>/limitup.json`（按 stock_id 键控）。

    - 顶层兼容 `{"reasons": {...}}` 或直接 `{code: {...}}`
    - 每只票：各源清洗（PS 字符串 → dict）+ 4 源合并
    - `concepts` 取主源、拆为数组（兼容 、 和 ，分隔）
    """
    reasons = data.get("reasons", data) if isinstance(data, dict) else {}
    out = {}
    for code, entry in reasons.items():
        if not isinstance(entry, dict):
            continue
        merged = merge_limitup_sources(entry.get("sources"))
        if merged is None:
            continue
        primary_entry = merged["sources"][merged["primary"]]
        concepts = str(primary_entry.get("concepts", "") or "")
        out[stock_id(code)] = {
            "reason": merged["reason"],
            "detail": merged["detail"],
            "boards": merged["boards"],
            "concepts": [c.strip() for c in re.split(r"[、,，]", concepts) if c.strip()],
            "first_time": entry.get("first_time", ""),
            "seal_amount": entry.get("seal_amount", 0),
            "primary": merged["primary"],
            "sourceCount": merged["sourceCount"],
            "sources": merged["sources"],
        }
    return out

# 策略修复：十全十美启用 + 金量买入配置参数生效

> 日期：2026-08-17 | 来源：用户策略审查

## 背景

1. **⑦ 十全十美（perfect_ten）**：配置 `min_conditions=11` 但代码仅 7 条件（无 L2 数据），永不命中（今日命中 0 只，实证）。用户选 A：降级为 7 启用，用现有 OHLCV 条件跑起来。
2. **⑧ 金量买入（golden_vol）**：`config/strategy.json` 的 `window`/`vol_mult` 参数**未传入策略引擎**（`m_golden_vol` 调用 `golden_vol_hit` 时用硬编码默认值 3/1.2）。当前值恰好等于默认值所以无感，但前端改配置保存后重跑不生效。需让配置真正生效（**不动公式口径**，红线 §2 不可改）。

## 任务

1. `config/strategy.json`：`perfect_ten.params.min_conditions` 11 → 7，更新 note
2. `services/collector/strategy_models.py`：`m_golden_vol(bars, ctx)` 读取 `ctx["window"]`/`ctx["vol_mult"]` 传给 `golden_vol_hit`（缺省回落默认值）
3. `services/collector/strategy_engine.py`：为 `golden_vol` 构建 ctx 参数（与 perfect_ten min_conditions 同模式）

## 测试（TDD）

- `test_perfect_ten_hit_with_min7`：7 条件全满足 → 命中（min_conditions=7）
- `test_golden_vol_ctx_vol_mult_blocks`：ctx `vol_mult=3.0`（末根仅 1.25 倍量）→ 不命中；无 ctx → 用默认 1.2 命中
- `test_golden_vol_ctx_window`：ctx `window=1`（只比 1 日）→ 命中行为随窗口变化
- 全量回归：`pytest tests/ -v`

## 步骤

1. 红灯：新增 3 个失败测试
2. 最小实现：config + strategy_models + strategy_engine
3. 绿灯：新增测试通过
4. 全量回归：197+ 现有测试全绿
5. 真实样本：重跑 strategy_engine（今日数据）验证 golden_vol 命中与 perfect_ten 开始命中
6. commit（中文规范）

# 调度韧性修复：失败升级告警 + 守护热更新

> 日期：2026-08-17 | 来源：D1 信任审计重大发现

## 背景（为什么做）

08-17 15:20 归档首跑失败后，旧版调度器（18c428b，无 attempt_count 上限、无冷却、15:20 即启动 archive）每 30s 盲重试 **592 次、耗时 4.8 小时**，直到 20:21 外部恢复才 `recovered`。新代码（106dac9，20:23）已修：15:30 启动 + 要求 postmarket success + attempt_count≥3 上限 + 5 分钟冷却——**但守护进程未重启，旧代码仍在运行**。

**两个待办**：
1. 重启守护进程，让新逻辑生效（运维动作）
2. **失败升级告警缺失**：attempt_count≥3 后只是"停止重试"，无任何告警——真故障会静默一天（代码缺陷，需 TDD 新增）

## 任务

1. scheduler_daemon.py 新增 `pending_escalations` 纯函数：attempt_count≥3 且 failed 且当日未告警 → 返回需升级阶段
2. 新增 `write_escalation`：写 `data/runs/alerts/<date>_<stage>.json`（幂等，已存在不覆盖）
3. main 循环接入：due_stages 后检查并写告警 + 日志 `[ESCALATE]`
4. 重启守护进程（kill 旧 PID → start-user-daemon.ps1）

## 文件

- `services/collector/scheduler_daemon.py`：+pending_escalations / +write_escalation / +RETRY_LIMIT 常量 / main 接入
- `tests/test_scheduler_daemon.py`：+3 个测试
- `deploy/status.ps1`（可选后续）：读取 alerts/ 展示

## 测试（TDD）

- `test_escalate_when_attempt_limit_reached`：failed + attempt_count=3 → 返回告警条目
- `test_no_escalation_below_limit`：attempt_count=2 → 空
- `test_escalation_idempotent`：alerts 文件已存在 → 不再告警（同 stage 只一次）

## 步骤

1. 红灯：加 3 个测试 → pytest 确认失败
2. 最小实现：纯函数 + main 接入
3. 绿灯：pytest test_scheduler_daemon.py 通过
4. 全量回归：pytest tests/ -v（197+3）
5. 重启守护：kill 33052 → start-user-daemon.ps1 → 心跳确认
6. commit（中文规范）

# 金十Agent 开发流程规范（基于 superpowers 方法论）

> 学习自 `github.com/jnMetaCode/superpowers-zh`（obra/superpowers 中文版）。
> 目的：把"版本规划"变成可执行的开发纪律——每个功能走完整的 头脑风暴 → 规格 → 计划 → TDD → 验证 → 审查 闭环。

## 1. 总体工作流

```text
需求/想法 → brainstorming（头脑风暴：澄清问题，产出规格 spec）
         → writing-plans（实现计划：任务分解，TDD 步骤，存 docs/superpowers/plans/）
         → executing-plans（逐任务执行：红灯→绿灯→重构→commit）
         → verification-before-completion（完成前验证）
         → code review（请求/接收审查）
         → 发布（build.ps1 + deploy.py + git tag）
```

- "让我们构建 X" → 先头脑风暴再写码，**绝不跳过计划直接写代码**
- "修复这个 bug" → 先系统化调试（复现→假设→最小修复→验证）再动手
- 变更必须可追溯：每个 commit 对应计划中的步骤

## 2. 产出物规范

| 阶段 | 产出 | 位置 |
|---|---|---|
| 规格 | 功能规格 spec（需求、边界、验收） | `docs/specs/YYYY-MM-DD-<feature>.md` |
| 计划 | 实现计划（任务+文件+测试+步骤） | `docs/superpowers/plans/YYYY-MM-DD-<feature>.md` |
| 测试 | 与代码同目录 `tests/`（TDD） | `tests/` |
| 记录 | 版本验收记录 | `docs/acceptance/` |

## 3. 计划编写铁律（writing-plans 要点）

1. **任务 = 能独立跑完一轮测试循环、值得独立审查的最小单元**；每个任务以可测试的交付物结束
2. **小步骤**（每步 2-5 分钟）：写失败测试 → 运行确认失败 → 最少实现 → 运行确认通过 → commit
3. **文件结构先行**：任务前先列出"创建/修改哪个文件、职责是什么"，小而专注的文件，按职责拆分
4. **禁止占位符**：计划中不得出现"待定/TODO/后续实现/添加适当错误处理"；代码步骤必须有真实代码块
5. **自检**：写完计划对照规格逐条检查覆盖度、扫描占位符、核对类型/命名一致性

## 4. TDD 铁律

```
没有失败的测试，就不写生产代码
```

- 先写测试 → 看它失败（验证红灯）→ 写最少代码通过（绿灯）→ 重构
- **例外需询问**：一次性原型、生成的代码、纯配置文件
- 本项目适用范围：`normalize`/`limit_detect`/`strategy_engine`/`kline_sync`/`web 聚合` 等核心逻辑
- 数据管线测试不是 mock 表演：用真实样本（`tests/fixtures/` 放剪裁后的真实 JSON 片段）

## 5. 验证清单（verification-before-completion）

任何任务声称"完成"前，必须通过：

- [ ] 计划中所有测试通过（`pytest tests/ -v`）
- [ ] 数据校验通过：行数/字段完整性/与源数据对账（`collector --verify`）
- [ ] 真实数据跑通一次（单日采集→归档→web 视图生成）
- [ ] 浏览器验证页面加载（本机 http://127.0.0.1 或服务器 /DSH/）
- [ ] 性能检查（页面首屏传输量、请求数符合 DATA_MODEL §13 预期）

## 6. git 工作流

- **V0.1a 启动即 `git init`**（当前项目还不是仓库）
- 分支：`main`（稳定）+ `feat/<version>-<feature>`；涉及数据格式变更时用 git worktree 并行
- **频繁 commit**：每个任务一个 commit，小步提交
- 中文提交规范（superpowers-zh `chinese-commit-conventions`）：
  ```
  feat: 新增 master_collector 主数据采集
  fix: 修复 limitup sources 字段 PS 残留清洗
  test: 补充 kline .day 解析单测
  docs: 更新数据模型 §13
  refactor: 抽取 normalize 纯函数
  ```
- 版本发布：`git tag v0.1.0`，与 `DSH.backup.<ts>` 双通道回滚

## 7. 代码审查

- 每个任务完成后**请求审查**（requesting-code-review），重点：口径一致性（⑧公式不可改）、数据模型字段命名、边界情况
- 审查意见用 `<review>` 标记记录在计划任务下，未解决不进入下一任务

## 8. 技能路由（本项目）

| 场景 | 使用 |
|---|---|
| 改数据模型/字段 | 先读 `docs/DATA_MODEL.md`，遵守 §7 规则 |
| 改策略 | 先读 `docs/STRATEGY_MODEL.md`，**⑧金量买入公式口径不可改**（§9） |
| 写计划 | 本节 §3 格式 |
| 写测试 | 本节 §4 TDD |
| 中文提交 | 本节 §6 规范 |

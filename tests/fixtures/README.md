# 测试夹具说明

本目录存放**真实数据裁剪样本**（不用 mock），用于数据管线 TDD：

- `limitup_multi_sample.json` — 从 `H:\projects\kpl\output\kpl_<date>_limitup_multi.json` 裁剪 3 只票
- `600000_5bars.day` — 通达信 vipdoc `.day` 二进制样本（5 根K线，32 字节/根）

裁剪规则：保留字段结构与 PS 残留原文，不得手工美化（否则测不出清洗逻辑）。

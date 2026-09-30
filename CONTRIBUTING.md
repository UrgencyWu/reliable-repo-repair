# Contributing

感谢关注 Reliable Repo Repair。项目基于 Open SWE；请保留上游来源、许可与贡献历史。提交前先阅读 [AGENTS.md](AGENTS.md)，了解异步实现、强类型、提示词、数据库迁移与测试约定。

## 开始开发

1. 从 [README](README.md) 运行本地 Compose 演示。
2. 阅读 [Repair 开发说明](tests/repair/README.md)，配置宿主机 Python 3.14 / uv 和相关 PostgreSQL / Runtime 测试。
3. 前端使用 pnpm workspace；版本以根 `package.json` 的 `packageManager` 为准。
4. 阅读 [数据模型](agent/repair/models.py)、[任务派发](agent/repair/dispatch.py) 和 [独立验证](agent/repair/validation.py) 实现。

保留固定上游基线和锁文件。升级 upstream / Runtime / SDK 时，使用独立变更说明接口变化并验证相关契约。

## 变更与验证

- 尽量围绕一个可观察的问题提交小改动。
- Python 使用异步实现和精确类型；前端使用 TypeScript 强类型。不要用 `Any` / `any` 规避类型错误。
- 新 Repair API 放在 `agent/repair/`；模型指令放在 `agent/resources/prompts/`。
- 数据库迁移使用 `make migration m="Short description"`。
- 只运行与改动相关的测试，**不要本地运行全量测试**。新增测试应保护外部行为，避免只断言常量或内部调用顺序。
- PG / Runtime 集成测试缺少配置时的 skip 不算验收通过。报告实际环境、结果和验证限制。
- `.env*`、session、API key、本地 `.tools/` 产物与运行日志保存在私有本地环境；开发登录 helper 使用本地演示会话。

最小 Python 行为检查示例：

```bash
.venv/bin/pytest tests/repair/test_candidate_patch.py tests/repair/test_state.py -q
.venv/bin/ruff check agent/repair tests/repair
.venv/bin/ty check agent/repair tests/repair
```

数据库、Runtime 与恢复相关改动还需执行对应集成检查，环境和命令见 [Repair 开发说明](tests/repair/README.md) 和 [部署指南](deploy/repair/README.md)。展示页使用静态页面检查，见 [页面维护说明](docs/site/README.md)。

## Issue 与 Pull Request

Bug 报告请包含复现步骤、预期/实际行为、版本与脱敏日志。新功能先说明使用场景和范围，尤其是涉及云 Sandbox、自动 CI 或额外基础设施的变更。

PR 标题使用 Conventional Commits，例如 `fix(repair): reject expired validation results`。描述说明问题与最终行为，遵循仓库约定：**不在 PR 描述中添加测试运行或验证章节**。安全问题按 [SECURITY.md](SECURITY.md) 的私密渠道反馈。

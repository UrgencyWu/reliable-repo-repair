# ADR-007: Python-first Control Plane with native Open SWE integration

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Accepted design; not implemented。替代 [ADR-002](ADR-002-spring-control-plane-python-execution.md)。

## Context

用户确认 Java 不是必须选项，可以使用 Python/Go，并要求不影响任务目标时最大复用。实际基线已有 Python FastAPI、异步 SQLAlchemy/PostgreSQL/Alembic、LangGraph Runtime、鉴权/Repository/React；新增语言会增加 API、部署、事务与恢复边界。

## Decision

采用 Python 模块化应用，在 `agent/repair/` 增量开发业务 control plane、dispatch/adapter/validation，保留原 graph/Runtime 和 feature router 规则。控制 plane 与 execution plane 在职责上分开，不要求不同语言或独立业务服务。Go 不进入 Phase 1，仅在具体性能/部署需求成立时另评估。

## Consequences

复用 auth/数据库/配置/测试设施，减少双服务 callback 和新 dependency project。RepairTask 仍须领域 service、typed DTO、事务、权限和 state machine；原 thread/run 不等于业务 task。保留 Server/SDK 边界，不拼装私有 Runtime，不复制 Agent。deployment 可按资源需要拆进程，但尚无拆分必要证据。

## Validation

实际原 graph harness、POST202 与 PG 任务、durable intent 异步启动、独立 validation、GET/integration。旧 Java 实现和跨语言 callback 未完成且不再列为默认 slice 验收。

相关：[目标架构](../ARCHITECTURE.md)、[Phase 1](../architecture/PHASE_1_PLAN.md)。

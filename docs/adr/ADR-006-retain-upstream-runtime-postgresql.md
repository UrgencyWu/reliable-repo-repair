# ADR-006: Retain internal LangGraph Server and PostgreSQL

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Superseded in part by [ADR-008](ADR-008-reuse-infrastructure-by-capability.md) on 2026-09-28。原 Runtime/PostgreSQL 继续复用；以下双数据库设计为历史，未实现。

## Context

agent/api/app.py lifespan执行database.require_configured/migrate；agent/database/postgres.py只接受PGasyncURI，多feature使用PGschema/queries。factory还依赖get_client、Thread/Store与serverinjected runtime。

## Decision

保留内部LangGraphServer与upstreamPG16；MySQL独占Repair业务数据，不迁移PG表也不拿PG冒充MySQL实践。新增repairruntime配置而不改原langgraph.json；当前根Dockerfile0.13.3与RCconstraints不匹配，待锁定版本实测后决定runtimeimage。

## Consequences

开发部署多一个内部database与serverprocess，但不新增业务微服务；比全量PG→MySQL迁移或拼装私有runtime更小侵入。内部runtime不暴露公网/用户payload；后续去PG依赖必须列调用路径、契约和故障验证后单独ADR。productionServerlicense/可用部署方式另验证。

## Validation

对照APIapp/databasepostgreSQL/runtimeexecution/dispatch源码；Phase1须真实服务启动/harness。rootDockerfile原样保留不是兼容性结论，当前不提供未经验证的production部署命令。

相关：[Upstream审查](../upstream-analysis/OPEN_SWE_ARCHITECTURE.md)、[目标架构](../ARCHITECTURE.md)、[Phase1计划](../architecture/PHASE_1_PLAN.md)。

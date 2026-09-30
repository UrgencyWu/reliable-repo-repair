# ADR-003: Why RabbitMQ instead of synchronous execution

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Superseded by [ADR-008](ADR-008-reuse-infrastructure-by-capability.md) on 2026-09-28。以下为初始 RabbitMQ 方案，未实现；长任务异步原则保留。

## Context

CI修复时长不适合请求连接，进程重启/重复delivery是正常故障；原LangGraph内部queue没有SpringRepairTask事务与业务retry语义。

## Decision

RabbitMQ做业务command投递，MySQLoutbox保证接受task后不会因MQ失败永久失去command。持久queue/message+publisherconfirm，manualack在结果持久化以后。沿用内部LangGraph调度执行graph；业务与模型/tool retry分开。

## Consequences

语义at-least-once，不能承诺exactly-once。consumerclaim与callback去重必需；Phase2加指数退避/预算/DLQ/poison分类，避免nack热循环。publisher与worker抢先执行的QUEUED竞态必须测试。

## Validation

实际MQ投递/confirm/consume/ACK链；DBcommit后发送失败、发送后mark前crash、callback后ACK前crash验证不丢任务且不重复修改终态。

相关：[Upstream审查](../upstream-analysis/OPEN_SWE_ARCHITECTURE.md)、[目标架构](../ARCHITECTURE.md)、[Phase1计划](../architecture/PHASE_1_PLAN.md)。

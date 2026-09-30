# ADR-002: Why Spring Boot Control Plane + Python Execution Plane

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Superseded by [ADR-007](ADR-007-python-first-control-plane.md) on 2026-09-28。以下保留初始 Java/Python 决策历史，未实现。

## Context

任务生命周期/查询/事务/异步可靠性需要强业务边界；upstream Agent与LangGraph为Python。把reasoning迁入Java既破坏复用也增加双份loop。

## Decision

Spring管API/RepairTask/MySQL/outbox/调度/cancel/retry与结果权威。PythonWorker管MQ执行适配/原AgentSDK/工具/Sandbox/验证证据。私有Agent Server保留在Python execution plane；暂不要求直接ainvoke进worker。

## Consequences

三类主要应用组件，Python可两进程。typed JSON contracts/schema version隔离语言边界；Worker不直接写MySQL避免绕过状态机；callback必需auth/attempt guard，迟到事件不能更改终态。

## Validation

Phase1须HTTP202快速返回、消费执行、typedresult回写、GET证据；Java不得包含model调用，Pythonadapter不得复制原factory。

相关：[Upstream审查](../upstream-analysis/OPEN_SWE_ARCHITECTURE.md)、[目标架构](../ARCHITECTURE.md)、[Phase1计划](../architecture/PHASE_1_PLAN.md)。

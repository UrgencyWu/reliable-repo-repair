# ADR-001: Why Open SWE as upstream

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Accepted for source reuse; runtime gate pending。该状态是架构决策状态，不是功能已实现。

## Context

目标是展示Agent Backend工程能力，而非新Agent算法。实际源码已经包含Deep Agents coding loop、LangGraph graph、6个Sandbox provider、GitHub交付/CIwatch、middleware与React基础。

## Decision

完整fork并保留agent/ui/tests/历史/license，使用固定SHA与tag；增量目录接入业务后端。审查快照固定到本次下载的SHA，不自动跟随main。先验证locked install/harness，证明可运行才作为已验收开发基线。

## Consequences

继承成熟工具/运行行为，也继承Python3.14、RCruntime、全局cache与产品耦合。upstream升级不是自动依赖更新，要重新审查与契约测试；禁止复制create_deep_agent成第二份Agent。

## Validation

Phase0静态证据：langgraph.json、agent/graphs/agent.py、agent/server.py、providers/registry.py。Phase1须原graph+deterministic model+fixture通过，不能用mockadapter代替。

相关：[Upstream审查](../upstream-analysis/OPEN_SWE_ARCHITECTURE.md)、[目标架构](../ARCHITECTURE.md)、[Phase1计划](../architecture/PHASE_1_PLAN.md)。

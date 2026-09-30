# 增量文件覆盖表

基线与 SHA256 见 [CHANGE_INVENTORY.json](CHANGE_INVENTORY.json)。共 100 个路径；审查材料本身不计入原增量。

此表记录阅读重点与验证边界，不表示每条分支都已动态测试；无单独发现也不等于证明无缺陷。确认问题与本轮运行命令统一见 [报告](REVIEW_REPORT.md)。

| 路径 | 阅读/检查结论与证据边界 |
|---|---|
| `.dockerignore` | 构建、部署、CI 或忽略规则增量阅读；未执行远程 CI/重新构建。 |
| `.github/workflows/repair-mvp.yml` | 构建、部署、CI 或忽略规则增量阅读；未执行远程 CI/重新构建。 |
| `.gitignore` | 构建、部署、CI 或忽略规则增量阅读；未执行远程 CI/重新构建。 |
| `ATTRIBUTION.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `README.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `agent/api/app.py` | 上游接入 diff 或 Repair prompt 阅读；保留 Runtime，API 不启动 Repair Worker。 |
| `agent/config.py` | 上游接入 diff 或 Repair prompt 阅读；保留 Runtime，API 不启动 Repair Worker。 |
| `agent/database/migrations/versions/0042_9edff2616cd3_repair_tasks_runs_and_durable_dispatch_.py` | 增量表、索引、约束及候选不可变规则；测试 schema 应用迁移。 |
| `agent/database/migrations/versions/0043_7a5b04c6bf56_repair_candidates_and_execution_leases.py` | 增量表、索引、约束及候选不可变规则；测试 schema 应用迁移。 |
| `agent/database/migrations/versions/0044_cded32b2d7d8_independent_repair_validation_evidence.py` | 增量表、索引、约束及候选不可变规则；测试 schema 应用迁移。 |
| `agent/database/migrations/versions/0045_14940cd67eb6_repair_task_deadline_and_runtime_stop_.py` | 增量表、索引、约束及候选不可变规则；测试 schema 应用迁移。 |
| `agent/repair/__init__.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/adapter.py` | 派发、SDK 映射、观察与异常分支；R2。 |
| `agent/repair/api_models.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/config.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/dispatch.py` | 派发、SDK 映射、观察与异常分支；R2。 |
| `agent/repair/dispatch_store.py` | 租约/写回/候选事务阅读与 PG 复现；R1。 |
| `agent/repair/execution_store.py` | 租约/写回/候选事务阅读与 PG 复现；R1。 |
| `agent/repair/models.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/process.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/recovery_store.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/repository.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/routes.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/service.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/state.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/store.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/validation.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/validation_store.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/repair/worker.py` | Repair 边界、状态/权限/配置/进程或持久化实现阅读；结合相关测试，未新增独立发现。 |
| `agent/resources/prompts/repair/task.md.jinja` | 上游接入 diff 或 Repair prompt 阅读；保留 Runtime，API 不启动 Repair Worker。 |
| `agent/resources/recovery_patch.py` | 与上游 diff 及导出实现阅读；显式 repo/base seam，candidate 相关测试。 |
| `compose.repair.yaml` | 构建、部署、CI 或忽略规则增量阅读；未执行远程 CI/重新构建。 |
| `deploy/repair/Dockerfile.backend` | 构建、部署、CI 或忽略规则增量阅读；未执行远程 CI/重新构建。 |
| `deploy/repair/Dockerfile.ui` | 构建、部署、CI 或忽略规则增量阅读；未执行远程 CI/重新构建。 |
| `deploy/repair/README.md` | 构建、部署、CI 或忽略规则增量阅读；未执行远程 CI/重新构建。 |
| `deploy/repair/start-backend.sh` | 构建、部署、CI 或忽略规则增量阅读；未执行远程 CI/重新构建。 |
| `docs/ARCHITECTURE.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/MVP_DEVELOPMENT_PLAN.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/ROADMAP.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-001-why-open-swe-as-upstream.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-002-spring-control-plane-python-execution.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-003-rabbitmq-asynchronous-execution.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-004-backend-state-vs-agent-state.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-005-sandbox-lifecycle-provider-strategy.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-006-retain-upstream-runtime-postgresql.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-007-python-first-control-plane.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-008-reuse-infrastructure-by-capability.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-009-independent-clean-validation.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-010-dispatch-lease-reconciliation.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-011-mvp-core-scope-basic-ui.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-012-reproducible-local-repair-demo.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/ADR-013-standalone-repair-worker.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/adr/README.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/architecture/MVP_ACCEPTANCE.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/architecture/PHASE_1_PLAN.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/architecture/REAL_MODEL_ACCEPTANCE.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/architecture/REPAIR_EXECUTION_CONTRACT.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/upstream-analysis/OPEN_SWE_ARCHITECTURE.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/upstream-analysis/UPSTREAM_README.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/upstream-analysis/VALIDATION.md` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `docs/upstream-analysis/baseline.json` | 职责、阶段边界、历史证据和当前声明一致性核对；历史状态歧义见非阻断观察。 |
| `scripts/repair_acceptance_fixtures.py` | 初始化、演示或合成样本准备路径阅读；样本测试不等于真实模型验收。 |
| `scripts/repair_demo.py` | 初始化、演示或合成样本准备路径阅读；样本测试不等于真实模型验收。 |
| `scripts/repair_init.py` | 初始化、演示或合成样本准备路径阅读；样本测试不等于真实模型验收。 |
| `tests/e2e/fake_llm.py` | deterministic seam、浏览器脚本/配置与断言阅读；本轮未执行浏览器 E2E。 |
| `tests/e2e/playwright.repair.config.ts` | deterministic seam、浏览器脚本/配置与断言阅读；本轮未执行浏览器 E2E。 |
| `tests/e2e/repair-tests/open-demo.mts` | deterministic seam、浏览器脚本/配置与断言阅读；本轮未执行浏览器 E2E。 |
| `tests/e2e/repair-tests/repair.spec.ts` | deterministic seam、浏览器脚本/配置与断言阅读；本轮未执行浏览器 E2E。 |
| `tests/repair/README.md` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/agent_entrypoint.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/langgraph.json` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_acceptance_fixtures.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_adapter_integration.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_api.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_candidate_patch.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_dispatch.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_process.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_recovery.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_runtime_integration.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_state.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_validation.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_validation_store.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/test_worker_crash.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `tests/repair/worker_process.py` | 测试用例及断言/隔离边界阅读；本轮执行子集见报告，未重跑其余 Runtime/SIGKILL 测试。 |
| `ui/server/backend-proxy.test.ts` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/features/agents/components/AgentsSidebar.tsx` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/features/agents/lib/apiWarmup.ts` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/features/agents/terminal/ghostty/surface.test.ts` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/features/repair/RepairTaskDetail.tsx` | 终态、日志/patch 查询及轮询；组件复现 R3。 |
| `ui/src/features/repair/RepairTaskList.tsx` | 创建、分页、幂等与查询；重复提交语义列非阻断观察。 |
| `ui/src/features/repair/RepairTasks.test.tsx` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/features/repair/api.ts` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/lib/appLocation.ts` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/lib/perf/fetchTiming.test.ts` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/lib/perf/fetchTiming.ts` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/routeTree.gen.ts` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/routes/repair.tsx` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/routes/repair/$taskId.tsx` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/src/routes/repair/index.tsx` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |
| `ui/vite.config.ts` | 前端增量/代理/路由/兼容修改阅读；相关 Vitest 子集见报告，未重跑 build。 |

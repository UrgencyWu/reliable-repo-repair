# 项目二相对 Open SWE 增量审查报告

后续状态：本报告保留修复前结论；2026-09-29 R1–R3 已修复并验证，当前状态见 [修复结果](FIX_RESULTS.md)。

日期：2026-09-29。审查对象：当前工作区，包括未提交和未跟踪实现。

固定上游基线：`langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。

## 结论

完成 [审查计划](REVIEW_PLAN.md) 的增量审查与针对性复现。确认 **1 项 P1、2 项 P2**。建议先修复 R1，再处理 R2/R3；本次没有修改业务实现。已有测试通过不能覆盖下列新增复现场景，不宜据此宣称所有过期执行者写回窗口均已验证。

范围清单记录 100 个路径，见 [内容快照](CHANGE_INVENTORY.json) 和 [文件覆盖表](FILE_REVIEW.md)。重点为事务、派发、恢复、独立验证、部署和 UI。未全面审计上游和第三方依赖；未发现其他问题不等于证明不存在缺陷。

## R1 · P1：等待行锁跨过租约到期后，仍允许写回或续租

位置：`agent/repair/dispatch_store.py:80–102,128–153`；`agent/repair/execution_store.py:55–82`。

派发写回及续租在获取行锁前读取数据库时间，随后使用该时间判断 lease/deadline。执行租约虽在 SQL WHERE 使用 `clock_timestamp()`，也没有在等待行锁返回后重新确认租约仍有效。

触发条件：另一个事务持有目标行锁但不修改该行；当前请求在租约有效时开始等待，直到租约实际到期后才能取得锁。此时 `record_dispatch`、`renew_claim` 和 `renew_execution` 均返回成功。执行续租还能将已经过期的租约延长。

影响：违反项目的严格租约过期拒绝契约，使过期执行者仍有机会写入 Runtime reference 或续期。**本轮没有证明新持有者的不同 token 被覆盖，也没有证明产生重复 Agent Run**；token 不匹配的保护与这里的时间窗口是不同问题。

证据：[reproduce_leases.py](reproduce_leases.py) 使用真实 PostgreSQL 行锁、2 秒租约，并等待真实时间跨过到期点，没有修改过期时间伪造结果。三个操作均输出：

```json
{"accepted_after_expiry": true, "waited_past_expiry": true}
```

修复方向：获取相关行锁后，以新的数据库时间复核 token、状态、lease 和 deadline；保持锁顺序一致，并检查共享 `owned_run` 的调用者。仅把预锁定 WHERE 的时间表达式改为 `clock_timestamp()` 不足以解决问题。补充“持锁等待跨过租约/任务到期”的回归测试，与既有“调用前已经过期”测试分开。

## R2 · P2：单条对账异常反复中断调度轮次，阻塞正常任务

位置：`agent/repair/dispatch.py:74–89`；`agent/repair/adapter.py:126–127`。

Adapter 对一个 intent 匹配到多个 Runtime Run 时显式抛出 `ValueError`。对账循环只处理 HTTP/超时异常，该错误直接退出 tick，后面的正常任务领取和执行观察均不运行。外层 run 捕获异常后，下轮仍会处理同一条记录。

触发条件：一条 RECONCILING 记录持续返回重复匹配错误，另有正常 PENDING 任务。直到异常记录不再进入对账集合或外部干预，其他任务可能持续排队并最终到期。

证据：[reproduce_reconciliation.py](reproduce_reconciliation.py) 使用真实 PG task/intent 和原 dispatcher，在 Adapter 边界注入源码定义的重复 metadata 异常。连续两个 tick 输出：

```json
{"tick_failures": 2, "healthy_task_status": "QUEUED", "healthy_dispatch_attempts": 0}
```

这验证了调度异常隔离缺口；未在真实 Runtime 制造两个重复 Run，不据此声称 Runtime 本身会重复创建。

修复方向：对该条 intent 持久化可诊断错误并隔离/限制后续处理，继续其他独立任务。不能仅吞掉错误，也不能把无法确定的 Runtime 创建结果当作安全重试。补充“异常对账记录与正常任务同队列”的测试。

## R3 · P2：TIMEOUT 后停止轮询，遗漏异步停止 Runtime 的结果

位置：`ui/src/features/repair/RepairTaskDetail.tsx:13–16`。

详情页只按 task 是否终态决定停止轮询。后端可以先将任务置为 TIMEOUT、设置 `runtime_stop_pending=true`，随后异步确认 Runtime 已停止，或记录停止失败。这些更新不改变 task 的 TIMEOUT 状态。

触发条件：页面第一次读到 TIMEOUT 时远端停止尚未确认。之后即使后端更新了停止结果，页面仍显示“Runtime stop awaiting confirmation”，直到其他刷新行为发生。“Refresh logs”只刷新 artifacts，不能可靠刷新这一详情字段。

证据：[ReviewFindings.test.tsx](ReviewFindings.test.tsx) 配置后续 detail 响应已清除 pending，推进 16 秒后 detail API 仍只调用一次，页面保留等待提示。该测试复现组件行为，未重新进行真实浏览器超时故障注入。

修复方向：终态且所有 Runtime 停止动作已结束时才停止轮询；增加 pending→confirmed 和 pending→failed 两类回归测试。

## 非阻断观察

- 创建表单成功后，以完全相同输入再次点击仍复用幂等键，返回旧任务。观察性 UI 测试确认该行为；它可能是有意去重，本次不作为确定缺陷。后续明确“重发请求”和“创建新任务”的交互即可，不要求实现延期的公共 retry API。
- `ATTRIBUTION.md` 末段仍称新增内容为 Phase 0 planned；若干契约/ADR 保留“尚未验收”的历史段落，后文才追加完成记录。建议标注历史快照与当前状态，避免读者误读；无需删除原决策历史。

## 本轮验证结果

| 检查 | 实际结果 | 证明范围 |
|---|---|---|
| 相关 Python 测试 | 48 passed，4 subtests passed，19.32s；5 条第三方 warning | state/dispatch/API/candidate/validation/process/fixture preparation，包含真实 PG 测试 |
| 相关 UI 测试 | 7 files / 40 tests passed，2.17s | 38 项既有测试 + 2 项观察性复现；不是 40 项正常行为全部无缺陷 |
| 锁等待复现 | 三类操作均接受过期请求 | R1 的真实 PG 时间窗口 |
| 对账隔离复现 | 两轮错误，正常任务领取次数为 0 | R2，Adapter 异常注入 + 真实 PG |
| Compose 状态读取 | 四服务 running，三个已配置 healthcheck 的服务 healthy | 本轮仅检查存活状态，没有重新 build 或重跑四服务 E2E |
| git diff --check | 通过 | 既有跟踪文件 diff 空白检查 |
| 范围内容核对 | 100 路径与审查前 hash/存在性快照一致 | 业务文件未因审查改变 |

通过的观察性复现断言的是当前问题行为，**不代表问题已修复**。Python 警告涉及 Pydantic V1/Python 3.14 兼容提示和第三方弃用提示，本轮没有将 warning 当作测试失败。

### 复现方式

在仓库根目录、现有 `.venv` 和本地测试 PG 可用时执行。两个 Python probe 固定连接本机 5433 的测试 PostgreSQL，并由原 `isolated_schema` 创建/清理独立测试 schema；不要改成生产数据库。

```sh
PYTHONPATH=. .venv/bin/python docs/reviews/reproduce_leases.py
PYTHONPATH=. .venv/bin/python docs/reviews/reproduce_reconciliation.py
TEST_ANALYTICS_POSTGRES_URI=postgresql://postgres:postgres@127.0.0.1:5433/postgres .venv/bin/pytest tests/repair/test_state.py tests/repair/test_dispatch.py tests/repair/test_validation_store.py tests/repair/test_api.py tests/repair/test_validation.py tests/repair/test_candidate_patch.py tests/repair/test_process.py tests/repair/test_acceptance_fixtures.py -q
```

UI probe 因使用现有模块的相对导入，需临时复制到 `ui/src/features/repair/ReviewFindings.test.tsx`（确认没有同名文件），用项目固定 Node/pnpm 工具链运行下面的测试后删除该临时副本；本轮已清理。

```sh
pnpm --dir ui exec vitest run src/features/repair/ReviewFindings.test.tsx src/features/repair/RepairTasks.test.tsx src/lib/perf/fetchTiming.test.ts src/features/agents/lib/apiWarmup.test.ts src/features/agents/terminal/ghostty/surface.test.ts server/backend-proxy.test.ts src/lib/appLocation.test.ts
```

本地原始输出保存在 `.tools/review-lease-probe.log`、`.tools/review-reconciliation-probe.log`、`.tools/review-focused-tests.log`、`.tools/review-ui-tests.log`。`.tools` 被忽略，报告保留了关键结果与可复现材料，不要求分发本机缓存。

## 复用边界与未验证事项

源码仍调用原 Open SWE/LangGraph API；新增 Repair 业务持久化、派发/观察、独立验证和 UI，没有复制 Agent loop。API 与独立 Worker 分离，PostgreSQL 继续承担 durable dispatch。候选不可变存储及独立 checkout 的验证边界在本轮相关测试中得到覆盖，但不等于强安全隔离或任意仓库正确性证明。

本轮没有重新执行历史三类 SIGKILL/真实 Runtime/浏览器全链验收，不把历史的 58 项或 Worker 故障结果合并进本轮计数。没有真实模型调用、成功率测量、生产环境压测、完整 Runtime 崩溃恢复验证、云 Sandbox 安全审计或查询性能实验。synthetic fixture preparation 不是真实模型修复验收。CI webhook、公共取消/retry、SSE、Redis/MQ/Kubernetes 仍不属于本次范围。

审查已经完成；R1–R3 保持未修复状态。下一步应在单独的修复工作中增加失败回归、修改实现、再运行对应测试与相关恢复链验证，而不是扩展功能范围。

# Repair Task、派发、恢复与独立验证契约

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

状态：**设计契约，M0–M7 可信本地范围已完成验收**。详细证据见 [ROADMAP](../ROADMAP.md) 和 [验收对照](MVP_ACCEPTANCE.md)。项目定位：**Reliable Repo Repair Agent Backend — 基于 Open SWE 的代码仓库修复 Agent 后端与可靠执行系统**。当前支持手动 Repo Repair，CI ingestion 完成后再宣称 CI 自动修复。沿用 Python/FastAPI/PostgreSQL/原 Runtime，核心贡献是下面五个模块；后续完整恢复/云能力不在本版结论内。

当前范围由用户确认的 [MVP-001 v1.0](../MVP_DEVELOPMENT_PLAN.md) 固定。本文的 CI 幂等、公共取消、自动新 RepairRun、完整 checkpoint/cloud resume、SSE/metrics 等仅为后续契约；本版实现 F01–F08，基本 UI 通过 REST 轮询。

## 1. RepairTask / RepairRun 数据与身份

| 对象 | 最小字段与约束 |
|---|---|
| RepairTask | task_id、owner/workspace/repository reference 或 fixture identity、target_commit_sha、immutable input/validation plan、status、deadline、created/updated、version |
| RepairRun | repair_run_id、task_id、attempt_no、thread_id、runtime_run_id、agent_sandbox_id、phase/checkpoint reference、开始/结束、failure classification；unique(task_id, attempt_no) |
| DispatchIntent | dispatch_id、repair_run_id、status、attempt_count、next_retry_at、claimed_by、claimed_at、lease_expires_at、lease_token、last_error；一个 initial intent 对应一个 business run |
| CandidateArtifact | artifact_id、repair_run_id、base_commit_sha、patch_sha256、patch storage reference、files changed、created_at；生成后不可变 |
| ValidationResult | validation_id、repair_run_id、candidate_artifact_id、validator workspace/provider/id、environment manifest、baseline/test/regression exit/output、PASS/FAIL/ERROR、duration |
| RepairEvent | event_id、task_id、repair_run_id、sequence、event、occurred_at、typed payload；unique(task_id, sequence)、event_id 去重 |

`repair_run_id` 是本项目执行记录，`runtime_run_id` 是 LangGraph Run，`thread_id` 是 Agent 状态身份，不能都叫含糊的 run_id。已有 Agent trace 保存 messages/tools；Repair 数据保存业务事实和引用。resume 如产生新 Runtime run，记录历史关联，不无痕覆盖旧 run；精确 SDK 语义待验证。

请求幂等按 owner/workspace + Idempotency-Key 唯一，并比较 payload hash；同 key 不同输入返回 409。CI 业务幂等按 workspace/repository + workflow_run_id + run_attempt + commit_sha，区分 GitHub rerun；delivery_id 另作事件去重。同一失败事件不重复创建 task，手动对相同 commit 的不同修复任务仍允许存在。

创建 RepairTask、首个 RepairRun、DispatchIntent 和初始 Event 在同一 PG 事务提交，POST 返回 202。Task 业务状态采用 [目标架构](../ARCHITECTURE.md) 的严格状态机；intent 的 CLAIMED/DISPATCHED 与 Runtime node/status 都不直接作为 task status。Phase 1 保留最小可观察 phase，细粒度诊断事件后加。

## 2. DispatchIntent claim 与派发

| intent 状态 | 含义 | 允许的下一状态 |
|---|---|---|
| PENDING | 尚未尝试或已确认可以安全重试，next_retry_at 到期可认领 | CLAIMED |
| CLAIMED | 已持久化 owner/token/lease，可能正在创建 Runtime Run | DISPATCHED、RECONCILING、PENDING、FAILED |
| RECONCILING | 调用结果未知或 lease 过期，先查明既有 Run | DISPATCHED；证明无运行/无在途创建才可 PENDING；人工确认不可恢复才 FAILED |
| DISPATCHED | 已关联 Runtime run；终止派发，不代表任务成功 | 不回退；后续 observe/recovery 管运行 |
| FAILED | 确定不可派发或安全重试预算耗尽 | 不回退；task 失败原因/历史保留 |

多实例 dispatcher 用 `SELECT ... FOR UPDATE SKIP LOCKED` 在短事务中选 PENDING、校验 deadline/任务状态、设置 claim/lease/token 并提交。索引按 status/next_retry_at 的实际扫描验证。advisory lock 不是必须同时使用的第二套锁；已有 PG 能解决时不增加 Redis。

SDK 调用发生在事务外。lease 使用 DB 时间、续租和条件更新；旧 token 不得写 reference/event/result。Phase 1 就需最小 lease 与 stale claim 分支，Phase 2 扩展故障矩阵。**DB fencing 只能拒绝旧数据库写入，不能自动取消旧 SDK 请求或阻止 Sandbox 副作用。**

正常返回：当前 token 写 runtime reference、intent DISPATCHED 与业务 event。确定未创建的 transient failure：attempt_count 增加，有限指数退避+jitter，PENDING + next_retry_at。永久输入/auth/config 错误：FAILED。连接中断、timeout、进程 crash/lease 过期：RECONCILING，不因 lease 到期直接当作安全重试。

派发前已有持久化 thread_id/dispatch_id，并在 Runtime metadata 关联业务身份；adapter 优先按已知 run id/对应 thread 查询。客户端指定 run id、查找完整性、冲突和创建请求的在途窗口都待 Gate 1 契约验证。一次查询“未找到”不自动证明创建从未发生。无法确认时保留 RECONCILING、failure reason 和可观察事件，进入受控恢复；不宣称 exactly-once 或完全自动恢复。

dispatch attempt_count 是派发重试次数，RepairRun attempt_no 是新的代码修复尝试，二者独立。普通观察网络错误不重新生成 patch；Runtime 内工具 retry 不消耗 business repair attempt。

## 3. Open SWE Adapter 与 Recovery

adapter 承担 validated task → Agent input/config → thread/run 关联 → Sandbox references →事件观察 →候选 patch/result。真实 Agent 仍由 `agent/server.py` 和原 graph 执行，不复制 loop、不透传内部配置、不依赖 LLM 自报告推进终态。

| 重启后实际观察 | 处理 |
|---|---|
| PENDING intent | 安全 claim 后派发 |
| stale CLAIMED / unknown create | 转 RECONCILING，核对原 thread/run；不立即创建第二个 |
| Runtime Run active | 恢复 observer，保留原 thread/workspace，不重复 generation |
| Runtime ended、candidate 已持久化 | 恢复 Validator；不再次调用 Agent |
| checkpoint 可恢复、原 Sandbox 在 | 按已验证 SDK 契约 resume，同 attempt 历史保留 |
| Sandbox unreachable | 保留原 id，等待有限恢复窗口，不 force checkout |
| Sandbox deleted、candidate 已持久化 | 从 candidate 在新 Validator workspace 验证 |
| Sandbox deleted、candidate 未保存 | 标 workspace loss；仅有 snapshot/artifact 才恢复，否则明确失败/新业务尝试 |
| Validator crash | 新 clean workspace 重做相同 candidate 验证，保留旧 validation attempt；不重启 Agent |
| 旧 owner 迟到结果 / task 已终态 | 拒绝非法更新，记录可追踪的 stale result |

本版只实现必要的总 deadline/执行 timeout 与 failure 记录；公共取消接口延后。后续取消与总 deadline 经业务 service；持久化意图后分别停止新派发、请求 Runtime cancel、验证远程进程停止。取消 Runtime 不等于杀掉所有 shell 进程。原 sandbox retention 不在 artifact 收集前盲目回收。

## 4. Independent Validator

generation 与 verification 共享原 Provider abstraction，**不共享可变工作区**。Phase 1 是独立本地 checkout，云模式可创建另一个 provider sandbox。记录 agent_sandbox_id 与 validator_sandbox_id/workspace_id；本地目录隔离不等于安全隔离，是否独立 filesystem/provider root 需实测。

验证计划由 task/config 固定，Agent 无权把测试命令、预算或通过标准改成自报 PASS。Phase 1 fixture 用固定外部断言避免靠修改测试让其通过；真实 repo 的测试/构建路径与可修改文件规则在 Phase 3 明确定义。PASS 表示配置的验证计划通过，不表示任意缺陷都被证明不存在。

执行顺序：

1. Agent generation 结束，收集候选 patch 到不可变 artifact：显式 repo path、精确 target SHA、patch hash、覆盖 committed/staged/unstaged/new-file 变化；未支持的变更形式显式失败，不静默丢文件。
2. 创建 clean Validator workspace，checkout target SHA；确认 initial tree 干净、commit 一致，使用记录的工具链/环境/依赖方案，绝不从 Agent 目录复制已修改文件或可变依赖环境。
3. 在 base 运行目标测试证明本次失败可复现；本身通过则记录 NOT_REPRODUCED，不把后续通过标为“修复成功”。环境/依赖建立失败为 ERROR。
4. 校验候选 hash/base SHA，做 patch apply check 并应用；应用失败记 FAIL/patch_apply，不能改用 Agent 当前目录的结果。
5. 运行固定 target tests 与配置的 regression checks，记录每项 exit code、timeout、输出 artifact、开始/结束和环境 manifest。模型不参与 PASS 判定。
6. 全部必需 checks 通过且证据完整 → PASS → task COMPLETED/WAITING_REVIEW；测试断言失败 → FAIL；执行基础设施故障 → ERROR。三者分别分类，不把网络失败当代码修复失败。

生成器与验证器可处于同一个 Python 应用，但 Validator 不调用模型。Phase 1 FAIL/ERROR 明确回写失败；Phase 2 对已保存 candidate 的 transient ERROR 重试验证，Phase 3 可在有限 budget 下把 FAIL 反馈为新的 RepairRun，保留前一 candidate/result。终态人工 retry 创建 linked 新 task，终态不回退。

源码复用点：原 [recovery_patch.py](../../agent/resources/recovery_patch.py) 已处理 binary/full-index 和普通 untracked files，但使用分支 merge-base/fallback、扫描 repo，不保证 task 的精确 commit/path；原 [diffs.py](../../agent/threads/diffs.py) 有提取与 download 路径。拟增加 optional explicit repo/base seam 或提取共用 helper，默认 dashboard 行为保留；Repair 模式严格使用显式 SHA、禁止 fallback。submodule/symlink 等覆盖与可重放性为 UNKNOWN，按 Phase 1 支持范围验证。

## 5. Observability、事件与验收

日志/event 全链统一 trace_id、repair_task_id、repair_run_id、runtime_run_id、thread_id；agent_sandbox_id 与 validator_sandbox_id 分开记录，未创建字段为 null。静态日志 message + extra，记录 phase/event/latency/error_type/retry_count。事务内 RepairEvent 是权威 timeline；stream/transcript 仅补充 Agent trace。

基础 duration/dispatch latency/provision/tool/validation/retry/failure reason 从第一版记录；Phase 4 再接 Prometheus/Grafana。SSE 后续按 event sequence replay 和 task ownership 授权。Runtime trace 自动透传是否完整为 UNKNOWN，须契约测试；id 不作高基数 metric labels。

验收至少覆盖：并发 claim、重复 intent/创建结果未知/lease expiry、restart observe、candidate 后 crash、dirty Agent workspace 对验证无影响、wrong base/hash/apply failure、baseline 未失败、真实 test failure、Validator crash/timeout、旧 token 迟到、terminal guard。真实 graph + deterministic model 在同一链操作 fixture，mock adapter 不替代。已验证的基础范围包括 exact-base replay、原 graph shell 工具、PG task 创建/API/并发幂等/回滚、claim/lease/token/有限 backoff；完整 Observer/Validator/restart recovery 尚未验收，详见 [验证记录](../upstream-analysis/VALIDATION.md)。

相关：[ADR-009](../adr/ADR-009-independent-clean-validation.md)、[ADR-010](../adr/ADR-010-dispatch-lease-reconciliation.md)、[Phase 1 文件计划](PHASE_1_PLAN.md)。

# ADR-010: PostgreSQL Dispatch Intent lease and reconciliation

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Accepted; 常驻 dispatcher、双实例与真实 Runtime 响应丢失后的对账已验证。细化 ADR-008，不引入默认 RabbitMQ/Redis。M5 的完整截止时间与恢复分类仍待验收。

## Context

task 和 intent 同事务只能覆盖接受请求后尚未派发的 crash。SDK 已创建 run、业务尚未写 reference，以及旧 dispatcher lease 到期时仍在请求中，都不能靠重置 PENDING 安全恢复。

## Decision

intent 采用 PENDING/CLAIMED/RECONCILING/DISPATCHED/FAILED，持久化 attempt_count/next_retry_at/claimed_by/claimed_at/lease_expires_at/token。短 PG transaction 用 SKIP LOCKED claim，SDK 调用在事务外；条件更新/renew 拒绝旧 token。

timeout/lease expiry/未知创建结果先进入 RECONCILING 核对原 thread/run；只有已确认安全的失败才有限 backoff 重试。Runtime 查询/指定 run id/在途创建窗口未验证，不能把一次 not-found 当未创建证明；无法确定时保留可观察未决状态。Phase 1 包含最小 lease/reconciliation；Phase 2 完善完整故障矩阵。

## Consequences

不宣称 exactly-once。DB fencing 不自动 fence Sandbox/SDK 副作用，不能单凭互斥锁保证不启动两个外部 Run。明确区分派发 retry、验证 retry、新 RepairRun，避免双重重试。task/attempt/event/结果仍由业务 service 事务推进。

## Validation

并发 claim、SDK success 后落库前 crash、lease expiry/旧请求在途、旧 token 迟到、metadata correlation、resume/query 契约、安全 backoff/exhausted。日志贯穿 repair_run_id/runtime_run_id/thread_id/sandbox identities。

2026-09-28：SDK 0.4.5 的 `runs.create` 无调用方 run id 参数；thread create 支持预设 id，真实 `runs.list` 能按业务 metadata 找到原 run。采用预存 thread 与 metadata 关联，不改原 Agent factory。数据库测试已覆盖并发 claim、续租/旧 token、stale lease→RECONCILING、unknown create 不重试、safe backoff/exhausted、deadline；常驻 dispatcher 与真实创建结果未知的恢复实验仍待接入。

同日实施更新：原 FastAPI lifespan 启停常驻 dispatcher，默认关闭，显式 `REPAIR_ENABLED=true` 开启；服务外调用依旧走原 SDK。两 dispatcher 并发生成一个 Run/候选；实际 Run 创建成功后注入响应丢失，替换 worker 按 metadata 找回原 Run，无重复创建。API 提交后未启动 worker 的持久 intent，在后续 lifespan 启动后自动处理。观察/收集另用 RepairRun execution lease/token，迟到 owner 被拒绝；不是用 dispatch lease 代替整个执行期锁。

相关：[执行契约](../architecture/REPAIR_EXECUTION_CONTRACT.md)、[目标架构](../ARCHITECTURE.md)。

## M5 deadline/stop intent — 2026-09-28

migration 0045 在 RepairRun 保存 runtime_stop_pending/error。DB-time sweeper 锁顺序 intent → run → task，活跃任务 deadline 到期即 TIMEOUT、清空 claim/execution token、结束 RUNNING validation（保留已存证据），持久化 Runtime stop intent。派发/验证还受整个 task 剩余预算约束；owned_run 同时检查 task phase/deadline，旧 owner 即使尚未被 sweep 也不能续租或写回。

恢复 worker 先处理 deadline/stop，再对账/派发。已知 Run 请求 SDK interrupt 并观察 terminal；cancel 请求成功本身不是停止证明。未知 Run 仅按预存 metadata 查询，不补发。停止/对账窗口在 deadline 后最多 60 秒：仍未知或不可达时结束自动尝试，保存 runtime_creation_unresolved_after_deadline/runtime_stop_unconfirmed，API 可见；不声称远程执行已停止或 exactly-once。终态不会因后续外部成功退回 COMPLETED。异常需要人工检查原 Runtime；公共 cancel/retry 仍延后。

实际 PG fence/保留日志与真实原 Runtime active→interrupted 测试通过；Runtime history 仅一个 Run。未知创建、missing thread 经真实查询后给出有界 unresolved 结果，attempt_count 仍 1。OS 级 worker kill/restart、其余不可恢复分类尚待完整验收。本地 SDK interrupt 不等于清理原 Agent shell 的所有派生进程。

## M5 process recovery evidence — 2026-09-28

新增 test-only 独立 worker harness，连接原 PG 的隔离迁移 schema 和原 Runtime；实际 OS SIGKILL 三个窗口：已启动 pending/running Run 后、Validator 正在执行固定命令时、远程 runs.create 成功但业务 Runtime ID 尚未落库时。新进程等待真实 DB lease expiry，重接同一个 Run 或同一个 candidate；没有修改时间戳来模拟本组租约到期，也没有第二次 generation。原 Run history 仅一条，候选身份/hash 不变，Validator 保留 old ERROR/new PASS。

Runtime 404 和 workspace loss 有明确失败分类：runtime_missing / agent_workspace_lost；已保存候选后即使原 workspace 丢失，仍在独立目录验证完成，不重建 Agent workspace。派发 attempt/status、queue wait、WORKSPACE_READY 与 RUNTIME_STARTED/RECONCILED 的引用/耗时持久化并可查询，不虚构 model reasoning phase。

M5 最小范围完成，证据见 VALIDATION。可信 local execution 下 SIGKILL 无法运行 Python finally，可能留下临时 Validator 目录和在途子进程；测试命令短时退出，测试清理自己遗留的目录。本次恢复验收不证明原 Agent 任意后台 shell 进程已回收，也不证明云 Sandbox/checkpoint 的完整恢复，后者仍延期。

## 2026-09-29 增量审查修复

审查 R1 证明：即便 WHERE 使用数据库时间，在等待行锁前求值也不能阻止等待期间租约过期。派发写入统一 intent→run→task，执行写入统一 run→task，取得这些锁后再读数据库时间复核 token/status/lease/deadline。共享执行入口覆盖候选与验证写入，避免复核后才等待 task 锁。claim/reconcile 写回也刷新锁后的 deadline 时间。数据库 fencing 仍不等于取消外部副作用。

审查 R2：重复 metadata 等 ValueError 对账冲突仅影响该 intent。保存 last_error，保持 RECONCILING，使用既有 next_retry_at 延后 30 秒再检查，继续正常领取/观察；不转为 PENDING、不增加 generation attempt。任务原 deadline 继续限制未决状态。日志记录业务关联 ID；数据库故障不伪装成已成功隔离。

真实 PG 锁等待、异常记录与正常记录同队列的回归及原恢复链结果见 [修复结果](../reviews/FIX_RESULTS.md)。这两项补充纠正之前测试未覆盖的窗口，不改变历史测试曾通过的事实。

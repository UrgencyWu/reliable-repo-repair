# ADR-009: Generation and independent clean validation

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。日期：2026-09-28。

## Status

Accepted; exact-base exporter、真实 graph 与正式独立 Validator/结果持久化已验证（可信本地 fixture 范围）。细化 ADR-004/005，采用用户提出的 clean-base → apply candidate →固定验证计划。

## Context

Agent workspace 可能有未导出的文件、可变依赖环境和测试修改。直接在同一目录重跑命令，不能证明返回的 patch 可独立重放。源码中的 recovery patch 已能收集多类 diff，但默认 base 是分支 merge-base/fallback，不是 task 精确 SHA。

## Decision

generation 结束先保存带 explicit base SHA/repo path/hash 的不可变 candidate。Validator 使用新 clean checkout/可选独立 provider sandbox，复现 base failure、apply candidate、执行固定 target/regression checks。Agent 不能决定 PASS。记录 PASS/FAIL/ERROR 和独立 workspace/环境/日志，只有 PASS 能推动完成。

复用原 registry/protocol/patch collection/download；如新增 explicit base/path seam，默认 dashboard 行为保持。Phase 1 使用可信 fixture 与外部固定断言，无新 Agent loop/LLM 验证器。patch 类型覆盖须实测，不声称所有 binary/symlink/submodule 已支持。

## Consequences

增加 checkout/validation 成本，但证明 artifact 可重放。Validator restart 重做同一 candidate 而不重新 generation；FAIL 与 infrastructure ERROR 使用不同 budget/恢复策略。Local checkout/Docker 不宣称强安全 Sandbox，环境独立程度需实验。

## Validation

真实 graph 产生 patch，在 dirty/残留 Agent workspace 下仍由 clean Validator fail-base/pass-patch；wrong SHA/hash、apply failure、新文件、缺失 artifact、baseline pass、测试失败、timeout/Validator crash。mock PASS 或 Agent 测试输出不能替代。

2026-09-28：复用原 exporter，增加 optional `repo_path/base_commit` 严格模式和 hash；6 个测试验证 exact-base committed/staged/unstaged/new-file/binary 重放及默认导出兼容。额外真实 SDK/graph smoke 在干净 checkout 证明 base fail→apply→pass。M4 的受控固定断言、验证结果入库与故障恢复尚未实现，不能以 smoke 代替 Validator 验收。

后续 M4–M6 已完成正式 clean Validator：独立 fresh checkout、base failure、candidate hash/base/file policy、固定 target/regression、完整检查结果/环境/输出入 PG；只允许完整独立 PASS 转 COMPLETED。原 graph integration、迟到 token、验证接管和真实 SIGKILL 测试通过，浏览器展示同一持久候选与 PASS 证据。完整云 Sandbox/不可信仓库/工具链环境等价仍不在这些本地证据范围内。详细实际结果见 [VALIDATION](../upstream-analysis/VALIDATION.md)。

同日 M3 更新：真实 dispatcher/adapter 在原 graph 结束后收集候选，事务保存 base/hash/bytea/文件清单并转 VALIDATING。共享 PG 存储最大 5 MiB 的小候选，不增加独立 Artifact 平台；DB trigger 禁止 UPDATE/DELETE，hash/大小/固定文件策略在写入前检查。symlink/submodule 在 MVP 明确拒绝，不再静默当作已支持。实际候选已在另一个 clean checkout 重放通过，但 M4 的正式 Validator/PASS 判定仍待接入。

相关：[执行契约](../architecture/REPAIR_EXECUTION_CONTRACT.md)、[Phase 1](../architecture/PHASE_1_PLAN.md)。

## M4 implementation evidence — 2026-09-28

新增 `agent/repair/validation.py` 与 `validation_store.py`、migration 0044。每个验证 attempt 使用独立 UUID clean checkout，精确 base SHA；执行顺序为 BASELINE → PATCH_CHECK → PATCH_APPLY → TARGET →配置的 REGRESSION。固定命令来自创建任务时持久化的服务配置，Agent 无法变更。保存每步 argv、exit、输出/截断、timeout、duration 与 base/hash/Python/platform 环境 manifest；只有完整证据的 PASS 在同一事务保存结果并转 COMPLETED。FAIL/ERROR 转 FAILED，保留分类。

验证中断的接管使用执行租约 token：旧 worker 的 checkpoint/finish 被拒绝；新 attempt 复用同一不可变 candidate，旧 RUNNING 标 validation_owner_lost；最多三个 attempt，耗尽明确失败。测试覆盖的是租约接管及事务证据，完整进程重启、总 deadline 和残留目录处理由 M5 继续验收。未引入额外云 Provider、容器强隔离或自动重新生成 patch。

实际测试包含 clean checkout 忽略 dirty source、wrong base/hash、apply/file-policy failure、baseline 已通过、target/regression failure、命令缺失、timeout 部分输出与清理、已有目录保护、缺失/伪造验证证据拒绝及有界接管。真实 API/双 dispatcher/原 graph 测试已推进至 COMPLETED，Runtime history 仍仅一个 Run，独立证据为 base exit 1、apply/target/regression exit 0。结果查询与 UI 在 M5/M6 提供，不将落库算成页面已完成。

M5 查询增量：验证原始证据仍存 PG，详情只读摘要；artifact 响应总日志上限 64 KiB，报告 stored bytes/读取截断，不返回 validator workspace。patch 从不可变 bytes 返回，SHA ETag 可与 candidate metadata 对照。所有查询复用原 session/ownership；有界日志不是完整 ToolCall/Artifact 平台，也不是监控专项。

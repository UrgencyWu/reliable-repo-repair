# R1–R3 修复计划

日期：2026-09-29。依据 REVIEW_REPORT.md；上游基线 ad545353e2cdb4c7ae1c419f966c82436b63e799。

## 范围

只修复确认的三个问题及直接关联的同类写入路径，不实现非阻断 UX 建议或延期功能，不重写 Agent、不调用真实模型。保留审查报告作为修复前证据。

## 实施顺序与验收

1. R1：新增真实 PG 行锁等待跨过 lease/deadline 的失败测试。派发操作统一按 intent→run→task 获取锁后读取数据库时间，复核 token/status/lease/deadline；执行操作按 run→task 获取锁后复核。检查 candidate/validation 共用入口，避免在复核后再等待 task 锁。已有错误 token、终态、恢复与验证测试必须继续通过。
2. R2：补充一条异常对账记录与正常任务共存的测试。将 ValueError 对账冲突保存在 intent，保持 RECONCILING 并延后再次检查；正常领取继续执行，不转为安全创建重试。使用既有 next_retry_at，不新增表或组件。
3. R3：补充 TIMEOUT 下 pending→确认及 pending→失败的组件回归。远端停止仍 pending 时继续轮询，停止处理结束后再停止轮询。
4. 运行相关 Python/PG、UI、格式检查及必要恢复测试，检查本次 diff，更新 ROADMAP/相关 ADR 和修复结果。只报告本轮真实结果。

## 文件边界

- agent/repair/dispatch_store.py、execution_store.py、dispatch.py
- tests/repair/test_review_regressions.py
- ui/src/features/repair/RepairTaskDetail.tsx、RepairTasks.test.tsx
- docs/reviews/FIX_PLAN.md、FIX_RESULTS.md；docs/ROADMAP.md；ADR-010/011

## 状态

已完成：先验证回归失败，再修复并通过相关检查。补跑真实 Runtime 后 13 项恢复/Adapter 测试无 skip，含三个 SIGKILL 场景。详细证据及首轮跳过原因见 [FIX_RESULTS.md](FIX_RESULTS.md)。

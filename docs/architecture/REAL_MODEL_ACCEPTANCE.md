# R2 小规模真实模型验收

Upstream baseline: `langchain-ai/open-swe@ad545353e2cdb4c7ae1c419f966c82436b63e799`。

状态：**2026-09-30 已完成用户授权本地 8100 模型的小规模验收**。13 个合成任务通过原固定验证，事后补充契约检查 11 个通过、2 个失败；见 [完整结果与失败案例](REAL_MODEL_ACCEPTANCE_RESULTS.md)。没有付费供应商账单或资源成本数据。确定性模型的既有测试不作为真实模型效果证据。

针对两个覆盖缺口的独立复测，以及两个真实开源包历史问题的受控复现，见 [后续实验](REAL_MODEL_FOLLOWUP_RESULTS.md)；这些新任务不改写首轮分母。

## 前置条件

本轮用户已明确授权使用本地端口 8100，服务报告 `qwen3.8-27b`；直接按该授权执行，无需另行索取付费供应商凭据。沿用上游 `LLM_MODEL_ID` 与原 model builder，仅允许显式配置 `OPENAI_BASE_URL` 时使用自定义默认模型 ID。私有会话与数据库凭据不进入 Git、HTTP 任务正文、截图或公开报告。真实验收必须加载 `agent.graphs.agent:traced_agent`，不能使用 `tests/repair/agent_entrypoint.py` 的 scripted model seam。

先运行一个已授权的小 fixture 验证配置、Runtime、模型调用与独立验证链，记录真实用量；本轮随后执行冻结单文件组剩余 9 项，再另行冻结 3 个多文件任务。不能将同一 arithmetic fixture 的重复执行当作不同修复任务。样本需包含完整固定SHA、真实可复现失败、固定target/regression及文件策略，先冻结样本清单，再运行；失败任务仍计入结果，不能只展示成功样本。若后续改用付费供应商，再按实际授权确认供应商费用限额；本地 Token 回执不等于已获得资源成本。

## 执行边界

真实验收独立于 CI/pytest 和当前无费用演示环境，保留 deterministic 服务可运行。复用四服务/Repair API/可靠派发/原Agent/独立Validator，采用独立部署项目、数据卷与session，避免把真实模型和fake结果混在同一实验数据中。

任务deadline和模型调用timeout控制执行时间，不等于供应商费用硬上限。请求中断也不能证明远端立即停止计费。付费供应商验收需结合账户限额及逐任务用量检查；预算无法确认时停止后续付费任务，不声称已实现自动准确计费。本轮使用已授权本地模型，用量据真实回执记录、费用 UNKNOWN。

## 每项记录

sample_id、repo/base_commit、task_id、repair_run_id、thread_id/runtime_run_id、模型标识、执行起止时间、candidate是否产生及hash、baseline是否复现、target/regression结果、最终业务状态及失败原因。

tool calls和token usage只从实际Runtime消息/供应商返回证据提取；缺失标记UNKNOWN，不填0。费用来自实际账单/用量与当时价格，需写明计量来源，不能用测试耗时或估算token伪造成本。输出脱敏记录和汇总，保留失败与部分执行。

## 验收报告

计划样本数、实际开始/完成数、Candidate produced数、baseline reproduced数、Independent Validation PASS数、失败分类、真实耗时、可用用量/费用及UNKNOWN项。仅对冻结样本和指定模型报告结果，不推广为CI仓库通用成功率，不宣称生产部署或强隔离Sandbox。

## 当前证据

无费用样本准备工具：`scripts/repair_acceptance_fixtures.py`，生成10个不同的合成小仓库：addition、clamp、mean、median、stable-unique、slug、chunks、inclusive-range、none-default、capped-backoff。逐个运行基准target，要求真实assertion failure而非import/setup error；应用参考patch后验证target与regression通过，最后还原干净失败base并记录40位SHA、参考patch hash、fixtures hash。

2026-09-28本机实际准备通过，结果在ignored `.tools/real-model-preparation-02/manifest.json`。这是fixture有效性检查，不是Agent生成补丁或真实模型效果；合成小函数不代表真实项目/SWE-bench。准备使用占位owner UUID，没有提交RepairTask。正式部署需在独立共享工作卷内重新生成，并指定实际授权用户，不能直接使用宿主机绝对路径和占位owner。

准备示例（输出目录必须不存在，保留已有证据）：

```bash
python -m scripts.repair_acceptance_fixtures --output /data/acceptance/samples --owner-id <实际用户UUID>
```

不保存参考patch内容在样本仓库。这个约束不等于Local Provider对恶意模型的安全隔离：生成工具源码含已知参考实现，不能宣称盲测或泄漏防护。每个样本只开放subject.py修改权限，测试来自固定fixture配置。

R1独立Worker已通过四服务/双Worker/浏览器与相关恢复测试，见 [ADR-013](../adr/ADR-013-standalone-repair-worker.md)。R2 已通过真实本地模型完成 10 个单文件与 3 个两文件任务；独立固定检查 13/13 PASS，事后补充检查 11/13 PASS，两个契约缺口均保留候选与失败日志。耗时中位数 23.202 秒、累计主 Agent Token 1,110,734；这些数据仅属于本轮顺序执行合成样本，不是通用修复成功率或容量。完整证据见 [结果报告](REAL_MODEL_ACCEPTANCE_RESULTS.md)。

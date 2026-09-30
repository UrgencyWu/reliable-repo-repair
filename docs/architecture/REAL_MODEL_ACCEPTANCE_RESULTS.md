# R2 真实模型验收结果：13 个合成修复任务

执行日期：2026-09-29 23:59 至 2026-09-30 00:08（Asia/Shanghai）。

结论：用户授权的本地 8100 模型已经走通 Repair API → 独立 Worker → 原 Open SWE Agent → 候选导出 → clean Validator。13 个不同任务均复现原始失败、产出候选并通过冻结的 target/regression；随后对全部候选做补充契约检查，11 个通过、2 个失败。**固定测试通过不等于修复语义完整正确。**

本轮结果支持“具备真实模型执行与独立验证的本地闭环”，不能支持“真实仓库修复成功率 100%”。补充检查在观察候选之后制定，属于事后探索性审查，不是预注册盲测；11/13 也不能作为泛化成功率。

## 环境与执行方式

- 模型服务：宿主机 `http://127.0.0.1:8100/v1`；容器使用 `http://host.docker.internal:8100/v1`。`/v1/models` 和实际消息回执均报告 `qwen3.8-27b`；服务自报 vLLM。这里只确认服务返回的标识，没有独立验证模型权重。
- 原 builder：`openai:qwen3.8-27b`，reasoning effort `none`，Responses API；没有使用 scripted/fake model seam。fallback 也指向同一授权本地模型，关闭 LangSmith gateway/tracing。
- Graph：`agent.graphs.agent:traced_agent`。真实模型执行读文件、运行测试、编辑文件等工具；没有给模型注入参考补丁。
- 独立 Compose 项目：`open-swe-repair-real-20260929`，独立 PostgreSQL、共享工作卷、Runtime 数据及 session。原确定性演示环境继续保留。新 API `2036`，页面 `3016`，postgres/backend/dashboard healthy，独立 Worker running；没有为 Worker 宣称业务 healthcheck。
- Python 3.14.7 / Linux aarch64，trusted Local Provider；这不是不可信代码的强隔离环境。
- 配置 task timeout 600 秒、validation timeout 60 秒、观测等待 720 秒；13 项按序执行。时间限制不是供应商计费硬上限。本轮没有压测或恢复故障注入，也没有重新执行浏览器验收。

上游模型目录原先拒绝自托管模型 ID。为本次接入，只在显式设置 `OPENAI_BASE_URL` 时允许合法的自定义 `openai:` 默认模型，继续拒绝无模型名、非法 effort、deprecated/non-default 选项；原 model builder 未改。

## 样本与固定验证

第一阶段先冻结 10 个单文件样本，先执行 addition 接入检查，随后执行其余 9 个；第二阶段单独冻结 3 个多文件样本。第二阶段是明确新增的样本组，不将第一阶段重复运行计作新样本。各 manifest 包含不同 base SHA、准备阶段真实 assertion failure、参考补丁 target/regression 通过记录；提交前保存请求与幂等键，续跑跳过已有结果。

模型提交候选后，后端在独立干净 checkout 按任务创建时保存的固定命令验证：BASELINE exit 1 → PATCH_CHECK/PATCH_APPLY exit 0 → TARGET/REGRESSION exit 0。模型不能修改测试；单文件只允许 `subject.py`，多文件只允许对应两个业务文件。13 项均只有一个业务 RepairRun、一个 Runtime Run、一次独立验证记录，下载补丁 SHA-256 与持久化候选一致。

样本是 stdlib 小函数/两模块合成仓库，不是外部真实 issue、复杂依赖工程或 SWE-bench。生成器在系统源码中包含参考实现，因此即使参考补丁没有放入样本仓库，也不构成隔离盲测。原始任务 constraints 为空，需求主要通过可见测试传达；尤其重试政策和倍增语义未充分写成明确契约，这是两个失败案例的实验限制。

## 实测结果

耗时取 Task `created_at` 至 `updated_at` 的业务终态时间，包含排队、Agent、候选收集和独立验证，排除观测端最多约两秒轮询滞后。是本机顺序执行数据，不能解释为纯推理速度或并发容量。

| 样本 | 文件数 | 固定验证 | 补充检查 | 业务耗时（秒） | AI 回合 | 工具调用 | 输入 / 输出 Token |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| addition | 1 | PASS | PASS | 23.771 | 6 | 6 | 67,678 / 537 |
| clamp | 1 | PASS | PASS | 20.721 | 6 | 7 | 68,161 / 614 |
| mean | 1 | PASS | PASS | 21.383 | 6 | 7 | 68,004 / 666 |
| median | 1 | PASS | PASS | 22.961 | 6 | 8 | 68,991 / 764 |
| stable-unique | 1 | PASS | PASS | 25.149 | 6 | 8 | 69,267 / 835 |
| slug | 1 | PASS | PASS | 20.728 | 6 | 7 | 68,486 / 685 |
| chunks | 1 | PASS | PASS | 23.202 | 6 | 8 | 68,776 / 736 |
| inclusive-range | 1 | PASS | PASS | 19.292 | 6 | 6 | 68,051 / 607 |
| none-default | 1 | PASS | PASS | 20.593 | 6 | 7 | 68,526 / 697 |
| capped-backoff | 1 | PASS | FAIL | 39.742 | 13 | 13 | 156,851 / 1,303 |
| pagination-contract | 2 | PASS | PASS | 36.042 | 11 | 13 | 132,868 / 1,246 |
| retry-contract | 2 | PASS | FAIL | 31.830 | 6 | 10 | 71,635 / 1,132 |
| export-contract | 2 | PASS | PASS | 43.503 | 10 | 12 | 122,054 / 1,564 |

开始 / 终态 / 候选产生 / baseline 复现 / 原独立 PASS / patch hash 一致：均为 13/13；没有原流程 FAILED/TIMEOUT，也没有缺失用量的主 Agent 消息。补充检查覆盖全部 13 个原候选，不覆盖或改写原数据库状态。最短 19.292 秒，中位数 **23.202 秒**，最长 43.503 秒，平均 26.840 秒；小样本不报告容量、SLA 或 P95。

用量来自持久化主 Agent AI 消息的真实 `usage_metadata`，序列化后部分位于 `additional_kwargs.usage_metadata`。94 条 AI 消息、112 次工具调用；累计输入 **1,099,348**、输出 **11,386**、总 Token **1,110,734**。累计输入包含各回合重复上下文，不是独立语料大小。未计入后台标题/分支命名以及配置/SDK smoke 调用；因此不是模型服务总用量。未获取账单、GPU 或其他资源成本，费用标为 **UNKNOWN**，不能写成零成本。

## 两个实际失败案例

### capped-backoff：基数 2 掩盖了错误公式

期望契约是 `min(base * 2 ** attempt, cap)`。模型最终写成 `min(base ** (attempt + 1), cap)`。原 target/regression 都使用 `base=2`，两式在这些输入上相等，clean Validator 正确执行了计划并返回 PASS，但计划不足以检验完整契约。

补充检查在新 checkout 应用同一原候选：`base=3, attempt=2, cap=100`，应为 12，实际为 27。参考实现通过相同补充检查。真实轨迹还保留了先写错误公式、测试失败、再修改并使可见测试通过的过程；13 个 AI 回合证明了模型进行了多轮尝试，也展示了对测试样例过拟合。

### retry-contract：可见样例未约束中间轮次与全部 5xx

模型把重试白名单限定为 `{429, 500, 502, 503, 504}`，遗漏参考契约中的 501/599；同时把延迟写成 `min(base * (attempt + 1), cap)`。现有测试只覆盖 attempt 0、1 和已封顶的 9，导致线性延迟也能通过。

补充检查确认 `next_delay(503, 2, 2, 100)` 应为 8，实际为 6；501/599 的策略检查也失败。原始任务没有显式写明完整政策，因此这些差异既反映模型对可见测试的拟合，也反映需求与验证计划表达不完整，不能直接外推为模型普遍无法理解重试策略。

### 处理与下一步

原 PASS、候选、Runtime 轨迹和测试日志均保留；没有人工修好模型候选后替换成绩，也没有将追加检查包装成原业务 Validator 已拒绝候选。补充检查在执行前另存 plan，使用不同 checkout，并验证 base/reference/candidate；它在补丁审查后制定，明确作为探索性证据。

接下来优先给新一轮任务写清业务契约，在运行前冻结跨参数、未封顶轮次和边界状态码检查；采用新实验版本与新任务，保留本轮分母。然后补少量来自真实开源仓库、带依赖与多文件上下文的固定 issue。现有结果不要求先引入新中间件、微服务或多 Agent 架构。

## 可核查证据与复跑

[脱敏逐项数据、候选身份、固定验证完整日志与用量](evidence/real-model-20260929/summary.json)；[10 项准备记录](evidence/real-model-20260929/single-file-preparation.json)；[3 项准备记录](evidence/real-model-20260929/multi-file-preparation.json)；[补充契约 plan](evidence/real-model-20260929/supplementary-plan.json)。候选在同目录 `patches/`，两个补充失败日志在 `failures/`。

本机原始证据 `.tools/real-model-20260929/`（Git ignored）：独立 Compose override、private.env/session、两阶段 manifests、`results/` / `results-multi/` 的完整 Runtime state/history、请求、API 回执与 patch，以及 `audit/` 的 base/reference/candidate 日志。凭据文件权限 600；公开证据不包含 cookie、JWT 或数据库密码。

本机已有环境续跑命令（已有结果直接读取，不发起新模型任务）：

```bash
PYTHONPATH=. .venv/bin/python -m scripts.repair_real_model_acceptance \
  --api-url http://127.0.0.1:2036 \
  --session .tools/real-model-20260929/session.json \
  --manifest .tools/real-model-20260929/manifest.json \
  --output .tools/real-model-20260929/results --limit 10
```

第二阶段改为 `manifest-multi.json`、`results-multi`、`--limit 3`。全新实验要新建独立输出/仓库及实际 owner，先验证基准失败与参考修复、冻结 manifest，再提交任务；不覆盖本轮证据。

`scripts/repair_acceptance_audit.py` 无模型调用，只复查已有候选；调用时在拥有 fixture 源仓库的容器内指定 `--fixtures`、`--evidence`、新 `--output`。它拒绝覆盖输出，并确认参考实现通过补充契约，避免将错误 oracle 当作候选失败。

本次相关验证：62 项 tests passed，5 条既有依赖兼容/弃用 warnings；包括既有模型 fallback 47 项、自托管默认模型 8 项、用量 2 项、审查正确/过拟合候选 2 项、样本准备完整性 3 项。新增工具与测试 Ruff / ty 通过。没有运行全量测试；这些工程 tests 不与 13 个真实修复任务混算。

后续单独实验：补齐两个契约并验证两件 Requests 历史 issue，见 [复测结果](REAL_MODEL_FOLLOWUP_RESULTS.md)。本报告的原始 13 项记录与分母保持不变。

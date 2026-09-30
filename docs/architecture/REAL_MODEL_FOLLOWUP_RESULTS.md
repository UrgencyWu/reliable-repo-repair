# 真实模型复测与 Requests 历史问题验证

执行日期：2026-09-30（Asia/Shanghai）。本次回应[首轮 13 项实验](REAL_MODEL_ACCEPTANCE_RESULTS.md)发现的两个契约覆盖缺口，并进一步检验原 Agent 能否处理真实开源包中的可复现历史问题。两类任务分开统计：**2 个补强后的合成任务**和 **2 个 Requests 历史 issue 复现任务**，各自固定验证均通过。结果仅证明这些特定任务在当前环境下通过，不能外推为真实仓库修复成功率。

## 两个契约缺口的重新验证

新任务的 ID、Git base、需求文本、target/regression 和允许修改文件在提交前重新冻结，与首轮两个错误候选分开保存。`capped-backoff-v2` 明确倍率始终为 2，固定测试覆盖基数 1/2/3/5、不同轮次和封顶值；`retry-contract-v2` 明确仅 429 与全部 500–599 可重试，延迟为 `min(base * 2 ** attempt, cap)`，固定测试覆盖 501/599、未封顶轮次和多个基数。生成器先证明原始失败是 assertion failure、参考修复通过、仓库还原干净；模型随后在新任务中从失败 base 自主执行。

| 新任务 | 文件数 | 原独立验证 | 业务耗时 | 主 Agent Token | 结果解释 |
| --- | ---: | --- | ---: | ---: | --- |
| capped-backoff-v2 | 1 | PASS | 26.442 秒 | 83,272 | 候选实现 `base * 2 ** attempt`，新契约测试通过 |
| retry-contract-v2 | 2 | PASS | 27.158 秒 | 72,555 | 候选覆盖完整状态码范围与倍增延迟，新契约测试通过 |

两个新任务各有一个业务 RepairRun、一个 Runtime Run、一次独立验证，下载补丁哈希与候选一致。**首轮的 2 个失败补丁仍算首轮失败**；新结果没有替换首轮 13/13 固定 PASS、11/13 事后契约 PASS 的原始记录，也不是简单重跑相同测试后的“成功率提高”估计。明确需求、扩大测试范围和再次采样同时改变了实验条件，无法单独归因模型进步。

## 两个真实开源包问题

来源是 Requests 官方历史 [issue #7432](https://github.com/psf/requests/issues/7432) 和 [issue #6295](https://github.com/psf/requests/issues/6295)。第一项取 [v2.34.0](https://github.com/psf/requests/releases/tag/v2.34.0) 包源码；第二项取 v2.33.1 包源码。由于本机 Git 无法连接 GitHub，源码通过已连接的 GitHub 文件接口逐文件获取，并逐一核对 release tag 的 Git blob SHA；归档的 source manifest 记录 upstream tag commit、每个文件的 blob SHA 和 Apache-2.0 LICENSE。随后在本地为每个提取出的包创建新的 Git base，加入独立离线复现测试，先证明 base 失败、已知修正版本或参考顺序修复通过。

这是**官方包源码提取 + 本地复现仓库**，并非完整上游 Git checkout；新增的测试与 ISSUE.md 也不属于上游 tag。两项 issue 已公开关闭，环境中还装有较新的 Requests，第二项任务说明引用了修复 PR。因此本轮不是解法不可见的盲测或对当前未解决 issue 的贡献，也没有在上游仓库提交 PR。

| 来源与故障 | 固定验证 | 额外离线检查 | 业务耗时 | 主 Agent Token |
| --- | --- | --- | ---: | ---: |
| [#7432](https://github.com/psf/requests/issues/7432)：v2.34.0 把委托 `__iter__` 的文件包装器误判为表单，307 上传失败 | PASS；在内存 307 adapter 下两次读取同一正文 | PASS；308 与非零初始文件偏移 | 62.717 秒 | 267,021 |
| [#6295](https://github.com/psf/requests/issues/6295)：v2.33.1 重定向历史出现自引用 | PASS；两次重定向后历史无环 | PASS；四次重定向后顺序与无环性 | 38.700 秒 | 196,341 |

两个问题都由真实包源码触发；测试中的 adapter 在内存中返回响应，不会访问 `example.invalid` 或外部服务。模型只被允许改 `src/requests/models.py` 或 `src/requests/sessions.py`，分别生成了一处流识别条件修复、一处历史赋值顺序修复。干净 checkout 中 BASELINE exit 1、PATCH_CHECK / PATCH_APPLY / TARGET / REGRESSION exit 0，业务状态 COMPLETED，下载 SHA 一致，各一个业务 Run 与 Runtime Run。

针对两个已保存候选，事后补充检查使用独立初始化的 Git 目录重新应用补丁，先校验原始失败、已知修正实现通过，再验证候选。两项额外检查均通过。它们在看过原候选后制定，因此是探索性审查，不是冻结计划的一部分；也不能代替上游完整测试矩阵、真实网络服务或用户环境中的依赖兼容性。首次本地补充脚本误把未初始化目录交给 `git apply`，未真正改变候选文件；该尝试作废。修正后在隔离 Git 目录应用补丁，并检查目标源码字节确实变化，使用新的审查输出目录记录上述结果。

## 用量、证据与后续边界

本轮四项累计主 Agent **613,856 输入 / 5,333 输出 / 619,189 总 Token**，41 条 AI 消息、48 次工具调用。用量来自实际 Runtime 回执，排除后台标题/分支命名和接入 smoke；不是本地服务总用量。费用与 GPU 成本仍为 UNKNOWN。业务耗时包含派发、模型执行和独立验证，四项顺序执行，不报告并发容量或 P95。

[四项逐任务结果、验证完整日志与候选哈希](evidence/real-model-followup-20260930/summary.json)；同目录保存新合成样本及两个 issue 的准备 manifest、两份 upstream source manifest、四份候选补丁、补充检查 plan/结果/日志。原始 Runtime state/history 和完整请求仍保存在 Git ignored `.tools/real-model-20260929/`。报告与公开证据不含登录 cookie 或本地数据库密码。

工程侧的下一步应是以固定依赖环境和预先冻结的业务约束扩展少量异质 issue，再引入更接近真实项目的构建、测试选择与环境失败分类。当前结果主要支撑后台任务控制、真实 Agent 接入与独立验证的面试讨论；无需据此扩展 Java 服务或新增中间件。

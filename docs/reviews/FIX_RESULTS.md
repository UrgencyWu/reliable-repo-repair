# R1–R3 修复结果

后续部署状态：同日已完成镜像重建与两个浏览器验收，当前容器已更新，见 [部署验收](DEPLOYMENT_ACCEPTANCE.md)。下文“本轮”指此前源码修复轮次。

日期：2026-09-29。上游基线：ad545353e2cdb4c7ae1c419f966c82436b63e799。

依据 [修复计划](FIX_PLAN.md) 完成三个确认问题。原 [审查报告](REVIEW_REPORT.md) 与复现材料保留为修复前证据；观察性 probe 不属于修复后验收测试。

## 实际改动

| 问题 | 修复 | 验收 |
|---|---|---|
| R1 过期租约跨锁等待 | 派发共有入口锁 intent→run→task，执行共有入口锁 run→task，然后读取数据库当前时间检查 token/status/lease/deadline；写回、续期、workspace/failure、candidate/validation 使用这些入口；领取/对账刷新锁后时间 | 新增 10 个租约测试覆盖两种持锁位置与五种操作，另有 task deadline 跨锁测试；既有 token/验证/恢复链通过 |
| R2 对账异常阻塞 | 对 ValueError 冲突记录 last_error，保持 RECONCILING，next_retry_at 延后 30 秒；单条异常不终止正常领取，不盲目重启 Agent | 新增真实 PG + Adapter 冲突注入测试：正常任务被领取；第二轮不再次查询冲突记录；原 intent attempt_count 不增加 |
| R3 TIMEOUT 停止结果不更新 | task 终态且没有 runtime_stop_pending 才停止轮询 | 新增 pending→confirmed / pending→error 两项组件测试；读到最终结果后停止轮询 |

R2 的退避只控制对账，不会转换为新的生成尝试。未决任务仍受原总 deadline 管理；没有新增公共 retry、取消接口或数据迁移。R1 的 DB fencing 不承诺停止外部 shell/SDK 副作用。

## 测试过程与结果

先加入回归，再修改业务实现：旧实现下 Python 12 项新回归失败（其中原来不等待任务锁的操作由等待探测超时暴露），UI 2 项新回归失败、4 项既有测试通过。最初沙箱禁止本机数据库连接造成 setup error；获得工具执行权限后才得到上述真实失败结果，未将环境错误当作缺陷证据。

| 检查 | 结果 |
|---|---|
| 新回归 + dispatch + validation_store + recovery + worker_crash，未配置 Runtime 的首轮 | 24 passed、8 skipped，49.39s；跳过原因是缺少真实 Runtime/worktree 配置 |
| 启动当前源码的确定性 Runtime 后，recovery + worker_crash + adapter_integration | **13 passed，无 skip**，99.65s；补齐上一轮全部 Runtime 跳过项，含 3 类真实 SIGKILL |
| 对账退避断言补强后的单项复验 | 1 passed，0.81s |
| RepairTasks UI | **6 passed**，909ms：4 既有 + 2 新增 |
| Python Ruff lint/format（变更文件） | 通过 |
| Python ty（变更实现及新增测试） | 通过 |
| UI tsc --noEmit | 通过 |
| git diff --check | 通过 |

两轮 Python 有重复用例，不将 24+13+1 当作独立测试总数。第三方 Pydantic V1/Python 3.14 和弃用提示仍有 5 条 warning，未新增规避逻辑。仓库没有安装 prettier，尝试未成功；前端按现有风格整理，未声称 Prettier 检查通过。类型检查早期发现新测试数据库时间需要 narrowing，补充 datetime 类型断言后通过。

## 复跑

仓库根目录，沿用 tests/repair/README.md 的依赖与测试 PG。使用隔离 schema，不写业务数据。

```sh
TEST_ANALYTICS_POSTGRES_URI=postgresql://postgres:postgres@127.0.0.1:5433/postgres .venv/bin/pytest tests/repair/test_review_regressions.py tests/repair/test_dispatch.py tests/repair/test_validation_store.py -q
```

真实 Runtime 测试使用本轮临时 localhost:2035、`.tools/repair-fix-runtime`，按照 tests/repair/README.md 启动原 test-only LangGraph 入口（脚本模型），然后执行：

```sh
TEST_ANALYTICS_POSTGRES_URI=postgresql://postgres:postgres@127.0.0.1:5433/postgres REPAIR_TEST_RUNTIME_URL=http://127.0.0.1:2035 OPEN_SWE_LOCAL_WORKTREES_DIR="$PWD/.tools/repair-fix-runtime/worktrees" .venv/bin/pytest tests/repair/test_recovery.py tests/repair/test_worker_crash.py tests/repair/test_adapter_integration.py -q
pnpm --dir ui exec vitest run src/features/repair/RepairTasks.test.tsx
pnpm --dir ui run typecheck
```

本机证据：`.tools/fix-red-python.log`、`fix-red-ui.log`、`fix-green-python.log`、`fix-green-ui.log`、`fix-runtime-tests.log`、`fix-reconcile-final.log`。这些是忽略的本地输出，本文保存关键结论；不会提交运行缓存或凭据。

## 范围和限制

实现修改为三个 Python 模块、一个 React 组件；新增 Python 回归文件，扩展已有 UI 测试。已对照审查前 SHA256 清单核对业务变更范围，并检查 diff。ROADMAP、ADR-010、ADR-011 已更新。没有修改同步 sources、上游 Agent loop、依赖锁文件或数据库 schema。

本轮未重新构建现有 Compose 镜像、未重跑浏览器 E2E、未调用真实模型、未验证生产环境或强隔离 Sandbox。当前运行的旧 Compose 容器不会自动包含工作区修复；源码和上述临时 Runtime 测试使用的是修复后实现。非阻断表单幂等 UX 与历史归属文字建议未扩大实施。

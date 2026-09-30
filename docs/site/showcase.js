// All panels remain readable when JavaScript is disabled.
document.querySelectorAll("[data-switch-group]").forEach((group) => {
  if (!(group instanceof HTMLElement)) return
  const buttons = Array.from(
    group.querySelectorAll("button[data-panel]")
  ).filter((button) => button instanceof HTMLButtonElement)
  const panels = Array.from(document.querySelectorAll("[data-group]"))
    .filter((panel) => panel instanceof HTMLElement)
    .filter((panel) => panel.dataset.group === group.dataset.switchGroup)

  /** @param {HTMLButtonElement} selected */
  const activate = (selected) => {
    buttons.forEach((button) => {
      button.setAttribute("aria-pressed", String(button === selected))
    })
    panels.forEach((panel) => {
      panel.hidden = panel.id !== selected.dataset.panel
    })
  }

  buttons.forEach((button) => {
    button.addEventListener("click", () => activate(button))
  })
  const initial = buttons.find(
    (button) => button.getAttribute("aria-pressed") === "true"
  )
  if (initial) activate(initial)
})

const copyButton = document.getElementById("copy-command")
const command = document.getElementById("start-command")
const copyStatus = document.getElementById("copy-status")

copyButton?.addEventListener("click", async () => {
  if (!command || !copyStatus) return
  try {
    await navigator.clipboard.writeText(command.textContent ?? "")
    copyStatus.textContent = "命令已复制。已有 .env.repair 时省略第一步。"
  } catch (error) {
    console.warn(
      "Clipboard unavailable; select the command for manual copy.",
      error
    )
    const range = document.createRange()
    range.selectNodeContents(command)
    const selection = window.getSelection()
    selection?.removeAllRanges()
    selection?.addRange(range)
    copyStatus.textContent = "自动复制不可用，已选中命令，请手动复制。"
  }
})

const flow = document.getElementById("repair-flow")
const packet = document.getElementById("flow-packet")
const flowToggle = document.getElementById("flow-toggle")
const flowRestart = document.getElementById("flow-restart")
const flowCount = document.getElementById("flow-count")
const flowTitle = document.getElementById("flow-step-title")
const flowDetail = document.getElementById("flow-step-detail")
const flowPayload = document.getElementById("flow-payload")

const flowSteps = [
  ["submit", "dashboard", "backend", "提交修复任务", "Dashboard 将仓库、精确提交与失败命令交给 Backend。", "任务输入"],
  ["commit", "backend", "postgres", "事务保存", "Task、Run、DispatchIntent 与初始事件在同一事务提交。", "Task + Run + Intent"],
  ["publish", "postgres", "redis", "发布派发意图", "发布器从数据库读取待处理 Intent，只向 Stream 投递 intent_id。", "intent_id"],
  ["deliver", "redis", "worker", "交付消息", "消费组将 intent_id 交给 Repair Worker。", "intent_id"],
  ["claim", "worker", "postgres", "领取执行权", "Worker 按 ID 回数据库取得行锁与带 owner token 的租约。", "租约 + token"],
  ["start", "worker", "runtime", "启动 Agent 执行", "Worker 创建关联业务 Run 的 Runtime Run。", "Runtime Run"],
  ["context", "runtime", "agent", "装载修复上下文", "Agent 接收目标提交、失败命令与工作区上下文。", "修复上下文"],
  ["reason", "agent", "model", "模型判断", "LangGraph 将当前消息与工具结果交给模型决定下一步。", "模型消息"],
  ["tool", "model", "tools", "发起工具调用", "模型选择读取文件、运行命令或修改代码所需的工具。", "工具调用"],
  ["workspace", "tools", "checkout", "操作工作区", "工具在 Agent 工作区读取代码、执行检查并写入改动。", "工作区改动"],
  ["observe", "checkout", "model", "回传工具结果", "文件内容、命令输出与测试结果回到模型上下文。", "工具结果"],
  ["iterate", "model", "agent", "继续迭代", "Agent 根据结果继续模型与工具循环，直到本轮执行结束。", "下一步判断"],
  ["finish", "agent", "runtime", "结束 Runtime Run", "Runtime 保存并返回 Agent 执行状态。", "执行状态"],
  ["candidate", "runtime", "patch", "导出候选补丁", "Worker 相对精确 base commit 导出原始 patch 与 SHA-256。", "候选补丁"],
  ["validate", "patch", "validator", "独立验证", "Worker 在全新 checkout 中复现失败、应用补丁并运行目标与回归命令。", "patch + SHA-256"],
  ["persist", "validator", "postgres", "写回验证结果", "候选、逐项检查和最终状态持久保存到 PostgreSQL。", "验证记录"],
  ["result", "postgres", "backend", "查询结果", "Backend 从数据库读取任务状态、补丁与验证记录。", "状态 + 证据"],
  ["display", "backend", "dashboard", "展示结果", "Dashboard 呈现时间线、只读 diff 和验证日志。", "状态 / diff / logs"],
]

if (flow && packet && flowToggle && flowRestart && flowCount && flowTitle && flowDetail && flowPayload) {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)")
  const duration = 1800
  let index = 0
  let progress = 0
  let lastFrame = 0
  let paused = reducedMotion.matches

  const render = () => {
    const [edgeName, sourceName, targetName, title, detail, payload] = flowSteps[index]
    flow.querySelectorAll(".flow-edge.is-active, .flow-node.is-active").forEach((item) => item.classList.remove("is-active"))
    const edge = flow.querySelector(`[data-edge="${edgeName}"]`)
    const source = flow.querySelector(`[data-node="${sourceName}"]`)
    const target = flow.querySelector(`[data-node="${targetName}"]`)
    edge?.classList.add("is-active")
    source?.classList.add("is-active")
    target?.classList.add("is-active")
    const path = edge?.querySelector("path")
    if (path instanceof SVGPathElement) {
      const point = path.getPointAtLength(path.getTotalLength() * progress)
      packet.setAttribute("visibility", "visible")
      packet.setAttribute("cx", String(point.x))
      packet.setAttribute("cy", String(point.y))
    }
    flowCount.textContent = `${String(index + 1).padStart(2, "0")} / ${flowSteps.length}`
    flowTitle.textContent = title
    flowDetail.textContent = detail
    flowPayload.textContent = payload
  }

  const tick = (now) => {
    if (!paused) {
      if (lastFrame) progress += (now - lastFrame) / duration
      if (progress >= 1) {
        index = (index + 1) % flowSteps.length
        progress %= 1
      }
      render()
    }
    lastFrame = now
    window.requestAnimationFrame(tick)
  }

  flowToggle.addEventListener("click", () => {
    paused = !paused
    flowToggle.textContent = paused ? "播放" : "暂停"
    flowToggle.setAttribute("aria-label", paused ? "播放数据流" : "暂停数据流")
  })
  flowRestart.addEventListener("click", () => {
    index = 0
    progress = 0
    lastFrame = 0
    render()
  })
  reducedMotion.addEventListener("change", (event) => {
    paused = event.matches
    flowToggle.textContent = paused ? "播放" : "暂停"
  })
  flowToggle.textContent = paused ? "播放" : "暂停"
  render()
  window.requestAnimationFrame(tick)
}

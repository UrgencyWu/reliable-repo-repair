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

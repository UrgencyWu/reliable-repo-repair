import { chromium } from "@playwright/test"
import { readFile } from "node:fs/promises"
import { resolve } from "node:path"

const sessionPath =
  process.env.REPAIR_DEMO_SESSION_FILE ??
  resolve("../../.tools/repair-demo/session.json")
const value: unknown = JSON.parse(await readFile(sessionPath, "utf8"))
if (!value || typeof value !== "object") throw new Error("Invalid private demo session")
const sessionObject = value
function field(key: string): string {
  const result: unknown = Reflect.get(sessionObject, key)
  if (typeof result !== "string") throw new Error("Invalid private demo session field")
  return result
}
const url = process.env.REPAIR_UI_URL ?? "http://127.0.0.1:3012"
const browser = await chromium.launch({
  headless: false,
  channel: process.env.REPAIR_BROWSER_CHANNEL,
})
const context = await browser.newContext()
await context.addCookies([
  { name: field("cookie_name"), value: field("cookie_value"), url, httpOnly: true, sameSite: "Lax" },
])
const page = await context.newPage()
await page.goto(`${url}/repair`)
await page.getByLabel("Repository fixture").fill(field("fixture_id"))
await page.getByLabel("Commit SHA").fill(field("target_commit"))
await page.getByLabel("Failing command").fill(field("failing_command"))
await new Promise<void>((resolveClosed) => browser.on("disconnected", () => resolveClosed()))

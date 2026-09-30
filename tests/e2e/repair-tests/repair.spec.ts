import { test, expect } from "@playwright/test";
import { readFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
interface DemoSession {
  cookie_name: string;
  cookie_value: string;
  fixture_id: string;
  target_commit: string;
  failing_command: string;
}

async function compose(args: string[]): Promise<void> {
  await promisify(execFile)(
    "docker",
    [
      "compose",
      "--env-file",
      ".env.repair",
      "-f",
      "compose.repair.yaml",
      ...args,
    ],
    { cwd: resolve(__dirname, "../../.."), timeout: 45000 },
  );
}

test("API queues while worker is stopped and two standalone workers consume once", async ({
  page,
  context,
  baseURL,
}) => {
  test.skip(
    process.env.REPAIR_COMPOSE_ACCEPTANCE !== "1",
    "Requires this project's Compose environment",
  );
  const demo = await session();
  await context.addCookies([
    {
      name: demo.cookie_name,
      value: demo.cookie_value,
      url: baseURL!,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await compose(["stop", "repair-worker"]);
  try {
    const created = await page.request.post("/api/repair-tasks", {
      headers: { Origin: baseURL!, "Idempotency-Key": randomUUID() },
      data: {
        fixture_id: demo.fixture_id,
        target_commit: demo.target_commit,
        failing_command: demo.failing_command,
        constraints: "",
      },
    });
    expect(created.status()).toBe(202);
    const task = (await created.json()) as { id: string };
    const detailUrl = `/api/repair-tasks/${task.id}`;
    await new Promise<void>((done) => setTimeout(done, 1500));
    const queued = await page.request.get(detailUrl);
    expect(queued.status()).toBe(200);
    const queuedTask = (await queued.json()) as { task: { status: string } };
    expect(queuedTask.task.status).toBe("QUEUED");
    await compose([
      "up",
      "-d",
      "--no-build",
      "--scale",
      "repair-worker=2",
      "repair-worker",
    ]);
    await expect
      .poll(
        async () => {
          const response = await page.request.get(detailUrl);
          const detail = (await response.json()) as {
            task: { status: string };
          };
          return detail.task.status;
        },
        { timeout: 30000 },
      )
      .toBe("COMPLETED");
    const completed = (await (await page.request.get(detailUrl)).json()) as {
      runs: { thread_id: string }[];
      candidates: object[];
    };
    expect(completed.runs).toHaveLength(1);
    expect(completed.candidates).toHaveLength(1);
    const history = await page.request.get(
      `${process.env.REPAIR_RUNTIME_URL ?? "http://127.0.0.1:2032"}/threads/${completed.runs[0].thread_id}/runs`,
    );
    expect(history.status()).toBe(200);
    expect(await history.json()).toHaveLength(1);
  } finally {
    await compose([
      "up",
      "-d",
      "--no-build",
      "--scale",
      "repair-worker=1",
      "repair-worker",
    ]);
  }
});

async function session(): Promise<DemoSession> {
  const value: unknown = JSON.parse(
    await readFile(
      process.env.REPAIR_DEMO_SESSION_FILE ??
        resolve(__dirname, "../../../.tools/repair-demo/session.json"),
      "utf8",
    ),
  );
  if (!value || typeof value !== "object")
    throw new Error("Invalid demo session");
  for (const key of [
    "cookie_name",
    "cookie_value",
    "fixture_id",
    "target_commit",
    "failing_command",
  ] as const) {
    if (!(key in value) || typeof Reflect.get(value, key) !== "string")
      throw new Error("Invalid demo session field");
  }
  return value as DemoSession;
}

test("browser creates a task and displays the independently validated original Agent patch", async ({
  page,
  context,
  baseURL,
}) => {
  const demo = await session();
  await context.addCookies([
    {
      name: demo.cookie_name,
      value: demo.cookie_value,
      url: baseURL!,
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  await page.goto("/repair");
  await expect(
    page.getByRole("heading", { name: "Repair Tasks", exact: true }),
  ).toBeVisible();
  await page.getByLabel("Repository fixture").fill(demo.fixture_id);
  await page.getByLabel("Commit SHA").fill(demo.target_commit);
  await page.getByLabel("Failing command").fill(demo.failing_command);
  const accepted = page.waitForResponse(
    (response) =>
      response.url().includes("/api/repair-tasks") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Create task" }).click();
  const posted = await accepted;
  expect(posted.status()).toBe(202);
  const task = (await posted.json()) as { id: string };
  await page.getByRole("link", { name: task.id, exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("COMPLETED", {
    timeout: 30000,
  });
  await page
    .getByRole("button", { name: "Show patch and validation logs" })
    .click();
  await expect(page.getByLabel("Candidate patch")).toContainText(
    "return a + b",
  );
  await expect(
    page.getByRole("heading", { name: "Validation 1: PASS", exact: true }),
  ).toBeVisible();
  const artifactsResponse = await page.request.get(
    `/api/repair-tasks/${task.id}/artifacts`,
  );
  expect(artifactsResponse.ok()).toBeTruthy();
  const artifacts = (await artifactsResponse.json()) as {
    candidate: { sha256: string };
    validations: { status: string; checks: { exit_code: number }[] }[];
  };
  expect(artifacts.validations[0]?.status).toBe("PASS");
  expect(
    artifacts.validations[0]?.checks.map((check) => check.exit_code),
  ).toEqual([1, 0, 0, 0, 0]);
  const patch = await page.request.get(`/api/repair-tasks/${task.id}/patch`);
  expect(
    createHash("sha256")
      .update(await patch.body())
      .digest("hex"),
  ).toBe(artifacts.candidate.sha256);
  const detailResponse = await page.request.get(`/api/repair-tasks/${task.id}`);
  const detail = (await detailResponse.json()) as {
    runs: { thread_id: string }[];
  };
  const runtime = process.env.REPAIR_RUNTIME_URL ?? "http://127.0.0.1:2031";
  const history = await page.request.get(
    `${runtime}/threads/${detail.runs[0]!.thread_id}/runs`,
  );
  expect(((await history.json()) as unknown[]).length).toBe(1);
  const directory = resolve(
    __dirname,
    "../../../.tools/repair-browser-artifacts",
  );
  await mkdir(directory, { recursive: true });
  await page.screenshot({
    path: resolve(directory, "repair-detail.png"),
    fullPage: true,
  });
  await page.getByLabel("Candidate patch").scrollIntoViewIfNeeded();
  await page.screenshot({
    path: resolve(directory, "repair-patch.png"),
    fullPage: true,
  });
  await page
    .getByRole("link", { name: "Back to Repair Tasks", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Repair Tasks", exact: true }),
  ).toBeVisible();
  await expect(
    page
      .locator(`tr:has(a[href="/repair/${task.id}"])`)
      .getByText("COMPLETED", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: resolve(directory, "repair-list.png"),
    fullPage: true,
  });
});

// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import type { ReactNode } from "react"
import { RepairTaskList } from "./RepairTaskList"
import { RepairTaskDetail } from "./RepairTaskDetail"
import { repairApi, type TaskDetail, type RepairTask } from "./api"
vi.mock("./api", () => ({
  REPAIR_POLL_INTERVAL: 4000,
  repairApi: {
    list: vi.fn(),
    detail: vi.fn(),
    create: vi.fn(),
    artifacts: vi.fn(),
    patch: vi.fn(),
  },
  isTerminal: (status: string) =>
    ["COMPLETED", "FAILED", "TIMEOUT"].includes(status),
}))
vi.mock("@tanstack/react-router", () => ({
  Link: ({ children }: { children: ReactNode }) => <a>{children}</a>,
}))
const task: RepairTask = {
  id: "task-1",
  trace_id: "trace-1",
  fixture_id: "arithmetic",
  target_commit: "a".repeat(40),
  failing_command: "python3 -m unittest",
  constraints: "",
  status: "QUEUED",
  failure_reason: null,
  created_at: "2026-09-28T01:00:00Z",
  updated_at: "2026-09-28T01:00:00Z",
  deadline_at: "2026-09-28T01:05:00Z",
}
function mount(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  vi.useRealTimers()
})

describe("repair tasks", () => {
  it("shows an empty list and submits the configured repository with a stable retry key", async () => {
    vi.mocked(repairApi.list).mockResolvedValue({
      items: [],
      limit: 20,
      offset: 0,
      has_more: false,
    })
    vi.mocked(repairApi.create)
      .mockRejectedValueOnce(new Error("Network unavailable"))
      .mockResolvedValue(task)
    mount(<RepairTaskList />)
    await screen.findByText("No repair tasks yet.")
    fireEvent.change(screen.getByLabelText("Repository fixture"), {
      target: { value: "arithmetic" },
    })
    fireEvent.change(screen.getByLabelText("Commit SHA"), {
      target: { value: task.target_commit },
    })
    fireEvent.change(screen.getByLabelText("Failing command"), {
      target: { value: task.failing_command },
    })
    fireEvent.click(screen.getByRole("button", { name: "Create task" }))
    await screen.findByText("Network unavailable")
    fireEvent.click(screen.getByRole("button", { name: "Create task" }))
    await screen.findByText("task-1")
    expect(vi.mocked(repairApi.create).mock.calls[0]?.[1]).toBe(
      vi.mocked(repairApi.create).mock.calls[1]?.[1]
    )
    expect(repairApi.create).toHaveBeenCalledWith(
      {
        fixture_id: "arithmetic",
        target_commit: task.target_commit,
        failing_command: task.failing_command,
        constraints: "",
      },
      expect.any(String)
    )
  })
  it("shows task failure and loads persisted patch/logs only when requested", async () => {
    const detail: TaskDetail = {
      task: {
        ...task,
        status: "FAILED",
        failure_reason: "regression_test_failed",
      },
      runs: [],
      events: [
        {
          sequence: 1,
          event: "VALIDATING",
          occurred_at: task.created_at,
          payload: {},
        },
      ],
      candidates: [
        {
          id: "candidate",
          repair_run_id: "run",
          base_commit: task.target_commit,
          sha256: "hash",
          files_changed: ["calc.py"],
          size_bytes: 20,
        },
      ],
      validations: [
        {
          id: "validation",
          status: "FAIL",
          attempt_no: 1,
          error_type: "regression_test_failed",
          duration_seconds: 0.2,
        },
      ],
    }
    vi.mocked(repairApi.detail).mockResolvedValue(detail)
    vi.mocked(repairApi.patch).mockResolvedValue("-return a - b\n+return a + b")
    vi.mocked(repairApi.artifacts).mockResolvedValue({
      candidate: detail.candidates[0]!,
      validations: [
        {
          ...detail.validations[0]!,
          checks: [
            {
              name: "REGRESSION_1",
              argv: ["python3"],
              exit_code: 1,
              output: "AssertionError",
              truncated: true,
              timed_out: false,
              duration_seconds: 0.1,
              stored_output_bytes: 100000,
            },
          ],
          manifest: { provider: "trusted_local_checkout" },
        },
      ],
      log_limit_bytes: 65536,
    })
    mount(<RepairTaskDetail taskId="task-1" />)
    await screen.findByText("Failure: regression_test_failed")
    expect(repairApi.patch).not.toHaveBeenCalled()
    expect(repairApi.artifacts).not.toHaveBeenCalled()
    fireEvent.click(
      screen.getByRole("button", { name: "Show patch and validation logs" })
    )
    await screen.findByText("AssertionError")
    expect(screen.getByLabelText("Candidate patch").textContent).toContain(
      "+return a + b"
    )
    expect(screen.getByText(/Output truncated/)).toBeTruthy()
  })
  it("reports missing or inaccessible tasks without showing a fake result", async () => {
    vi.mocked(repairApi.detail).mockRejectedValue(
      new Error("Repair task not found")
    )
    mount(<RepairTaskDetail taskId="missing" />)
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        "Repair task not found"
      )
    )
    expect(screen.queryByLabelText("Candidate patch")).toBeNull()
  })
})

it("polls active tasks and stops after a terminal result", async () => {
  vi.useFakeTimers()
  const active: TaskDetail = {
    task,
    runs: [],
    events: [],
    candidates: [],
    validations: [],
  }
  vi.mocked(repairApi.detail)
    .mockResolvedValueOnce(active)
    .mockResolvedValue({ ...active, task: { ...task, status: "COMPLETED" } })
  mount(<RepairTaskDetail taskId="poll-task" />)
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1)
  })
  expect(repairApi.detail).toHaveBeenCalledTimes(1)
  await act(async () => {
    await vi.advanceTimersByTimeAsync(4001)
  })
  expect(repairApi.detail).toHaveBeenCalledTimes(2)
  expect(screen.getByRole("status").textContent).toBe("COMPLETED")
  await act(async () => {
    await vi.advanceTimersByTimeAsync(12000)
  })
  expect(repairApi.detail).toHaveBeenCalledTimes(2)
  expect(repairApi.patch).not.toHaveBeenCalled()
})

it.each([null, "runtime_stop_unconfirmed"])(
  "refreshes timeout stop outcome %s before ending polling",
  async (error) => {
    vi.useFakeTimers()
    const run = {
      id: "run",
      thread_id: "thread",
      runtime_run_id: "runtime",
      dispatch_attempts: 1,
      dispatch_status: "FAILED",
      runtime_stop_pending: true,
      runtime_stop_error: null,
      started_at: null,
      ended_at: task.updated_at,
    }
    const detail: TaskDetail = {
      task: { ...task, status: "TIMEOUT" },
      runs: [run],
      events: [],
      candidates: [],
      validations: [],
    }
    vi.mocked(repairApi.detail)
      .mockReset()
      .mockResolvedValueOnce(detail)
      .mockResolvedValue({
        ...detail,
        runs: [{ ...run, runtime_stop_pending: false, runtime_stop_error: error }],
      })
    mount(<RepairTaskDetail taskId="stop-pending" />)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1)
    })
    expect(screen.getByText("Runtime stop awaiting confirmation.")).toBeTruthy()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(16000)
    })
    expect(repairApi.detail).toHaveBeenCalledTimes(2)
    expect(screen.queryByText("Runtime stop awaiting confirmation.")).toBeNull()
    if (error) expect(screen.getByText(new RegExp(error))).toBeTruthy()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(12000)
    })
    expect(repairApi.detail).toHaveBeenCalledTimes(2)
  }
)

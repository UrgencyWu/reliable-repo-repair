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

it("review: timeout with pending remote stop never refreshes the stop result", async () => {
  vi.useFakeTimers()
  const run = { id: "run", thread_id: "thread", runtime_run_id: "runtime", dispatch_attempts: 1, dispatch_status: "FAILED", runtime_stop_pending: true, runtime_stop_error: null, started_at: null, ended_at: task.updated_at }
  const detail: TaskDetail = { task: { ...task, status: "TIMEOUT" }, runs: [run], events: [], candidates: [], validations: [] }
  vi.mocked(repairApi.detail).mockReset().mockResolvedValueOnce(detail).mockResolvedValue({ ...detail, runs: [{ ...run, runtime_stop_pending: false }] })
  mount(<RepairTaskDetail taskId="stop-pending" />)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(screen.getByText("Runtime stop awaiting confirmation.")).toBeTruthy()
  await act(async () => { await vi.advanceTimersByTimeAsync(16000) })
  expect(repairApi.detail).toHaveBeenCalledTimes(1)
  expect(screen.getByText("Runtime stop awaiting confirmation.")).toBeTruthy()
})

it("review: a successful create retains its key for the next deliberate submission", async () => {
  vi.mocked(repairApi.list).mockResolvedValue({ items: [], limit: 20, offset: 0, has_more: false })
  vi.mocked(repairApi.create).mockReset().mockResolvedValue(task)
  mount(<RepairTaskList />)
  await screen.findByText("No repair tasks yet.")
  fireEvent.change(screen.getByLabelText("Repository fixture"), { target: { value: "arithmetic" } })
  fireEvent.change(screen.getByLabelText("Commit SHA"), { target: { value: task.target_commit } })
  fireEvent.change(screen.getByLabelText("Failing command"), { target: { value: task.failing_command } })
  fireEvent.click(screen.getByRole("button", { name: "Create task" }))
  await screen.findByText("task-1")
  fireEvent.click(screen.getByRole("button", { name: "Create task" }))
  await waitFor(() => expect(repairApi.create).toHaveBeenCalledTimes(2))
  expect(vi.mocked(repairApi.create).mock.calls[0]?.[1]).toBe(vi.mocked(repairApi.create).mock.calls[1]?.[1])
})

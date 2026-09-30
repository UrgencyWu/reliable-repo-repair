import { ApiError } from "@/lib/api"
import {
  dashboardForwardedHeaders,
  dashboardRequestOrigin,
  newRequestId,
  REQUEST_ID_HEADER,
} from "@/lib/dashboard-fetch"

export const REPAIR_POLL_INTERVAL = Math.min(
  60000,
  Math.max(1000, Number(import.meta.env.VITE_REPAIR_POLL_MS) || 4000)
)

export type RepairStatus =
  | "RECEIVED"
  | "QUEUED"
  | "PROVISIONING"
  | "VALIDATING"
  | "COMPLETED"
  | "FAILED"
  | "TIMEOUT"
export interface RepairTask {
  id: string
  trace_id: string
  fixture_id: string
  target_commit: string
  failing_command: string
  constraints: string
  status: RepairStatus
  failure_reason: string | null
  created_at: string
  updated_at: string
  deadline_at: string
}
export interface CreateTask {
  fixture_id: string
  target_commit: string
  failing_command: string
  constraints: string
}
export interface Candidate {
  id: string
  repair_run_id: string
  base_commit: string
  sha256: string
  files_changed: string[]
  size_bytes: number
}
export interface Validation {
  id: string
  status: "RUNNING" | "PASS" | "FAIL" | "ERROR"
  attempt_no: number
  error_type: string | null
  duration_seconds: number | null
}
export interface TaskDetail {
  task: RepairTask
  runs: {
    id: string
    thread_id: string
    runtime_run_id: string | null
    dispatch_attempts: number
    dispatch_status: string
    runtime_stop_pending: boolean
    runtime_stop_error: string | null
    started_at: string | null
    ended_at: string | null
  }[]
  events: {
    sequence: number
    event: string
    occurred_at: string
    payload: Record<string, string | number | boolean | null>
  }[]
  candidates: Candidate[]
  validations: Validation[]
}
export interface Check {
  name: string
  argv: string[]
  exit_code: number
  output: string
  truncated: boolean
  timed_out: boolean
  duration_seconds: number
  stored_output_bytes: number
}
export interface Artifacts {
  candidate: Candidate | null
  validations: (Validation & {
    checks: Check[]
    manifest: Record<string, string>
  })[]
  log_limit_bytes: number
}
export interface TaskPage {
  items: RepairTask[]
  limit: number
  offset: number
  has_more: boolean
}
export function isTerminal(status: RepairStatus): boolean {
  return ["COMPLETED", "FAILED", "TIMEOUT"].includes(status)
}

async function response(
  path: string,
  init: RequestInit = {}
): Promise<Response> {
  const requestId = newRequestId()
  const base = dashboardRequestOrigin().replace(/\/dashboard$/, "")
  const res = await fetch(`${base}/api/repair-tasks${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      [REQUEST_ID_HEADER]: requestId,
      ...dashboardForwardedHeaders(),
      ...init.headers,
    },
  })
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => null)
    let message = res.statusText
    if (body && typeof body === "object" && "detail" in body) {
      const detail = body.detail
      if (
        detail &&
        typeof detail === "object" &&
        "message" in detail &&
        typeof detail.message === "string"
      )
        message = detail.message
    }
    throw new ApiError(res.status, message, requestId)
  }
  return res
}
async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return (await response(path, init)).json()
}
export const repairApi = {
  list: (offset: number, signal?: AbortSignal) =>
    json<TaskPage>(`?limit=20&offset=${offset}`, { signal }),
  detail: (id: string, signal?: AbortSignal) =>
    json<TaskDetail>(`/${encodeURIComponent(id)}`, { signal }),
  artifacts: (id: string, signal?: AbortSignal) =>
    json<Artifacts>(`/${encodeURIComponent(id)}/artifacts`, { signal }),
  patch: async (id: string, signal?: AbortSignal): Promise<string> =>
    (await response(`/${encodeURIComponent(id)}/patch`, { signal })).text(),
  create: (body: CreateTask, key: string) =>
    json<RepairTask>("", {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify(body),
    }),
}

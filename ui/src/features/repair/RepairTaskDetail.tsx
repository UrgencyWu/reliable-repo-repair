import { useState } from "react"
import { Link } from "@tanstack/react-router"
import { useQuery } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { REPAIR_POLL_INTERVAL, isTerminal, repairApi } from "./api"

export function RepairTaskDetail({ taskId }: { taskId: string }) {
  const [resultsOpen, setResultsOpen] = useState(false)
  const detail = useQuery({
    queryKey: ["repair", "detail", taskId],
    queryFn: ({ signal }) => repairApi.detail(taskId, signal),
    retry: false,
    refetchInterval: (query) =>
      query.state.data &&
      isTerminal(query.state.data.task.status) &&
      !query.state.data.runs.some((run) => run.runtime_stop_pending)
        ? false
        : REPAIR_POLL_INTERVAL,
    refetchIntervalInBackground: false,
  })
  const candidate = detail.data?.candidates.at(-1)
  const validationStamp = detail.data?.validations
    .map((v) => `${v.id}:${v.status}`)
    .join(",")
  const artifacts = useQuery({
    queryKey: ["repair", "artifacts", taskId, validationStamp],
    queryFn: ({ signal }) => repairApi.artifacts(taskId, signal),
    enabled: resultsOpen && !!detail.data,
    retry: false,
  })
  const patch = useQuery({
    queryKey: ["repair", "patch", taskId, candidate?.sha256],
    queryFn: ({ signal }) => repairApi.patch(taskId, signal),
    enabled: resultsOpen && !!candidate,
    staleTime: Infinity,
    retry: false,
  })
  if (detail.isPending)
    return (
      <main className="p-6" role="status">
        Loading repair task…
      </main>
    )
  if (detail.error || !detail.data)
    return (
      <main className="space-y-4 p-6">
        <Link to="/repair">Back to Repair Tasks</Link>
        <p role="alert">{detail.error?.message ?? "Repair task unavailable"}</p>
        <Button onClick={() => void detail.refetch()}>Retry</Button>
      </main>
    )
  const { task, runs, events, validations } = detail.data
  return (
    <main className="mx-auto w-full max-w-5xl space-y-7 p-6">
      <Link className="underline" to="/repair">
        Back to Repair Tasks
      </Link>
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">{task.fixture_id} repair</h1>
        <p className="font-semibold" role="status">
          {task.status}
        </p>
        <p className="text-sm break-all">Task: {task.id}</p>
        <p className="font-mono text-sm break-all">
          Commit: {task.target_commit}
        </p>
        <p className="text-sm">Command: {task.failing_command}</p>
        {task.constraints && (
          <p className="text-sm whitespace-pre-wrap">
            Constraints: {task.constraints}
          </p>
        )}
        {task.failure_reason && (
          <p role="alert">Failure: {task.failure_reason}</p>
        )}
      </header>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Timeline</h2>
        <ol className="space-y-2 border-l pl-4">
          {events.map((event) => (
            <li key={event.sequence}>
              <span className="font-medium">
                {event.event.replaceAll("_", " ")}
              </span>
              <time className="ml-3 text-sm text-muted-foreground">
                {new Date(event.occurred_at).toLocaleString()}
              </time>
              {Object.entries(event.payload).length > 0 && (
                <dl className="text-xs text-muted-foreground">
                  {Object.entries(event.payload).map(([key, value]) => (
                    <div className="break-all" key={key}>
                      <dt className="inline">{key}: </dt>
                      <dd className="inline">{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              )}
            </li>
          ))}
        </ol>
      </section>
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">Run references</h2>
        <p className="text-xs break-all">Trace: {task.trace_id}</p>
        {runs.map((run) => (
          <div className="space-y-1 rounded border p-3 text-sm" key={run.id}>
            <p className="break-all">Run: {run.id}</p>
            <p className="break-all">Thread: {run.thread_id}</p>
            <p className="break-all">
              Runtime: {run.runtime_run_id ?? "Not started"}
            </p>
            <p>
              Dispatch: {run.dispatch_status} · attempts {run.dispatch_attempts}
            </p>
            {run.started_at && (
              <p>
                Execution duration:{" "}
                {Math.max(
                  0,
                  Math.round(
                    (Date.parse(run.ended_at ?? new Date().toISOString()) -
                      Date.parse(run.started_at)) /
                      1000
                  )
                )}
                s
              </p>
            )}
            {run.runtime_stop_pending && (
              <p>Runtime stop awaiting confirmation.</p>
            )}
            {run.runtime_stop_error && (
              <p role="alert">Runtime stop: {run.runtime_stop_error}</p>
            )}
          </div>
        ))}
      </section>
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">
          Patch and independent validation
        </h2>
        {!candidate && <p>No candidate patch available yet.</p>}
        {validations.map((validation) => (
          <p key={validation.id}>
            Validation {validation.attempt_no}:{" "}
            <strong>{validation.status}</strong>
            {validation.duration_seconds != null &&
              ` · ${validation.duration_seconds.toFixed(2)}s`}
            {validation.error_type && ` · ${validation.error_type}`}
          </p>
        ))}
        <Button
          variant="outline"
          onClick={() => setResultsOpen(true)}
          disabled={resultsOpen}
        >
          Show patch and validation logs
        </Button>
        {resultsOpen && (
          <>
            {patch.isFetching && <p role="status">Loading patch…</p>}
            {patch.error && <p role="alert">{patch.error.message}</p>}
            {candidate && (
              <div>
                <p>Files changed: {candidate.files_changed.join(", ")}</p>
                <p className="text-xs break-all">
                  Patch SHA256: {candidate.sha256}
                </p>
              </div>
            )}
            {patch.data && (
              <pre
                aria-label="Candidate patch"
                className="max-h-[32rem] overflow-auto rounded border bg-muted p-4 text-xs"
              >
                {patch.data.split("\n").map((line, i) => (
                  <span
                    className={`block ${line.startsWith("+") ? "text-green-700 dark:text-green-400" : line.startsWith("-") ? "text-red-700 dark:text-red-400" : ""}`}
                    key={i}
                  >
                    {line || " "}
                  </span>
                ))}
              </pre>
            )}
            {artifacts.isFetching && (
              <p role="status">Loading validation logs…</p>
            )}
            {artifacts.error && <p role="alert">{artifacts.error.message}</p>}
            <Button
              variant="outline"
              disabled={artifacts.isFetching}
              onClick={() => void artifacts.refetch()}
            >
              Refresh logs
            </Button>
            {artifacts.data?.validations.map((validation) => (
              <div key={validation.id} className="space-y-3 rounded border p-4">
                <h3 className="font-semibold">
                  Validation {validation.attempt_no}: {validation.status}
                </h3>
                {validation.checks.length === 0 && (
                  <p>Waiting for the first check result.</p>
                )}
                {validation.checks.map((check, index) => (
                  <details key={index}>
                    <summary className="cursor-pointer">
                      {check.name}: exit {check.exit_code} ·{" "}
                      {check.duration_seconds.toFixed(2)}s
                      {check.timed_out ? " · timed out" : ""}
                    </summary>
                    <p className="font-mono text-xs break-all">
                      {check.argv.join(" ")}
                    </p>
                    <pre className="max-h-64 overflow-auto bg-muted p-3 text-xs whitespace-pre-wrap">
                      {check.output || "No output."}
                    </pre>
                    {check.truncated && (
                      <p className="text-xs">
                        Output truncated; stored output is{" "}
                        {check.stored_output_bytes} bytes.
                      </p>
                    )}
                  </details>
                ))}
                <details>
                  <summary>Validation environment</summary>
                  <dl className="text-xs">
                    {Object.entries(validation.manifest).map(([key, value]) => (
                      <div className="break-all" key={key}>
                        <dt className="font-medium">{key}</dt>
                        <dd>{value}</dd>
                      </div>
                    ))}
                  </dl>
                </details>
              </div>
            ))}
          </>
        )}
      </section>
    </main>
  )
}

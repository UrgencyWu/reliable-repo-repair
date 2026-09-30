import { useRef, useState } from "react"
import { Link } from "@tanstack/react-router"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { REPAIR_POLL_INTERVAL, repairApi, type CreateTask } from "./api"

export function RepairTaskList() {
  const [offset, setOffset] = useState(0)
  const [form, setForm] = useState<CreateTask>({
    fixture_id: "",
    target_commit: "",
    failing_command: "",
    constraints: "",
  })
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null)
  const client = useQueryClient()
  const tasks = useQuery({
    queryKey: ["repair", "list", offset],
    queryFn: ({ signal }) => repairApi.list(offset, signal),
    staleTime: 0,
    refetchInterval: REPAIR_POLL_INTERVAL,
    refetchIntervalInBackground: false,
    retry: false,
  })
  const create = useMutation({
    mutationKey: ["repair", "create"],
    meta: { silent: true },
    mutationFn: async (input: CreateTask) => {
      const fingerprint = JSON.stringify(input)
      if (attempt.current?.fingerprint !== fingerprint)
        attempt.current = { fingerprint, key: crypto.randomUUID() }
      return repairApi.create(input, attempt.current.key)
    },
    onSuccess: () => {
      setOffset(0)
      void client.invalidateQueries({ queryKey: ["repair", "list"] })
    },
  })
  return (
    <main className="mx-auto w-full max-w-5xl space-y-8 p-6">
      <header>
        <h1 className="text-2xl font-semibold">Repair Tasks</h1>
        <p className="text-muted-foreground">
          Repair a configured repository and independently verify the patch.
        </p>
      </header>
      <form
        className="grid gap-4 rounded-lg border p-5"
        onSubmit={(event) => {
          event.preventDefault()
          if (!create.isPending) create.mutate(form)
        }}
      >
        <h2 className="font-semibold">Create repair task</h2>
        <p className="text-sm text-muted-foreground">
          Use a repository fixture configured by the backend administrator.
        </p>
        <label>
          Repository fixture
          <Input
            required
            pattern="[a-z0-9][a-z0-9_-]{0,63}"
            value={form.fixture_id}
            onChange={(e) => setForm({ ...form, fixture_id: e.target.value })}
          />
        </label>
        <label>
          Commit SHA
          <Input
            required
            pattern="[0-9a-f]{40}"
            maxLength={40}
            placeholder="Full 40-character commit SHA"
            value={form.target_commit}
            onChange={(e) =>
              setForm({ ...form, target_commit: e.target.value })
            }
          />
        </label>
        <label>
          Failing command
          <Input
            required
            maxLength={512}
            value={form.failing_command}
            onChange={(e) =>
              setForm({ ...form, failing_command: e.target.value })
            }
          />
        </label>
        <label>
          Constraints
          <Textarea
            maxLength={4000}
            value={form.constraints}
            onChange={(e) => setForm({ ...form, constraints: e.target.value })}
          />
        </label>
        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? "Creating…" : "Create task"}
        </Button>
        {create.error && <p role="alert">{create.error.message}</p>}
        {create.data && (
          <p role="status">
            Task accepted:{" "}
            <Link
              className="underline"
              to="/repair/$taskId"
              params={{ taskId: create.data.id }}
            >
              {create.data.id}
            </Link>
          </p>
        )}
      </form>
      <section className="space-y-3" aria-label="Repair task list">
        {tasks.isPending && <p role="status">Loading repair tasks…</p>}
        {tasks.error && (
          <div role="alert">
            {tasks.error.message}{" "}
            <Button variant="outline" onClick={() => void tasks.refetch()}>
              Retry
            </Button>
          </div>
        )}
        {tasks.data?.items.length === 0 && <p>No repair tasks yet.</p>}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                {["Repository", "Commit", "Status", "Created", "Duration"].map(
                  (label) => (
                    <th className="p-2" key={label}>
                      {label}
                    </th>
                  )
                )}
              </tr>
            </thead>
            <tbody>
              {tasks.data?.items.map((task) => (
                <tr className="border-t" key={task.id}>
                  <td className="p-2">
                    <Link
                      className="underline"
                      to="/repair/$taskId"
                      params={{ taskId: task.id }}
                    >
                      {task.fixture_id}
                    </Link>
                  </td>
                  <td className="p-2 font-mono" title={task.target_commit}>
                    {task.target_commit.slice(0, 8)}
                  </td>
                  <td className="p-2">{task.status}</td>
                  <td className="p-2">
                    {new Date(task.created_at).toLocaleString()}
                  </td>
                  <td className="p-2">
                    {Math.max(
                      0,
                      Math.round(
                        (Date.parse(
                          ["COMPLETED", "FAILED", "TIMEOUT"].includes(
                            task.status
                          )
                            ? task.updated_at
                            : new Date().toISOString()
                        ) -
                          Date.parse(task.created_at)) /
                          1000
                      )
                    )}
                    s
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 20))}
          >
            Previous
          </Button>
          <span>Page {offset / 20 + 1}</span>
          <Button
            variant="outline"
            disabled={!tasks.data?.has_more}
            onClick={() => setOffset(offset + 20)}
          >
            Next
          </Button>
        </div>
      </section>
    </main>
  )
}

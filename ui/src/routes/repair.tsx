import { useEffect } from "react"
import { Outlet, createFileRoute, useRouterState } from "@tanstack/react-router"
import { AgentsShell } from "@/features/agents/components/AgentsSidebar"
import { RequireLogin } from "@/lib/auth-redirect"
import { rememberAppLocation } from "@/lib/appLocation"
import { useSession } from "@/lib/session"

export const Route = createFileRoute("/repair")({ component: RepairLayout })
function RepairLayout() {
  const session = useSession()
  const href = useRouterState({ select: (state) => state.location.href })
  useEffect(() => {
    rememberAppLocation(href)
  }, [href])
  if (session.isPending)
    return (
      <p className="p-6" role="status">
        Loading session…
      </p>
    )
  if (session.error)
    return (
      <p className="p-6" role="alert">
        {session.error.message}
      </p>
    )
  if (!session.data) return <RequireLogin />
  return (
    <AgentsShell user={session.data}>
      <div className="min-w-0 flex-1 overflow-y-auto">
        <Outlet />
      </div>
    </AgentsShell>
  )
}

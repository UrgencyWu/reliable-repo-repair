import { createFileRoute } from "@tanstack/react-router"
import { RepairTaskDetail } from "@/features/repair/RepairTaskDetail"
import { pageTitle } from "@/lib/pageTitle"
export const Route = createFileRoute("/repair/$taskId")({
  component: Page,
  head: () => ({ meta: [{ title: pageTitle("Repair Task") }] }),
})
function Page() {
  const { taskId } = Route.useParams()
  return <RepairTaskDetail key={taskId} taskId={taskId} />
}

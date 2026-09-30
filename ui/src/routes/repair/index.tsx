import { createFileRoute } from "@tanstack/react-router"
import { RepairTaskList } from "@/features/repair/RepairTaskList"
import { pageTitle } from "@/lib/pageTitle"
export const Route = createFileRoute("/repair/")({
  component: RepairTaskList,
  head: () => ({ meta: [{ title: pageTitle("Repair Tasks") }] }),
})

import { createFileRoute } from "@tanstack/react-router";
import { AdminGate } from "@/components/admin/AdminLayout";

export const Route = createFileRoute("/_authenticated/admin")({
  component: AdminGate,
});

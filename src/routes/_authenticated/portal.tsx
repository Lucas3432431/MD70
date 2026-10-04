import { createFileRoute, Outlet } from "@tanstack/react-router";
import { PortalLayout } from "@/components/portal/PortalLayout";

export const Route = createFileRoute("/_authenticated/portal")({
  component: () => <PortalLayout><Outlet /></PortalLayout>,
});

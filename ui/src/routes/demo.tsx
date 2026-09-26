import { Outlet, createFileRoute } from "@tanstack/react-router";

import { AppHeader } from "@/components/app-header";
import { CommandBar } from "@/components/command-bar";
import { KillSwitchDialog } from "@/components/kill-switch";

export const Route = createFileRoute("/demo")({
  component: DemoLayout,
});

/** Layout for the interactive demo: landing and /download render standalone. */
function DemoLayout() {
  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main>
        {/* Required: nested routes render here. */}
        <Outlet />
      </main>
      <CommandBar />
      <KillSwitchDialog />
    </div>
  );
}

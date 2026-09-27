import { Link } from "@tanstack/react-router";
import {
  CircuitBoard,
  Inbox,
  LayoutGrid,
  Moon,
  OctagonX,
  Rocket,
  Search,
  Settings,
  Sun,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useTheme } from "@/components/theme-provider";
import { useStore } from "@/components/app-store";
import { KillSwitchTrigger } from "@/components/kill-switch";
import { ConnectionStatus } from "@/components/connection-status";
import { useQuery } from "@tanstack/react-query";
import { approvalQueueQuery, setupStateQuery, spendTodayQuery } from "@/lib/queries";
import { DEMO_MODE } from "@/lib/api";
import { LanguageToggle, useT, type MessageKey } from "@/lib/i18n";
import { UpdateBanner } from "@/components/update-banner";

const nav: ReadonlyArray<{ to: string; label: MessageKey }> = DEMO_MODE
  ? [
      { to: "/demo", label: "nav.team" },
      { to: "/demo/approvals", label: "nav.approvals" },
    ]
  : [
      { to: "/demo", label: "nav.team" },
      { to: "/missions", label: "nav.missions" },
      { to: "/routines", label: "nav.routines" },
      { to: "/approvals", label: "nav.approvals" },
    ];

export function AppHeader() {
  const t = useT();
  const { theme, toggle } = useTheme();
  const { approvals: localApprovals, setCommandOpen, setKillSwitchOpen } = useStore();
  const approvalsResult = useQuery(approvalQueueQuery("pending"));
  const pendingCount =
    approvalsResult.data?.length ?? (approvalsResult.isError ? localApprovals.length : 0);
  const setupResult = useQuery(setupStateQuery());
  const needsSetup = !DEMO_MODE && Boolean(setupResult.data?.needs_setup);
  const spendResult = useQuery({ ...spendTodayQuery(), enabled: !DEMO_MODE });
  const spend = spendResult.data;
  const nearCap = (spend?.agents ?? []).some(
    (a) => a.budget_usd !== null && a.spent_usd >= a.budget_usd * 0.8,
  );
  const overCap = (spend?.agents ?? []).some(
    (a) => a.budget_usd !== null && a.spent_usd >= a.budget_usd,
  );
  const spendTitle = (spend?.agents ?? [])
    .map(
      (a) =>
        `${a.agent_id}: $${a.spent_usd.toFixed(4)}` +
        (a.budget_usd === null ? t("hdr.noCap") : t("hdr.ofCap", { cap: `$${a.budget_usd.toFixed(2)}` })),
    )
    .join("\n");

  return (
    <header className="sticky top-0 z-40 border-b border-border bg-background/85 backdrop-blur">
      {!DEMO_MODE && <UpdateBanner />}
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-4 px-6">
        <Link to="/demo" className="flex shrink-0 items-center gap-2" aria-label={t("hdr.home")}>
          <span className="grid size-6 shrink-0 place-items-center rounded-md bg-[#f4f1ea]">
            <img
              src="/eeze-mark.png"
              alt=""
              width={20}
              height={20}
              aria-hidden="true"
              className="h-5 w-5"
            />
          </span>
          <span className="whitespace-nowrap text-sm font-semibold tracking-tight">Eeze Agents</span>
        </Link>

        <nav aria-label={t("hdr.mainNav")} className="ml-2 hidden items-center gap-1 sm:flex">
          {nav.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              activeOptions={{ exact: item.to === "/demo" }}
              className="inline-flex items-center whitespace-nowrap rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground data-[status=active]:bg-accent data-[status=active]:text-foreground"
            >
              {t(item.label)}
              {item.to.endsWith("approvals") && pendingCount > 0 && (
                <Badge variant="secondary" className="ml-2 px-1.5 py-0 text-[10px]">
                  {pendingCount}
                </Badge>
              )}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-1.5">
          {needsSetup && (
            <Button variant="outline" size="sm" asChild className="gap-1.5 whitespace-nowrap">
              <Link to="/setup" title={t("hdr.finishSetup")}>
                <Rocket className="size-3.5" />
                {t("header.setup")}
              </Link>
            </Button>
          )}
          {!DEMO_MODE && spend && (
            <span
              title={`${t("header.spendTitle")}\n${spendTitle}`}
              className={`hidden items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-1 font-mono text-xs lg:inline-flex ${
                overCap
                  ? "border-destructive/40 bg-destructive/10 text-destructive"
                  : nearCap
                    ? "border-warning/40 bg-warning/10 text-warning"
                    : "border-border bg-muted text-muted-foreground"
              }`}
            >
              {overCap ? `${t("header.budgetReached")} · ` : `${t("header.today")} `}$
              {spend.total_usd.toFixed(2)}
            </span>
          )}
          {DEMO_MODE ? (
            <span
              title={t("hdr.demoTitle")}
              className="mr-1 inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground"
            >
              <span className="size-1.5 rounded-full bg-muted-foreground/50" />
              {t("hdr.demoBadge")}
            </span>
          ) : (
            <ConnectionStatus />
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={() => setCommandOpen(true)}
            className="hidden gap-2 whitespace-nowrap text-muted-foreground lg:flex"
          >
            <Search className="size-3.5" />
            <span>{t("header.command")}</span>
            <kbd className="rounded border border-border bg-muted px-1.5 font-mono text-[10px]">
              ⌃⇧E
            </kbd>
          </Button>
          {!DEMO_MODE && <LanguageToggle />}
          <Button variant="ghost" size="icon" asChild aria-label={t("cmd.approvals")}>
            <Link to={DEMO_MODE ? "/demo/approvals" : "/approvals"}>
              <Inbox className="size-4" />
            </Link>
          </Button>
          <Button variant="ghost" size="icon" aria-label={t("hdr.settings")} asChild>
            <Link to="/demo/settings">
              <Settings className="size-4" />
            </Link>
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={toggle}
            aria-label={theme === "dark" ? t("theme.toLight") : t("theme.toDark")}
          >
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label={t("hdr.trayMenu")}>
                <CircuitBoard className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel>{t("hdr.tray")}</DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild>
                <Link to="/demo">
                  <LayoutGrid className="size-4" />
                  {t("hdr.openTeam")}
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => setCommandOpen(true)}>
                <Search className="size-4" />
                {t("hdr.commandBar")}
              </DropdownMenuItem>
              <DropdownMenuItem asChild>
                <Link to="/demo/settings">
                  <Settings className="size-4" />
                  {t("hdr.settings")}
                </Link>
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="text-destructive focus:text-destructive"
                onSelect={() => setKillSwitchOpen(true)}
              >
                <OctagonX className="size-4" />
                {t("kill.emergency")}
                <span className="ml-auto font-mono text-[10px] text-muted-foreground">⌃⇧⌥K</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <KillSwitchTrigger />
        </div>
      </div>
    </header>
  );
}

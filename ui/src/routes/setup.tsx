import { useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CheckCircle2, CircleDashed, Rocket, ShieldCheck, XCircle } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ErrorState, RowSkeleton } from "@/components/data-state";
import { routinesQuery, setupStateQuery, systemStatusQuery } from "@/lib/queries";
import { DEMO_MODE, api, type RoutineCreateRequest } from "@/lib/api";

export const Route = createFileRoute("/setup")({
  head: () => ({ meta: [{ title: "Setup — Eeze Agents" }] }),
  component: SetupPage,
});

const STEPS = ["System check", "Connect Gmail", "First routine", "Done"] as const;

function StepDots({ step }: { step: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-2 text-xs">
      {STEPS.map((label, index) => (
        <li
          key={label}
          className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 ${
            index === step
              ? "border-primary/40 bg-primary/10 font-medium text-foreground"
              : index < step
                ? "border-border text-muted-foreground"
                : "border-dashed border-border text-muted-foreground/70"
          }`}
        >
          {index < step ? (
            <CheckCircle2 className="size-3 text-success" />
          ) : (
            <CircleDashed className="size-3" />
          )}
          {label}
        </li>
      ))}
    </ol>
  );
}

function CheckRow({ ok, label, detail }: { ok: boolean; label: string; detail?: string }) {
  return (
    <li className="flex items-start gap-2.5 py-2.5">
      {ok ? (
        <CheckCircle2 className="mt-0.5 size-4 text-success" />
      ) : (
        <XCircle className="mt-0.5 size-4 text-warning" />
      )}
      <div>
        <p className="text-sm font-medium">{label}</p>
        {detail && <p className="text-xs text-muted-foreground">{detail}</p>}
      </div>
    </li>
  );
}

function SetupPage() {
  const queryClient = useQueryClient();
  const state = useQuery(setupStateQuery());
  const status = useQuery(systemStatusQuery());
  const notify = useMutation({
    mutationFn: (enabled: boolean) => api.setNotify(enabled),
    onSuccess: async (result) => {
      toast.success(result.enabled ? "Approval alerts on." : "Approval alerts off.");
      await queryClient.invalidateQueries({ queryKey: ["system-status"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const routines = useQuery(routinesQuery());
  const [step, setStep] = useState(0);

  // Gmail form
  const [host, setHost] = useState("imap.gmail.com");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  // First-routine form
  const [summaryTo, setSummaryTo] = useState("");
  const [sendSummary, setSendSummary] = useState(true);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["setup-state"] });
    void queryClient.invalidateQueries({ queryKey: ["routines"] });
  };

  const test = useMutation({
    mutationFn: () => api.testImap({ host, user, app_password: password }),
    onSuccess: (result) => {
      if (result.ok) {
        setTestResult({
          ok: true,
          message: `Connected — ${result.messages ?? "?"} messages in the inbox.`,
        });
        toast.success("Mailbox connection works.");
      } else {
        setTestResult({ ok: false, message: result.error ?? "Connection failed." });
        toast.error("Connection failed.");
      }
    },
    onError: (error: Error) => setTestResult({ ok: false, message: error.message }),
  });

  const save = useMutation({
    mutationFn: () => api.saveImap({ host, user, app_password: password }),
    onSuccess: () => {
      toast.success("Saved to your machine only (.env).");
      setPassword("");
      refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const createRoutine = useMutation({
    mutationFn: (body: RoutineCreateRequest) => api.createRoutine(body),
    onSuccess: () => {
      toast.success("Routine created — it will run on schedule.");
      refresh();
      setStep(3);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const finish = useMutation({
    mutationFn: () => api.completeSetup(),
    onSuccess: () => {
      toast.success("Setup complete.");
      refresh();
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const alreadyDone = state.data && !state.data.needs_setup && step === 0;

  return (
    <>
      <AppHeader />
      <div className="mx-auto max-w-3xl px-4 py-8 sm:px-6 sm:py-10">
        <div className="flex items-center gap-2">
          <Rocket className="size-5 text-muted-foreground" />
          <h1 className="text-2xl font-semibold tracking-tight">Set up Eeze</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">
          Three quick steps — everything stays on this machine.
        </p>
        <div className="mt-4">
          <StepDots step={step} />
        </div>

        {state.isError ? (
          <ErrorState onRetry={refresh} />
        ) : state.isLoading ? (
          <RowSkeleton rows={2} />
        ) : alreadyDone ? (
          <Card className="mt-6">
            <CardHeader>
              <div className="flex items-center gap-2">
                <ShieldCheck className="size-4 text-success" />
                <h2 className="text-base font-semibold">Setup is already complete</h2>
              </div>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              <Button asChild size="sm">
                <Link to="/routines">Open routines</Link>
              </Button>
              <Button asChild size="sm" variant="outline">
                <Link to="/approvals">Open approvals</Link>
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setStep(1)}>
                Review settings
              </Button>
            </CardContent>
          </Card>
        ) : (
          <Card className="mt-6">
            <CardContent className="pt-6">
              {step === 0 && (
                <div>
                  <h2 className="text-base font-semibold">System check</h2>
                  <ul className="mt-2 divide-y divide-border">
                    <CheckRow
                      ok={Boolean(state.data?.daemon_running)}
                      label="Background service"
                      detail={
                        state.data?.daemon_running
                          ? `Running (v${state.data.version})`
                          : "Not running — double-click install.cmd (or the Eeze Agent Desktop shortcut)."
                      }
                    />
                    <CheckRow
                      ok={Boolean(state.data?.imap_configured)}
                      label="Mailbox connected"
                      detail={
                        state.data?.imap_configured
                          ? `${state.data.imap_user} @ ${state.data.imap_host ?? "imap.gmail.com"}`
                          : "Not yet — the next step connects Gmail (read-only)."
                      }
                    />
                    <CheckRow
                      ok={(state.data?.routines_count ?? 0) > 0}
                      label="Routines"
                      detail={`${state.data?.routines_count ?? 0} configured`}
                    />
                    <CheckRow
                      ok={Boolean(state.data?.tools?.["ffmpeg"])}
                      label="ffmpeg (video & photo missions)"
                      detail={
                        state.data?.tools?.["ffmpeg"] ??
                        "Not found — install it (winget install Gyan.FFmpeg) to edit video and photos."
                      }
                    />
                    <CheckRow
                      ok={Boolean(state.data?.tools?.["blender"])}
                      label="Blender (3D missions)"
                      detail={
                        state.data?.tools?.["blender"] ??
                        "Not found — install Blender from blender.org to render 3D scenes."
                      }
                    />
                    <CheckRow
                      ok={Boolean(state.data?.tools?.["codex"])}
                      label="Codex CLI (writes mission plans on your subscription)"
                      detail={
                        state.data?.tools?.["codex"] ??
                        "Not found — plans will use the model provider set in Settings instead."
                      }
                    />
                  </ul>
                  <div className="mt-4 flex gap-2">
                    <Button size="sm" onClick={() => setStep(1)}>
                      Continue
                    </Button>
                  </div>
                </div>
              )}

              {step === 1 && (
                <div>
                  <h2 className="text-base font-semibold">Connect Gmail (read-only)</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Eeze reads invoices from your mailbox and never marks, moves, or deletes email.
                    Use a Google <span className="font-medium">app password</span> — the value is
                    written straight to the local <code>.env</code> and never shown again.
                  </p>
                  {state.data?.imap_configured && (
                    <p className="mt-3 rounded-md border border-success/25 bg-success/10 px-3 py-2 text-xs text-success">
                      Currently connected as {state.data.imap_user}. Saving again replaces it.
                    </p>
                  )}
                  <div className="mt-4 grid gap-3 sm:grid-cols-2">
                    <div className="grid gap-1.5">
                      <Label htmlFor="imap-host">IMAP host</Label>
                      <Input
                        id="imap-host"
                        value={host}
                        onChange={(e) => setHost(e.target.value)}
                      />
                    </div>
                    <div className="grid gap-1.5">
                      <Label htmlFor="imap-user">Email address</Label>
                      <Input
                        id="imap-user"
                        value={user}
                        onChange={(e) => setUser(e.target.value)}
                        placeholder="you@gmail.com"
                      />
                    </div>
                    <div className="grid gap-1.5 sm:col-span-2">
                      <Label htmlFor="imap-pass">App password</Label>
                      <Input
                        id="imap-pass"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="xxxx xxxx xxxx xxxx"
                        autoComplete="off"
                      />
                    </div>
                  </div>
                  {testResult && (
                    <p
                      className={`mt-3 rounded-md border px-3 py-2 text-xs ${
                        testResult.ok
                          ? "border-success/25 bg-success/10 text-success"
                          : "border-destructive/30 bg-destructive/10 text-destructive"
                      }`}
                    >
                      {testResult.message}
                    </p>
                  )}
                  <div className="mt-4 flex flex-wrap gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => test.mutate()}
                      disabled={test.isPending || !user || !password}
                    >
                      {test.isPending ? "Testing…" : "Test connection"}
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => save.mutate()}
                      disabled={save.isPending || !user || !password}
                    >
                      {save.isPending ? "Saving…" : "Save"}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setStep(2)}>
                      {state.data?.imap_configured ? "Continue" : "Skip for now"}
                    </Button>
                  </div>
                </div>
              )}

              {step === 2 && (
                <div>
                  <h2 className="text-base font-semibold">First routine</h2>
                  {(routines.data ?? []).length > 0 ? (
                    <div className="mt-3">
                      <p className="text-sm text-muted-foreground">
                        You already have {routines.data?.length} routine
                        {(routines.data?.length ?? 0) > 1 ? "s" : ""}:
                      </p>
                      <ul className="mt-2 space-y-1">
                        {(routines.data ?? []).map((routine) => (
                          <li key={routine.id} className="flex items-center gap-2 text-sm">
                            <Badge variant="outline">{routine.kind}</Badge>
                            {routine.name}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : (
                    <>
                      <p className="mt-1 text-sm text-muted-foreground">
                        The classic one: scan the mailbox every morning, build the verified invoice
                        ledger, and email you the summary — the email waits for your approval.
                      </p>
                      <div className="mt-4 grid gap-3">
                        <div className="grid gap-1.5">
                          <Label htmlFor="setup-email-to">Send the summary to</Label>
                          <Input
                            id="setup-email-to"
                            value={summaryTo}
                            onChange={(e) => setSummaryTo(e.target.value)}
                            placeholder={state.data?.imap_user ?? "you@example.com"}
                          />
                        </div>
                        <div className="flex items-center gap-2">
                          <Switch checked={sendSummary} onCheckedChange={setSendSummary} />
                          <span className="text-sm text-muted-foreground">
                            Email summary enabled (gated by your approval)
                          </span>
                        </div>
                      </div>
                    </>
                  )}
                  <div className="mt-4 flex flex-wrap gap-2">
                    {(routines.data ?? []).length > 0 ? (
                      <Button size="sm" onClick={() => setStep(3)}>
                        Continue
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        onClick={() =>
                          createRoutine.mutate({
                            id: "invoices",
                            name: "Gmail invoices",
                            kind: "invoices",
                            schedule: { type: "daily", at: "08:00" },
                            params: {
                              email_summary: sendSummary,
                              ...(summaryTo.trim() || state.data?.imap_user
                                ? { email_to: summaryTo.trim() || (state.data?.imap_user ?? "") }
                                : {}),
                            },
                          })
                        }
                        disabled={createRoutine.isPending}
                      >
                        {createRoutine.isPending ? "Creating…" : "Create daily invoices routine"}
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" onClick={() => setStep(3)}>
                      Skip
                    </Button>
                  </div>
                </div>
              )}

              {step === 3 && (
                <div className="text-center">
                  <div className="mx-auto grid size-12 place-items-center rounded-full bg-success/12">
                    <CheckCircle2 className="size-6 text-success" />
                  </div>
                  <h2 className="mt-3 text-lg font-semibold">You're set</h2>
                  <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
                    Schedules run in the background while the service is on. When a routine reaches
                    a risky step, it pauses and waits for your click in Approvals.
                  </p>
                  <div className="mt-5 flex flex-wrap justify-center gap-2">
                    <Button size="sm" onClick={() => finish.mutate()} disabled={finish.isPending}>
                      {finish.isPending ? "Finishing…" : "Finish setup"}
                    </Button>
                    <Button asChild size="sm" variant="outline">
                      <Link to="/routines">Open routines</Link>
                    </Button>
                    <Button asChild size="sm" variant="ghost">
                      <Link to="/approvals">Open approvals</Link>
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        {!DEMO_MODE && (
          <Card className="mt-6">
            <CardHeader>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-base font-semibold">Notifications</h2>
                  <p className="mt-1 text-sm text-muted-foreground">
                    A Windows alert when a run pauses for approval — visible without stealing focus
                    from whatever you are doing.
                  </p>
                </div>
                <Switch
                  checked={status.data?.notifications_enabled ?? true}
                  disabled={!status.data || notify.isPending}
                  aria-label="Desktop alerts for approvals"
                  onCheckedChange={(checked) => notify.mutate(checked)}
                />
              </div>
            </CardHeader>
          </Card>
        )}

        {DEMO_MODE && (
          <p className="mt-4 text-xs text-muted-foreground">
            Demo mode: setup runs on your own machine after install.
          </p>
        )}
      </div>
    </>
  );
}

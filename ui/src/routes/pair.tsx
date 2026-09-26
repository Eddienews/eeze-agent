import { useEffect, useState, type FormEvent } from "react";
import { Link, createFileRoute } from "@tanstack/react-router";
import { MousePointerClick, ShieldCheck } from "lucide-react";
import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_URL, DEMO_MODE } from "@/lib/api";
import { safeReturnPath, takeReturnPath } from "@/lib/pairing";
import { useT } from "@/lib/i18n";

export const Route = createFileRoute("/pair")({
  head: () => ({ meta: [{ title: "Pair operator — Eeze Agents" }] }),
  component: PairPage,
});

function PairPage() {
  const t = useT();
  const [token, setToken] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [showToken, setShowToken] = useState(false);

  // Opened by the "Eeze Agent" shortcut (`eeze open`): #code=<one-time code> pairs silently.
  useEffect(() => {
    if (DEMO_MODE) return;
    const code = new URLSearchParams(window.location.hash.slice(1)).get("code");
    if (!code) return;
    const next = safeReturnPath(new URLSearchParams(window.location.search).get("next"));
    window.history.replaceState(null, "", window.location.pathname); // the code never lingers
    setPending(true);
    fetch(`${API_URL}/session/pair`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ code }),
    })
      .then((response) => {
        if (response.ok) {
          window.location.assign(next);
        } else {
          setError(t("pair.expired"));
          setPending(false);
        }
      })
      .catch(() => {
        setError(t("pair.unreachable"));
        setPending(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function pair(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (DEMO_MODE || pending || !token.trim()) return;
    setPending(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/session/pair`, {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ token: token.trim() }),
      });
      if (!response.ok) {
        setError(t("pair.failed"));
        return;
      }
      window.location.assign(takeReturnPath());
    } catch {
      setError(t("pair.unreachable"));
    } finally {
      setToken("");
      setPending(false);
    }
  }

  return (
    <div className="min-h-screen bg-background">
      <AppHeader />
      <main className="mx-auto max-w-md px-4 py-12 sm:py-20">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <ShieldCheck aria-hidden="true" className="size-5 text-primary" />
              <h1 className="text-xl font-semibold tracking-tight">{t("pair.title")}</h1>
            </div>
            <p className="text-sm text-muted-foreground">{t("pair.why")}</p>
          </CardHeader>
          <CardContent className="space-y-5">
            {DEMO_MODE ? (
              <p className="text-sm text-muted-foreground">
                {t("pair.demo")}{" "}
                <Link to="/demo" className="text-primary underline">
                  {t("pair.openDemo")}
                </Link>
              </p>
            ) : (
              <>
                <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 text-sm">
                  <p className="flex items-center gap-2 font-medium">
                    <MousePointerClick aria-hidden="true" className="size-4 text-primary" />
                    {t("pair.easyTitle")}
                  </p>
                  <p className="mt-1.5 text-muted-foreground">{t("pair.easyBody")}</p>
                  {pending && !showToken && (
                    <p className="mt-2 text-xs text-primary">{t("pair.signingIn")}</p>
                  )}
                </div>
                {error && (
                  <p role="alert" className="text-sm text-destructive">
                    {error}
                  </p>
                )}
                {!showToken ? (
                  <button
                    type="button"
                    onClick={() => setShowToken(true)}
                    className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                  >
                    {t("pair.otherWay")}
                  </button>
                ) : (
                  <form
                    onSubmit={(event) => void pair(event)}
                    autoComplete="off"
                    className="space-y-3 border-t border-border pt-4"
                  >
                    <div className="space-y-2">
                      <Label htmlFor="operator-token">{t("pair.tokenLabel")}</Label>
                      <p className="text-xs text-muted-foreground">
                        {t("pair.tokenWhere")} <code>%USERPROFILE%\.eeze\api.token</code>
                      </p>
                      <Input
                        id="operator-token"
                        type="password"
                        name="operator-token"
                        autoComplete="off"
                        autoCapitalize="none"
                        spellCheck={false}
                        value={token}
                        onChange={(event) => setToken(event.target.value)}
                        required
                        autoFocus
                      />
                      <p className="text-xs text-muted-foreground">{t("pair.tokenSafety")}</p>
                    </div>
                    <Button type="submit" disabled={pending || !token.trim()} className="w-full">
                      {pending ? t("pair.pending") : t("pair.submit")}
                    </Button>
                  </form>
                )}
                <p className="text-xs text-muted-foreground">{t("pair.duration")}</p>
              </>
            )}
          </CardContent>
        </Card>
      </main>
    </div>
  );
}

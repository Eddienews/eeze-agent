import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { toast } from "sonner";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { AgentAvatar } from "@/components/agent-avatar";
import { useStore } from "@/components/app-store";
import { Inbox, LayoutGrid, Rocket, Send } from "lucide-react";
import { DEMO_MODE, type MissionKind } from "@/lib/api";
import { useT } from "@/lib/i18n";

/** Best guess of the mission kind from the words of a request (EN + PT). */
export function guessMissionKind(text: string): MissionKind {
  const t = text.toLowerCase();
  if (/(renam|renome|organi[sz]|duplicat|duplicad)/.test(t)) return "files";
  if (/\b(3d|blender|render|turntable|glb|modelo 3d|cena 3d)\b/.test(t)) return "3d";
  if (/(v[ií]deo|video|clip|clipe|reels?|shorts?|tiktok|mp4|teaser|slideshow)/.test(t)) return "video";
  if (/(photo|foto|image|imagem|picture|png|jpe?g|instagram|crop|recort)/.test(t)) return "photo";
  return "task";
}

export function CommandBar() {
  const t = useT();
  const { agents, commandOpen, setCommandOpen } = useStore();
  const [query, setQuery] = useState("");
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === "e" && e.ctrlKey && e.shiftKey) {
        e.preventDefault();
        setCommandOpen(!commandOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [commandOpen, setCommandOpen]);

  const mention = query.match(/@(\w*)$/)?.[1]?.toLowerCase();
  const mentioned = agents.find((a) => query.toLowerCase().includes(`@${a.name.toLowerCase()}`));

  const close = () => {
    setCommandOpen(false);
    setQuery("");
  };

  const dispatch = () => {
    const goal = query.replace(/@\w+\s*/g, "").trim();
    if (!goal) return;
    if (DEMO_MODE) {
      toast.message(t("cmd.demo"), { description: goal });
      close();
      return;
    }
    // A request becomes a mission draft: the plan is written, shown and approved as usual —
    // nothing runs from here.
    navigate({
      to: "/missions",
      search: {
        goal,
        kind: guessMissionKind(goal),
        ...(mentioned ? { agent: mentioned.id } : {}),
      },
    });
    close();
  };

  return (
    <CommandDialog open={commandOpen} onOpenChange={(o) => (o ? setCommandOpen(true) : close())}>
      <CommandInput
        value={query}
        onValueChange={setQuery}
        placeholder={t("cmd.placeholder")}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !mention && query.trim()) {
            e.preventDefault();
            dispatch();
          }
        }}
      />
      <CommandList>
        <CommandEmpty>{t("cmd.empty")}</CommandEmpty>
        {query.trim() && !mention && (
          <CommandGroup heading={t("cmd.newMission")}>
            <CommandItem value={`run-${query}`} onSelect={dispatch}>
              <Send className="text-muted-foreground" />
              <span className="truncate">
                {mentioned
                  ? t("cmd.draftFor", { q: query.trim(), agent: mentioned.name })
                  : t("cmd.draft", { q: query.trim() })}
              </span>
            </CommandItem>
          </CommandGroup>
        )}
        <CommandGroup heading={t("cmd.agents")}>
          {agents
            .filter((a) => !mention || a.name.toLowerCase().startsWith(mention))
            .map((agent) => (
              <CommandItem
                key={agent.id}
                value={`@${agent.name} ${agent.role}`}
                onSelect={() => {
                  if (mention !== undefined) {
                    setQuery(query.replace(/@(\w*)$/, `@${agent.name} `));
                    return;
                  }
                  navigate({ to: "/demo/agents/$agentId", params: { agentId: agent.id } });
                  close();
                }}
              >
                <AgentAvatar name={agent.name} accent={agent.accent} size="sm" />
                <span className="font-medium">@{agent.name}</span>
                <span className="text-muted-foreground">{agent.role}</span>
              </CommandItem>
            ))}
        </CommandGroup>
        <CommandGroup heading={t("cmd.navigate")}>
          <CommandItem
            value="team dashboard"
            onSelect={() => {
              navigate({ to: "/demo" });
              close();
            }}
          >
            <LayoutGrid className="text-muted-foreground" />
            {t("cmd.team")}
          </CommandItem>
          {!DEMO_MODE && (
            <CommandItem
              value="missions"
              onSelect={() => {
                navigate({ to: "/missions" });
                close();
              }}
            >
              <Rocket className="text-muted-foreground" />
              {t("cmd.missions")}
            </CommandItem>
          )}
          <CommandItem
            value="approval inbox"
            onSelect={() => {
              navigate({ to: DEMO_MODE ? "/demo/approvals" : "/approvals" });
              close();
            }}
          >
            <Inbox className="text-muted-foreground" />
            {t("cmd.approvals")}
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}

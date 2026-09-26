import type { CSSProperties } from "react";
import { cn } from "@/lib/utils";

const sizes = {
  sm: "size-7 text-[11px]",
  md: "size-10 text-sm",
  lg: "size-16 text-xl",
} as const;

export function AgentAvatar({
  name,
  accent,
  size = "md",
  className,
}: {
  name: string;
  accent: string;
  size?: keyof typeof sizes;
  className?: string;
}) {
  const style = { "--agent-color": `var(--agent-${accent})` } as CSSProperties;
  return (
    <span
      aria-hidden
      style={style}
      className={cn(
        "agent-tint inline-flex shrink-0 items-center justify-center rounded-full font-semibold tracking-tight ring-1 ring-current/25",
        sizes[size],
        className,
      )}
    >
      {name.slice(0, 2)}
    </span>
  );
}

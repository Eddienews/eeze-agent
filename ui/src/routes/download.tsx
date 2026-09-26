import { createFileRoute, Link } from "@tanstack/react-router";
import { Apple, Monitor, Terminal } from "lucide-react";

export const Route = createFileRoute("/download")({
  head: () => ({
    meta: [
      { title: "Download — Eeze" },
      {
        name: "description",
        content: "Eeze desktop builds for macOS, Windows and Linux — coming soon.",
      },
      { name: "robots", content: "noindex" },
    ],
  }),
  component: Download,
});

const platforms = [
  { name: "macOS", detail: "Apple silicon · macOS 14+", icon: Apple },
  { name: "Windows", detail: "Windows 11 · x64", icon: Monitor },
  { name: "Linux", detail: "Ubuntu 22.04+ · x64", icon: Terminal },
];

function Download() {
  return (
    <div
      className="min-h-screen bg-[#0a0a0a] text-neutral-200 antialiased"
      style={{
        backgroundImage: "radial-gradient(rgba(255,255,255,0.03) 1px, transparent 1px)",
        backgroundSize: "20px 20px",
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif",
      }}
    >
      <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6">
        <Link to="/" className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-white text-sm font-bold text-black">
            E
          </div>
          <span className="font-semibold tracking-tight">Eeze</span>
        </Link>
        <Link to="/demo" className="text-sm text-neutral-400 transition-colors hover:text-white">
          See the demo →
        </Link>
      </nav>

      <main className="mx-auto max-w-5xl px-6 pt-16 pb-24 md:pt-24">
        <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-neutral-800 px-3 py-1 text-xs text-neutral-400">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
          Coming soon
        </div>

        <h1 className="max-w-3xl text-4xl font-semibold leading-[1.1] tracking-tight text-white md:text-5xl">
          Download Eeze for your machine.
        </h1>
        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-neutral-400">
          Desktop builds are in internal testing. Join the private pilot and we'll send you the
          build for your platform.
        </p>

        <div className="mt-14 grid gap-6 md:grid-cols-3">
          {platforms.map((platform) => (
            <div
              key={platform.name}
              className="rounded-xl border border-neutral-800 bg-neutral-950/60 p-6"
            >
              <platform.icon className="h-8 w-8 text-neutral-300" />
              <h2 className="mt-5 text-lg font-semibold text-white">{platform.name}</h2>
              <p className="mt-1 text-sm text-neutral-500">{platform.detail}</p>
              <button
                type="button"
                disabled
                className="mt-6 w-full cursor-not-allowed rounded-lg border border-neutral-800 px-4 py-2 text-sm font-medium text-neutral-500"
              >
                Coming soon
              </button>
            </div>
          ))}
        </div>

        <p className="mt-10 text-sm text-neutral-500">
          Desktop builds are in internal testing. The demo is live today — see it in action.
        </p>
      </main>
    </div>
  );
}

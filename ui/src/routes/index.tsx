import { useState } from "react";
import { createFileRoute, Link, redirect } from "@tanstack/react-router";
import { DEMO_MODE } from "@/lib/api";
import { ContactModal } from "@/components/contact-modal";

export const Route = createFileRoute("/")({
  // The installed app opens straight on Missions; this landing only shows in the public demo.
  beforeLoad: () => {
    if (!DEMO_MODE) throw redirect({ to: "/missions" });
  },
  head: () => ({
    meta: [
      { title: "Eeze — A small team of AI agents that works on your computer" },
      {
        name: "description",
        content:
          "Self-hosted AI agents for computer-use. Runs locally, works in the background, you approve every risk.",
      },
      { name: "robots", content: "noindex" },
      { property: "og:title", content: "Eeze — AI agents that work on your computer" },
      {
        property: "og:description",
        content:
          "Self-hosted AI agents for computer-use. Runs locally, works in the background, you approve every risk.",
      },
      { property: "og:type", content: "website" },
      { property: "og:image", content: "https://eeze.app/eeze-logo.png" },
      { name: "twitter:card", content: "summary" },
      { name: "twitter:image", content: "https://eeze.app/eeze-logo.png" },
    ],
  }),
  component: Landing,
});

const principles = [
  {
    n: "01",
    title: "Runs on your machine",
    body: "No cloud. No accounts. Your data stays where it is.",
  },
  {
    n: "02",
    title: "Works in the background",
    body: "The driver operates without stealing focus. You keep working.",
  },
  {
    n: "03",
    title: "You approve every risk",
    body: "Reads and writes are automatic. Sends and payments wait for you.",
  },
];

const isList = [
  "A team of named agents (Fin, Inbox, Scout, Scribe, QA) with distinct roles.",
  "A background automation engine with a replayable audit log.",
  "Self-hosted. Works on macOS, Windows, and Linux.",
];

const isNotList = ["Not a chatbot.", "Not a cloud service.", "Not available yet."];

const infra = [
  {
    title: "Jev — the tactical brain",
    body: "Decides the next action in ~150ms. A specialized reasoning model for structured decisions — not a general-purpose chat LLM. 40× faster and 40× cheaper per decision than frontier models.",
    linkLabel: "typesafe.ai ↗",
    href: "https://typesafe.ai",
  },
  {
    title: "Cua — the hands",
    body: "An open-source computer-use driver that operates native apps in the background. No cursor stealing. No window focus changes. Works on macOS, Windows, and Linux.",
    linkLabel: "trycua/cua ↗",
    href: "https://github.com/trycua/cua",
  },
];

const comparison = [
  { label: "Decision latency", typical: "2–5 seconds", eeze: "~150 ms" },
  { label: "Cost per decision", typical: "$0.01+", eeze: "~$0.00004" },
  { label: "Focus stealing", typical: "Yes", eeze: "Never" },
  { label: "Platform", typical: "Usually one", eeze: "macOS · Windows · Linux" },
];

const status = [
  { value: "92", label: "Automated tasks" },
  { value: "77%", label: "Success rate" },
  { value: "$0.05", label: "Total cost" },
  { value: "0", label: "Focus steals" },
];

function Landing() {
  const [contactOpen, setContactOpen] = useState(false);

  return (
    <div
      className="min-h-screen bg-[#0a0a0a] text-neutral-200 antialiased"
      style={{
        backgroundImage: "radial-gradient(rgba(255,255,255,0.03) 1px, transparent 1px)",
        backgroundSize: "20px 20px",
        fontFamily: "-apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif",
      }}
    >
      {/* Nav */}
      <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-6">
        <div className="flex items-center gap-2.5">
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-[#f4f1ea]">
            <img
              src="/eeze-mark.png"
              alt=""
              width={24}
              height={24}
              aria-hidden="true"
              className="h-6 w-6"
            />
          </span>
          <span className="font-semibold tracking-tight">Eeze</span>
        </div>
        <button
          type="button"
          onClick={() => setContactOpen(true)}
          className="text-sm text-neutral-400 transition-colors hover:text-white"
        >
          Contact
        </button>
      </nav>

      {/* Hero */}
      <main className="mx-auto max-w-5xl px-6 pt-16 pb-24 md:pt-28 md:pb-32">
        <div className="mb-8 inline-flex items-center gap-2 rounded-full border border-neutral-800 px-3 py-1 text-xs text-neutral-400">
          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
          Private development preview · Not yet generally available
        </div>

        <h1 className="max-w-3xl text-4xl font-semibold leading-[1.1] tracking-tight text-white md:text-6xl">
          A small team of AI agents that works on your computer.
        </h1>

        <p className="mt-6 max-w-2xl text-lg leading-relaxed text-neutral-400 md:text-xl">
          Eeze runs locally. Each agent has a role and its own permissions. You approve anything
          risky. Every action is logged.
        </p>

        <div className="mt-10 flex flex-wrap gap-3">
          <Link
            to="/demo"
            className="rounded-lg bg-white px-5 py-2.5 text-sm font-medium text-black transition-colors hover:bg-neutral-200"
          >
            See it in action →
          </Link>
          <button
            type="button"
            onClick={() => setContactOpen(true)}
            className="rounded-lg border border-neutral-800 px-5 py-2.5 text-sm font-medium text-neutral-300 transition-colors hover:border-neutral-700 hover:text-white"
          >
            Request access
          </button>
        </div>

        {/* Three principles */}
        <div className="mt-24 grid gap-8 md:grid-cols-3">
          {principles.map((item) => (
            <div key={item.n}>
              <div className="mb-3 font-mono text-sm text-neutral-500">{item.n}</div>
              <h3 className="mb-2 font-semibold text-white">{item.title}</h3>
              <p className="text-sm leading-relaxed text-neutral-400">{item.body}</p>
            </div>
          ))}
        </div>

        {/* What it is / isn't */}
        <div className="mt-24 grid gap-12 md:grid-cols-2">
          <div>
            <h2 className="mb-5 font-mono text-xs uppercase tracking-widest text-neutral-500">
              What it is
            </h2>
            <ul className="space-y-3.5 text-neutral-300">
              {isList.map((item) => (
                <li key={item} className="flex gap-3">
                  <span className="mt-0.5 shrink-0 text-green-500">✓</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h2 className="mb-5 font-mono text-xs uppercase tracking-widest text-neutral-500">
              What it isn't
            </h2>
            <ul className="space-y-3.5 text-neutral-300">
              {isNotList.map((item) => (
                <li key={item} className="flex gap-3">
                  <span className="mt-0.5 shrink-0 text-red-400">✕</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* Under the hood */}
        <div className="mt-24 border-t border-neutral-800 pt-12">
          <h2 className="mb-5 font-mono text-xs uppercase tracking-widest text-neutral-500">
            Under the hood
          </h2>
          <p className="mb-8 text-neutral-400">
            Two pieces of open infrastructure make Eeze possible.
          </p>

          <div className="grid gap-6 md:grid-cols-2">
            {infra.map((item) => (
              <div
                key={item.title}
                className="rounded-xl border border-neutral-800 bg-neutral-950/60 p-7"
              >
                <h3 className="font-semibold text-white">{item.title}</h3>
                <p className="mt-3 text-sm leading-relaxed text-neutral-400">{item.body}</p>
                <a
                  href={item.href}
                  target="_blank"
                  rel="noopener"
                  className="mt-5 inline-flex items-center gap-1 text-sm text-neutral-300 transition-colors hover:text-white"
                >
                  {item.linkLabel}
                </a>
              </div>
            ))}
          </div>

          <div className="mt-10 overflow-x-auto rounded-xl border border-neutral-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-800 text-left">
                  <th className="px-6 py-4 font-normal text-neutral-500"> </th>
                  <th className="px-6 py-4 font-normal text-neutral-500">Typical agent</th>
                  <th className="px-6 py-4 font-medium text-white">Eeze</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-900">
                {comparison.map((row) => (
                  <tr key={row.label}>
                    <td className="px-6 py-4 text-neutral-400">{row.label}</td>
                    <td className="px-6 py-4 font-mono text-neutral-500">{row.typical}</td>
                    <td className="px-6 py-4 font-mono text-neutral-100">{row.eeze}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-8 text-sm text-neutral-500">
            Neither layer is proprietary to Eeze. Both are swappable. You own the stack.
          </p>
        </div>

        {/* Status */}
        <div className="mt-24 border-t border-neutral-800 pt-12">
          <h2 className="mb-5 font-mono text-xs uppercase tracking-widest text-neutral-500">
            Status
          </h2>
          <div className="grid max-w-3xl grid-cols-2 gap-6 md:grid-cols-4">
            {status.map((item) => (
              <div key={item.label}>
                <div className="text-2xl font-semibold tracking-tight text-white md:text-3xl">
                  {item.value}
                </div>
                <div className="mt-1 text-xs text-neutral-500">{item.label}</div>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-neutral-500">
            Internal testing in progress. Private pilot with selected users. No public signup.
          </p>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-neutral-900">
        <div className="mx-auto flex max-w-5xl flex-col items-start justify-between gap-4 px-6 py-8 text-sm text-neutral-500 md:flex-row md:items-center">
          <div className="flex items-center gap-2.5">
            <div className="flex h-5 w-5 items-center justify-center rounded bg-white text-[10px] font-bold text-black">
              E
            </div>
            <span>© 2026 Eeze</span>
          </div>
          <div className="flex items-center gap-5">
            <button
              type="button"
              onClick={() => setContactOpen(true)}
              className="transition-colors hover:text-neutral-300"
            >
              Contact
            </button>
            <Link to="/download" className="transition-colors hover:text-neutral-300">
              Download
            </Link>
          </div>
        </div>
      </footer>

      <ContactModal open={contactOpen} onOpenChange={setContactOpen} />
    </div>
  );
}

# Eeze Agent UI

Frontend for **Eeze Agent** — the local control plane for your computer-use agents
(Team Dashboard, Agent Detail, Approval Inbox, Run Viewer, Settings).
TanStack Start · React 19 · Tailwind CSS v4 · shadcn/ui — built as a static SPA and
served by the FastAPI backend, so the whole product runs 100% locally.

## Local development (hot reload)

```sh
npm install
npm run dev      # http://localhost:5173 — proxies /api to http://127.0.0.1:8765
```

Start the backend first (from the repo root): `uv run eeze api start`.

## Production build

```sh
npm run build    # SPA bundle in dist/   (or: `uv run eeze ui build` from the repo root)
```

Then `uv run eeze api start` serves everything from one place:

- `http://127.0.0.1:8765/` → the built UI (SPA fallback for client routes)
- `http://127.0.0.1:8765/api/*` → the JSON API

## Notes

- The API base URL is the relative prefix `/api` (`src/lib/api.ts`): the Vite dev
  proxy handles it in development; in production FastAPI serves SPA + API on one host.
- Mock fallbacks (`src/lib/mock-data.ts`) keep the design reviewable when the backend
  is down; with the backend running, the dashboard shows live data from the journals.
- Routes: `/` Team Dashboard · `/agents/$agentId` Agent Detail · `/inbox` Approvals ·
  `/settings`. The global command bar opens with **Ctrl+Shift+E**.

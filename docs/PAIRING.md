# Pairing: signing a browser in to Eeze

🇧🇷 [Português](pt-BR/PAIRING.md)

Eeze's dashboard runs on `http://127.0.0.1:8765` and can approve actions on your computer
(move files, spend on AI calls, send email). So a browser must be **paired** — signed in —
before it can see or do anything. Pairing is automatic in normal use.

## The automatic way (normal)

| When | What happens |
| --- | --- |
| At install | `install.cmd` finishes by opening Eeze **already paired** on the setup page. |
| Any time after | Double-click the **Eeze Agent** shortcut (Desktop or Start menu). |

Behind the scenes the shortcut runs `eeze open`, which:

1. starts the Eeze service if it is not running;
2. creates a random **one-time code** (only its SHA-256 hash is stored, in
   `~/.eeze/pair-codes.json`);
3. opens `http://127.0.0.1:8765/pair#code=…` — the page trades the code for a sign-in cookie
   and removes it from the address bar immediately.

The code works **once**, for **two minutes**, and only from this computer. The browser then
stays signed in for **30 days**.

From a terminal: `eeze open` (dashboard), `eeze open /setup` (a specific page),
`eeze open --print-only` (print the link instead of opening a browser — e.g. for a second
browser on the same PC).

## The manual way (fallback)

Use this if the shortcut is missing or you want to sign in a different browser:

1. Open `%USERPROFILE%\.eeze\api.token` in Notepad (on macOS/Linux: `~/.eeze/api.token`).
2. Copy the whole content.
3. On the **Sign in this browser** page, click *"No shortcut? Sign in with your access key"*,
   paste, and click **Sign in**.

## Security model

- The service listens on **loopback only** (`127.0.0.1`) and rejects requests from other
  machines, proxies and foreign web origins.
- `~/.eeze/api.token` is the **access key**. Anyone who can read it can control Eeze, so:
  never share it, never paste it into a chat, a website or the public demo, never commit it.
- The sign-in cookie is `HttpOnly`, `SameSite=Strict` and signed with the access key; the
  key itself is never stored in the browser.
- One-time codes add convenience without widening access: anyone able to run `eeze open` on
  your account could already read the access key.

## Signing everything out

```bash
eeze unpair
```

This replaces the access key, which **signs out every browser at once** (and invalidates
scripts using the old key). Use it if you think the key leaked, or on a shared PC. Then open
Eeze from the shortcut to sign in again.

## Settings

| Variable (in `.env`) | Default | Meaning |
| --- | --- | --- |
| `EEZE_SESSION_DAYS` | `30` | How long a browser stays signed in (1–365). |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "This link has already been used or expired" | Double-click the Eeze Agent shortcut again (codes last two minutes and work once). |
| "Could not reach Eeze on this computer" | Double-click the shortcut — it starts the service. If it persists, run `install.cmd`; logs are in `%USERPROFILE%\.eeze\api.log`. |
| Keeps asking to sign in | Cookies for `127.0.0.1` are being cleared (private window, cleaner extension). Use a normal window or allow cookies for `127.0.0.1`. |
| Signed in on `localhost:8765` but not `127.0.0.1:8765` | They are different sites to the browser. Use `http://127.0.0.1:8765` (what the shortcut opens). |
| Access key rejected | Copy the entire file content with no extra spaces. If you ran `eeze unpair`, the key changed. |

# Security policy

Eeze Agent runs on your own computer and can act on your files and apps, so security reports
are very welcome.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on this repository. Include what you found, how to
reproduce it and the impact you expect. We aim to reply within a week.

## Scope highlights

- The local service must only be reachable from the same computer (`127.0.0.1`) by a paired
  browser or a caller holding `~/.eeze/api.token` — see [docs/PAIRING.md](docs/PAIRING.md).
- Steps that change or remove files, spend money or send data out must stop for approval.
- Secrets (`.env`, `~/.eeze/secrets.json`, `~/.eeze/api.token`) must never be returned by the
  API, logged or sent anywhere except to the provider they belong to.

If you think you leaked your own access key, run `eeze unpair` to replace it.

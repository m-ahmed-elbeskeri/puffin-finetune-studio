# Security Policy

## Supported versions

This project is pre-1.0 and moves quickly. Security fixes land on `main`; please test against
the latest `main` before reporting.

| Version | Supported |
| --- | --- |
| `main` (latest) | ✅ |
| older commits / tags | ❌ |

## Reporting a vulnerability

**Please do not open a public issue, PR, or Discussion for security problems.**

Report privately through GitHub's coordinated disclosure:

1. Go to the repository's **Security** tab → **Report a vulnerability** (GitHub Private
   Vulnerability Reporting), or
2. Email the maintainer at the address on their GitHub profile.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a minimal proof of concept if possible).
- Affected component (training, serving, the Copilot backend, a provider adapter, etc.).
- Any suggested remediation.

### What to expect

- **Acknowledgement** within 3 business days.
- A fix or mitigation plan within 30 days for confirmed issues, sooner for anything actively
  exploitable.
- Credit in the release notes if you would like it (or anonymity if you prefer).

## Scope and hardening notes

This is a template you run yourself; a few defaults are worth calling out:

- **The Copilot backend binds to `127.0.0.1` by default.** If you bind a non-loopback host,
  set `PUFFIN_COPILOT_API_KEY` to require a bearer token, or you expose an unauthenticated API
  that can trigger training/deploy actions. The launcher warns you about this.
- **State-mutating tools are gated.** Destructive operations (config edits, training launch,
  deploy/promote, package install) are locked unless `PUFFIN_COPILOT_ENABLE_DANGEROUS=1`.
- **Never commit secrets.** `.env` and `.env.*` are git-ignored; use a cloud secret manager in
  production. Log redaction is available via `PUFFIN_REDACT_LOGS=true`.
- **Uploaded and generated data is path-jailed** to the project's `data/` tree.

Thank you for helping keep puffin and its users safe.

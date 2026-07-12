# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it reaches 1.0.

## [Unreleased]

Nothing yet. Open a PR or an issue to shape the next release.

## [0.2.1] - 2026-07-12

### Fixed
- `finetune-copilot` no longer crashes with `EADDRINUSE` when the frontend port
  is held by an IPv6 (`::`) listener (e.g. a leftover Next dev server). Port
  availability is now checked across every interface and address family before
  binding, so the launcher auto-bumps to the next free port. The dev server also
  binds the same host it probes (loopback by default).

## [0.2.0] - 2026-07-11

### Changed
- Repositioned the product as **Puffin Studio**: the web studio is the main way to use the
  platform, backed by the `llmops` engine (which still runs headless via the `puffin` CLI).
  README, package/repo descriptions, and the in-app branding now lead with the studio; the
  AI chat is "the copilot".
- CI is green end to end (lint + unit tests, data + eval smoke, docker builds).

### Fixed
- Declared the previously-missing `ruamel.yaml` dependency.
- Packaging excludes the frontend's `node_modules`/build artifacts so `python -m build`
  is fast and the wheel is lean.

## [0.1.0] - 2026-07-11

Initial public release (matches `pyproject.toml` `version = "0.1.0"`).

### Added
- Golden-path LLM fine-tuning platform: config-driven SFT / LoRA / DPO with reproducible
  lineage, a hard promotion gate (task / safety / regression / latency), a model registry, and
  cloud-portable serving with `local` / `gcp` / `aws` / `azure` / `kubernetes` adapters.
- `finetune-copilot` command: one command that starts the backend and web UI, waits for both,
  and opens the browser. Dev mode (hot reload) and `--prod` single-origin static mode, plus
  `doctor` and `build` subcommands.
- The Copilot: a Next.js + FastAPI dashboard with an AI chat that has tool-use access to the
  whole `llmops.*` codebase, and a point-and-click Train Studio.
- Community health files: contributing guide, security policy, code of conduct, issue and PR
  templates.

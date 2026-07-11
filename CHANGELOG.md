# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it reaches 1.0.

## [Unreleased]

Nothing yet. Open a PR or an issue to shape the next release.

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

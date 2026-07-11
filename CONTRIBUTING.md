# Contributing to puffin-finetune-studio

Thanks for taking the time to contribute. This project aims to be a calm, well-tested
golden path, so the bar for changes is "keeps the path golden": reproducible, typed,
tested, and documented. This guide gets you productive fast.

## Ways to contribute

- **Report a bug** using the issue template (include repro steps and versions).
- **Propose a feature** or a new recipe/provider adapter via a feature-request issue first,
  so we can agree on the shape before you build.
- **Improve docs** (README, runbooks, docstrings). Small doc PRs are always welcome.
- **Send code**: pick a [`good first issue`](https://github.com/m-ahmed-elbeskeri/puffin-finetune-studio/labels/good%20first%20issue)
  or comment on an open issue to claim it.

## Development setup

```bash
git clone https://github.com/m-ahmed-elbeskeri/puffin-finetune-studio
cd puffin-finetune-studio
cp .env.example .env

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,train,copilot]"
```

The Makefile (`make.ps1` on Windows) wraps the common tasks:

```bash
make setup        # install extras
make lint         # ruff
make typecheck    # mypy on src/llmops
make test-fast    # unit tests, no slow/gpu/integration markers
make test         # full suite
```

To work on the Copilot UI:

```bash
finetune-copilot           # backend + UI, opens the browser
finetune-copilot doctor    # verify Node, deps, ports, API key
```

## Before you open a PR

Please make sure the following are green locally:

```bash
make lint
make typecheck
make test-fast
```

Then:

1. **Branch** from `main` (`git switch -c feat/short-name`). Do not commit to `main`.
2. **Keep the diff focused.** One logical change per PR. Split refactors from features.
3. **Add or update tests** for any behavior change. New tools/endpoints need coverage.
4. **Update docs** (README, `copilot/README.md`, docstrings) when behavior changes.
5. **Write a clear PR description** using the template: what, why, and how you verified it.

## Coding standards

- **Python 3.11+.** Type-hint public functions; `make typecheck` must pass.
- **Style:** [ruff](https://github.com/astral-sh/ruff) for lint and import order
  (`line-length = 100`). Run `ruff check --fix` before pushing.
- **Tests:** [pytest](https://pytest.org). Prefer fast, deterministic unit tests; mark slow or
  environment-dependent tests with `@pytest.mark.slow` / `integration` / `gpu` / `network`.
- **No secrets in the repo.** Use `.env` (git-ignored) or a cloud secret manager.
- **Prefer config over code.** Most changes should be expressible in `configs/*.yaml`. If you
  find yourself editing training/serving logic to support a new project, that is a signal the
  change belongs in the shared feature layer, not a fork.
- **Frontend:** TypeScript, `npm run lint` and `npm run typecheck` in `copilot/frontend/`.

## Commit messages

Conventional-commit style is appreciated but not enforced:
`feat: ...`, `fix: ...`, `docs: ...`, `test: ...`, `refactor: ...`, `chore: ...`.
Keep the subject under ~72 chars and explain the "why" in the body.

## Review and merge

- CI (`llmops-ci`) runs lint + unit tests on every PR; it must be green.
- A maintainer will review for correctness, tests, and scope. Expect a round or two of
  feedback, it is how we keep the path golden.
- We squash-merge; your PR title becomes the commit subject.

## Reporting security issues

Do **not** open a public issue for vulnerabilities. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions are licensed under the
[Apache 2.0](LICENSE) license.

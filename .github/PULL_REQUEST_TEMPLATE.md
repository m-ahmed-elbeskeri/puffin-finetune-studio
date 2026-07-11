<!-- Thanks for contributing! Keep PRs focused: one logical change each. -->

## What & why

<!-- What does this change, and what problem does it solve? Link the issue: Closes #123 -->

## How I verified it

<!-- Commands you ran, tests you added, screenshots for UI changes. -->

```bash
make lint
make typecheck
make test-fast
```

## Checklist

- [ ] Branched from `main`; diff is focused on one change
- [ ] Added/updated tests for the behavior change
- [ ] Updated docs (README / copilot/README / docstrings) if behavior changed
- [ ] `make lint`, `make typecheck`, `make test-fast` pass locally
- [ ] No secrets, credentials, or large binaries committed
- [ ] For config-shaped changes: expressed in `configs/*.yaml` rather than forked logic

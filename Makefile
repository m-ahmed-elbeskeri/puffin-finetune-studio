PYTHON ?= python
PROFILE ?= local
ENV ?= dev

.PHONY: help setup install install-train install-serve install-eval install-all install-copilot lint typecheck format test test-fast cov data-validate data-build train-smoke train evaluate gate serve docker-build-train docker-build-serve docker-build-eval docker-build clean

help:
	@echo "puffin-finetune-studio — common targets"
	@echo ""
	@echo "Setup:"
	@echo "  setup           Create venv + install dev/data/eval extras (uv)"
	@echo "  install         Install editable package (no extras)"
	@echo "  install-train   Install with [train] extras"
	@echo "  install-serve   Install with [serve] extras"
	@echo "  install-eval    Install with [eval] extras"
	@echo "  install-all     Install with [all,dev] extras"
	@echo ""
	@echo "Quality:"
	@echo "  lint            Run ruff check + ruff format check + mypy"
	@echo "  typecheck       Run mypy on src/llmops"
	@echo "  format          Auto-format and auto-fix lints"
	@echo "  test            Run pytest with coverage"
	@echo "  test-fast       Run only fast unit tests (exclude integration/gpu/network/slow)"
	@echo "  cov             Coverage report (HTML)"
	@echo ""
	@echo "Data:"
	@echo "  data-validate   Validate raw data against schema"
	@echo "  data-build      Run full data pipeline (ingest → redact → dedupe → split → card)"
	@echo ""
	@echo "Train + eval:"
	@echo "  train-smoke     Tiny CPU-friendly training smoke test"
	@echo "  train           Real training using configs/train.yaml"
	@echo "  evaluate        Run task + safety + regression + latency evals"
	@echo "  gate            Apply promotion gate"
	@echo ""
	@echo "Serve:"
	@echo "  serve           Start FastAPI serving app"
	@echo ""
	@echo "Docker:"
	@echo "  docker-build    Build train/serve/eval images"
	@echo ""
	@echo "Other:"
	@echo "  clean           Remove caches, build artifacts, mlruns"

setup:
	uv venv .venv
	uv pip install -e ".[data,eval,dev]"

install:
	$(PYTHON) -m pip install -e .

install-train:
	$(PYTHON) -m pip install -e ".[train,data,eval,mlflow]"

install-serve:
	$(PYTHON) -m pip install -e ".[serve]"

install-eval:
	$(PYTHON) -m pip install -e ".[eval,data]"

install-all:
	$(PYTHON) -m pip install -e ".[all,dev]"

lint:
	ruff check src tests
	ruff format --check src tests
	mypy src/llmops || true

typecheck:
	mypy src/llmops

format:
	ruff check --fix src tests
	ruff format src tests

test:
	pytest tests --cov=src/llmops --cov-report=term-missing

test-fast:
	pytest tests -m "not gpu and not network and not slow and not integration" -x

cov:
	pytest tests --cov=src/llmops --cov-report=html
	@echo "Open htmlcov/index.html"

data-validate:
	$(PYTHON) -m llmops.data.validate --config configs/data.yaml

data-build:
	$(PYTHON) -m llmops.data.ingest    --config configs/data.yaml
	$(PYTHON) -m llmops.data.redact_pii --config configs/data.yaml
	$(PYTHON) -m llmops.data.dedupe     --config configs/data.yaml
	$(PYTHON) -m llmops.data.split      --config configs/data.yaml
	$(PYTHON) -m llmops.data.build_dataset_card --config configs/data.yaml

train-smoke:
	$(PYTHON) -m llmops.training.train_sft_lora --config configs/train.yaml --smoke-test

train:
	$(PYTHON) -m llmops.training.train_sft_lora --config configs/train.yaml

evaluate:
	$(PYTHON) -m llmops.evaluation.task_eval       --config configs/eval.yaml
	$(PYTHON) -m llmops.evaluation.safety_eval     --config configs/eval.yaml
	$(PYTHON) -m llmops.evaluation.regression_eval --config configs/eval.yaml
	$(PYTHON) -m llmops.evaluation.latency_eval    --config configs/eval.yaml

gate:
	$(PYTHON) -m llmops.evaluation.gate --config configs/eval.yaml --metrics artifacts/eval/metrics.json

serve:
	$(PYTHON) -m llmops.serving.app --config configs/deploy.yaml

docker-build-train:
	docker build -f infra/docker/Dockerfile.train -t puffin-train:latest .

docker-build-serve:
	docker build -f infra/docker/Dockerfile.serve -t puffin-serve:latest .

docker-build-eval:
	docker build -f infra/docker/Dockerfile.eval -t puffin-eval:latest .

docker-build: docker-build-train docker-build-serve docker-build-eval

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

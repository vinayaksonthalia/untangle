# untangle — developer run targets (constitution V: clone-and-run in one command)
# Uses a local venv if present, else falls back to python3.
PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

BANK   ?= data/bank_statement.csv
RECON  ?= data/recon_report.json
LEDGER ?= data/order_ledger.csv
TRUTH  ?= data/ground_truth.json
OUT    ?= out/
SEED   ?= 42

.PHONY: help venv run eval ablation test lint why clean

help:
	@echo "make venv     - create .venv and install dev deps (pytest, hypothesis, ruff)"
	@echo "make run      - deterministic no-AI attribution -> out/report.json"
	@echo "make eval     - score out/report.json against blind ground truth"
	@echo "make ablation - eval with AI on/off delta + latency + cost/1k"
	@echo "make test     - run the full pytest suite"
	@echo "make lint     - ruff check"

venv:
	python3 -m venv .venv
	.venv/bin/python -m pip install -q --upgrade pip pytest hypothesis ruff

run:
	$(PY) -m engine.cli run --bank $(BANK) --recon $(RECON) --ledger $(LEDGER) \
	  --out $(OUT) --no-ai --seed $(SEED)

eval:
	$(PY) -m eval.harness --run $(OUT)report.json --truth $(TRUTH)

ablation:
	$(PY) -m eval.harness --run $(OUT)report.json --truth $(TRUTH) --ablation

why:
	$(PY) -m engine.cli why $(KEY) --out $(OUT)

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check engine eval tests

clean:
	rm -rf out/ .pytest_cache __pycache__ */__pycache__ */*/__pycache__

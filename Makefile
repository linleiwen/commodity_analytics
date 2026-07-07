RUN_ID ?= 2026-07-japan-trip
PY ?= python
OUT ?= data/exports/japan_dmv_product_rankings.xlsx
QA  ?= data/exports/qa_report.md

.PHONY: install install-dev test lint init-db seeds normalize score export qa run-all clean

install:
	$(PY) -m pip install -e .

install-dev:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest

init-db:
	$(PY) -m app.cli init-db

seeds:
	$(PY) -m app.cli import-seeds --file config/keyword_seeds.yaml

manual-import:
	$(PY) -m app.cli manual-import --type field_prices --file data/manual_imports/japan_store_prices.csv --run-id $(RUN_ID)
	$(PY) -m app.cli manual-import --type terapeak      --file data/manual_imports/terapeak.csv         --run-id $(RUN_ID)
	$(PY) -m app.cli manual-import --type social_notes  --file data/manual_imports/xhs_notes.csv         --run-id $(RUN_ID)

normalize:
	$(PY) -m app.cli normalize --run-id $(RUN_ID)

score:
	$(PY) -m app.cli score --run-id $(RUN_ID)

export:
	$(PY) -m app.cli export-xlsx --run-id $(RUN_ID) --out $(OUT)

qa:
	$(PY) -m app.cli qa-report --run-id $(RUN_ID) --out $(QA)

run-all:
	$(PY) -m app.cli run-all --run-id $(RUN_ID)

clean:
	$(PY) -c "import shutil,glob,os; [os.remove(p) for p in glob.glob('data/*.sqlite')]; [shutil.rmtree(p,ignore_errors=True) for p in glob.glob('**/__pycache__',recursive=True)]"

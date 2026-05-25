.PHONY: help setup test dry-run run clean

PYTHON := .venv/bin/python

help:
	@echo "Crypto Meme Bot — make targets"
	@echo ""
	@echo "  make setup     create venv, install deps, scaffold .env"
	@echo "  make test      run the pytest suite"
	@echo "  make dry-run   run the pipeline once (no Telegram, no X)"
	@echo "  make run       start the bot for real (scheduler + Telegram polling)"
	@echo "  make clean     remove venv, __pycache__, *.db, logs/*"
	@echo ""
	@echo "First time? Read README.md, then run 'make setup'."

setup:
	@./scripts/setup.sh

test:
	@$(PYTHON) -m pytest -v

dry-run:
	@$(PYTHON) -m src.main --dry-run

run:
	@$(PYTHON) -m src.main

clean:
	rm -rf .venv
	find . -type d -name "__pycache__" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	rm -f data/*.db
	rm -f logs/*.log
	@echo "cleaned: venv, __pycache__, .pytest_cache, data/*.db, logs/*.log"

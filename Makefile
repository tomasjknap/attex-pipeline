SHELL = /usr/bin/env sh
MAKEFLAGS += --silent

.PHONY: install check format

install:
	uv sync

check:
	uv run ruff format --preview --check src

format:
	uv run ruff format --preview src

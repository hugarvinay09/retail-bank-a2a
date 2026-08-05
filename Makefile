.PHONY: install lint format type test test-all run migrate ingest compose-up compose-down docker-build

install:
	uv sync --all-extras

lint:
	uv run ruff check .

format:
	uv run ruff format .

type:
	uv run mypy src

test:
	uv run pytest -m "not integration and not live" --cov --cov-report=term-missing

test-all:
	uv run pytest --cov --cov-report=term-missing

run:
	uv run uvicorn retail_bank_agents.main:app --reload --host 0.0.0.0 --port 8080

migrate:
	uv run alembic upgrade head

ingest:
	uv run bank-agent-ingest

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

docker-build:
	docker build -t retail-bank-a2a:local .


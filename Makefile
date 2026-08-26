.PHONY: install dev lint format test run docker-build docker-run

install:
	pip install -e .

dev:
	pip install -e ".[dev]"
	pre-commit install

lint:
	ruff check .
	black --check .
	mypy app

format:
	ruff check --fix .
	black .

test:
	pytest

run:
	uvicorn app.main:app --reload

docker-build:
	docker build -t eve-build .

docker-run:
	docker compose up --build

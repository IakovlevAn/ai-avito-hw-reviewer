.PHONY: install dev-api dev-web test build-web docker-build

install:
	uv sync --dev
	cd web && npm install

dev-api:
	uv run uvicorn app.main:app --reload

dev-web:
	cd web && npm run dev

test:
	uv run pytest
	cd web && npm run build

build-web:
	cd web && npm run build

docker-build:
	docker compose build

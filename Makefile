install:
	pip install -r requirements.txt
	python -m copilot download-runtime

run:
	uvicorn app.main:app

dev-reload:
	uvicorn app.main:app --reload --reload-dir app

mcp:
	python -m mcp_servers.engineering_server

test:
	pytest -q

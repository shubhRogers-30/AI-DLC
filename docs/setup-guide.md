# AI-DLC Reference Implementation Setup Guide

This guide explains how to run the AI-DLC Reference Implementation locally for a project demonstration or evaluation. The application includes a Python API and an optional Angular web console. For a first run, use mock mode: it does not require Jira, GitHub, SonarQube, or GitHub Copilot credentials.

## 1. Project Overview

The application demonstrates a human-reviewed software delivery workflow:

1. Load a Jira story and derive requirements.
2. Propose an architecture and pause for human approval.
3. Plan and implement changes, then run tests.
4. Prepare a pull request and quality checks, then pause for final human approval.

The backend is built with Python, FastAPI, and LangGraph. The optional frontend is an Angular web console. The workflow is designed to require human approvals; final approval does not automatically merge a pull request.

## 2. Prerequisites

- Git
- Python 3.11 or later
- Node.js 20.19 or later and earlier than 23, plus npm (only for the web console)
- A terminal such as PowerShell, Command Prompt, or a macOS/Linux shell

For the mock-mode demonstration, no third-party accounts or API credentials are required. Real integrations have additional setup requirements described in the project [README](../README.md).

## 3. Get the Project

If you have access to the Git repository, clone it and enter its directory:

```powershell
git clone <repository-url>
cd <repository-folder>
```

Alternatively, extract the project archive provided to you and open a terminal in the extracted project folder. Run the commands below from the folder containing `requirements.txt` and `app/`.

## 4. Configure the Backend

Create a Python virtual environment and install the dependencies.

**Windows PowerShell:**

```powershell
py -3 -m venv .venv
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

**macOS/Linux:**

```bash
python3 -m venv .venv
cp .env.example .env
./.venv/bin/python -m pip install -r requirements.txt
```

Open `.env` and keep `MOCK_MODE=true`. Set `API_TOKEN` to a local value of your choice, for example:

```dotenv
MOCK_MODE=true
API_TOKEN=local-demo-token
```

The web console requires a non-empty API token. This token is only for local use; do not reuse a personal password or share a populated `.env` file. Leave the Jira, GitHub, and SonarQube credential fields empty for the mock-mode demonstration.

## 5. Start and Verify the Backend

Open a terminal in the project folder and start the API.

**Windows PowerShell:**

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**macOS/Linux:**

```bash
./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep this terminal open. Visit these URLs in a browser:

- API health: <http://127.0.0.1:8000/health>
- Interactive API documentation: <http://127.0.0.1:8000/docs>

The health endpoint should return a response indicating `status` is `ok` and `mock_mode` is `true`.

## 6. Start the Web Console (Optional)

Open a second terminal in the project folder, then install and start the frontend.

```powershell
Set-Location frontend
npm ci
npm start
```

The commands are the same on macOS/Linux. Open <http://127.0.0.1:4200/> and enter:

- API URL: `http://127.0.0.1:4200` (the development server forwards API requests to the backend)
- API bearer token: the value you set for `API_TOKEN` in `.env`

Select **Connect** to load the available mock data. In mock mode, the Jira issue list includes the sample issue `DEMO-101`. Keep both the backend and frontend terminals running while using the console.

## 7. Run the Tests (Optional)

From the project root, run:

**Windows PowerShell:**

```powershell
.\.venv\Scripts\python.exe -m pytest tests
```

**macOS/Linux:**

```bash
./.venv/bin/python -m pytest tests
```

## 8. Troubleshooting

- **`py` or `python3` is not found:** Install Python 3.11 or later and ensure it is available on your terminal's `PATH`.
- **The backend reports an authentication error:** Confirm `API_TOKEN` is set in `.env`, then stop and restart the backend. Environment changes are read when the application starts.
- **The console cannot connect:** Confirm the backend is running on port 8000, the console is running on port 4200, and the token entered in the console exactly matches `.env`.
- **`npm ci` reports an unsupported Node version:** Install Node.js 20.19 or later, but earlier than 23, and rerun `npm ci` from the `frontend` directory.
- **Port 8000 or 4200 is already in use:** Stop the process using that port before starting this application.

## 9. Important Safety Note

Keep `MOCK_MODE=true` for a classroom or local demonstration. Real mode can access external services and execute repository build commands. Enabling it requires properly configured credentials, an approved sandbox repository, and review of the project's security guidance. Do not expose the local API to the public internet or use production credentials for a demonstration.
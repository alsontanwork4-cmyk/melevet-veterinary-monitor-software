# Melevet Veterinary Monitor Platform

Melevet Veterinary Monitor Platform is a full-stack web application for importing Melevet veterinary monitor exports, storing decoded data, and visualizing patient trend information.

It includes:

- A FastAPI backend for upload processing, decoding, patient management, encounter management, and CSV export
- A React + Vite frontend for uploading monitor files, browsing patients, and reviewing trend data
- Sample Melevet record files for local testing

## What the Application Does

The application is designed to work with exported monitor record files such as:

- `TrendChartRecord.data` and `TrendChartRecord.Index`
- `NibpRecord.data` and `NibpRecord.Index`
- `AlarmRecord.data` and `AlarmRecord.Index`

These files can be uploaded into the system so users can:

- Register and manage patient records
- Upload monitor sessions
- Discover channels and recorded periods from an upload
- Create encounters from uploaded sessions
- Review trend measurements, NIBP events, and alarms
- Export decoded or filtered data for further analysis

## Technology Stack

### Backend

- Python
- FastAPI
- SQLAlchemy
- Alembic
- SQLite

### Frontend

- React
- TypeScript
- Vite
- React Query
- ECharts

## Project Structure

```text
.
|-- backend/    FastAPI application, database, API routes, tests
|-- frontend/   React application
|-- Records/    Sample Melevet monitor export files
|-- scripts/    Utility scripts
|-- output/     Generated output artifacts
|-- README.md
```

## Prerequisites

Install the following before running the project:

- Python 3.11 or newer
- Node.js 18 or newer
- npm

## Local Setup

### 1. Clone the repository

```powershell
git clone <your-repository-url>
cd melevet-veterinary-monitor
```

If you already downloaded the project as a folder, open a terminal in the project root instead.

### 2. Set up the backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

The backend uses SQLite by default, so no separate database server is required for local development.
The default `DATABASE_URL=sqlite:///./melevet.db` is resolved from the `backend` working directory, so starting Uvicorn from `backend` creates or opens `backend/melevet.db`.
Authentication is enabled by default. Before the first startup, set `AUTH_BOOTSTRAP_USERNAME` and `AUTH_BOOTSTRAP_PASSWORD` in `backend/.env` so the initial login user can be created automatically.

### 3. Set up the frontend

Open a second terminal:

```powershell
cd frontend
npm install
Copy-Item .env.example .env
```

## Running the Application

You need both the backend and frontend running at the same time.

### Start the backend

From the `backend` folder:

```powershell
.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

Backend endpoints will be available at:

- API base URL: `http://localhost:8000/api`
- Health check: `http://localhost:8000/health`

### Start the frontend

From the `frontend` folder:

```powershell
npm run dev
```

The frontend will usually start at:

- `http://localhost:5173`

## Windows Local App Scaffold

For the single-PC Windows install flow, launcher and packaging scaffolding now lives in [`scripts/local_app/`](./scripts/local_app).

Key entry points:

- `scripts/local_app/launch_melevet.ps1`
- `scripts/local_app/package_local_app.ps1`
- `scripts/local_app/create_shortcuts.ps1`

### One-click local launch

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local_app\launch_melevet.ps1
```

What the launcher does:

- reuses an already-running local Melevet instance if `http://127.0.0.1:8000/health` is healthy
- opens the browser automatically
- stores runtime data under `%LOCALAPPDATA%\Melevet\`
- writes backend stdout/stderr logs under `%LOCALAPPDATA%\Melevet\logs\`

### Package scaffold for a Windows install

To create a distributable folder scaffold:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local_app\package_local_app.ps1
```

This creates `output\local-app-package\Melevet\` with:

- the built frontend assets
- the backend source tree
- the launcher scripts
- packaging notes for where the self-contained backend executable should be placed

Create desktop and Start Menu shortcuts for a packaged install with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local_app\create_shortcuts.ps1 -InstallRoot C:\Path\To\Melevet
```

## How to Use the System

### Option 1: Upload monitor files directly

1. Start the backend and frontend.
2. Open the frontend in your browser.
3. Go to the upload workflow.
4. Select the Melevet export files you want to import.
5. Submit the upload and wait for processing to finish.
6. Open the discovery or report views to inspect periods, channels, trends, alarms, and NIBP data.

### Option 2: Manage patient-linked uploads

1. Create or select a patient from the patient list.
2. Upload a monitor session for that patient.
3. Review the discovered recording data.
4. Create an encounter from the uploaded session.
5. Open the encounter report page to review measurements and export data if needed.

## Sample Data

Sample monitor exports are included in the [`Records/`](./Records) folder:

- `Records/TrendChartRecord.data`
- `Records/TrendChartRecord.Index`
- `Records/NibpRecord.data`
- `Records/NibpRecord.Index`
- `Records/AlarmRecord.data`
- `Records/AlarmRecord.Index`

These files can be used for local testing and demonstration of the upload and decoding flow.

## Configuration

### Backend environment variables

The backend reads configuration from `backend/.env`.

Default example values:

```env
APP_NAME=Melevet Monitor Platform
API_PREFIX=/api
DATABASE_URL=sqlite:///./melevet.db
CORS_ORIGINS=http://localhost:5173
AUTH_BOOTSTRAP_USERNAME=admin
AUTH_BOOTSTRAP_PASSWORD=change-me-before-sharing
CHANNEL_MAP_PATH=channel_map.json
RECORDING_PERIOD_GAP_SECONDS=86400
SEGMENT_GAP_SECONDS=600
INVALID_U16_VALUES=65535,21845
UPLOAD_TIMEOUT_SECONDS=180
MEASUREMENT_INSERT_BATCH_SIZE=5000
EVENT_INSERT_BATCH_SIZE=1000
```

On a fresh database, startup will fail if the `users` table is empty and the bootstrap credentials are missing. After the first user is created, later restarts can succeed without those variables as long as the database still contains at least one user.

### Frontend environment variables

The frontend reads configuration from `frontend/.env`.

Default example value:

```env
VITE_DEV_API_ORIGIN=http://localhost:8000
```

Production defaults to same-origin `/api`. If `VITE_API_BASE_URL` is set, it must be a relative path or an HTTPS URL. Plain HTTP is only accepted for localhost development.

### Security Baseline

- Frontend dev and preview now emit baseline security headers (`Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`).
- The frontend no longer depends on Google Fonts and only loads local assets by default.
- Backend dependencies are pinned in `backend/requirements.lock` for CI and reproducible installs.

To install the backend with pinned versions:

```powershell
cd backend
.venv\Scripts\Activate.ps1
pip install -r requirements.lock
```

## Channel Mapping

Channel name mapping can be edited in `backend/app/channel_map.json`.

If a channel is not mapped, it remains available using its raw source name.

## Available Backend Capabilities

The backend currently provides endpoints for:

- Patient management
- Upload creation and deletion
- Upload discovery and measurement browsing
- Encounter creation, update, deletion, and reporting
- Alarm and NIBP event retrieval
- CSV export
- Decode job creation and downloadable decode output

## Running Tests

### Backend tests

```powershell
cd backend
.venv\Scripts\Activate.ps1
pytest -q
```

### Frontend tests

```powershell
cd frontend
npm test
```

## Troubleshooting

### Frontend cannot connect to backend

Check that:

- The backend is running on port `8000`
- `frontend/.env` points to `http://localhost:8000/api`
- `backend/.env` allows `http://localhost:5173` in `CORS_ORIGINS`

### Upload succeeds but data looks incomplete

Check that you uploaded matching `.data` and `.Index` files for the same record type.

### Database file location

By default, the SQLite database is created at:

- `backend/melevet.db`

If startup fails with `Authentication is enabled but no users exist`, check that:

- `backend/.env` exists
- `AUTH_BOOTSTRAP_USERNAME` and `AUTH_BOOTSTRAP_PASSWORD` are set in `backend/.env`
- you started the backend from the `backend` folder so `sqlite:///./melevet.db` resolves to `backend/melevet.db`

## Notes

- SQLite is used for local development by default.
- The backend automatically initializes required database tables on startup.
- This repository includes sample data for testing the upload flow locally.

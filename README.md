# CAO 48.1 Compliance API

A stateless REST API for validating flight crew duty periods against the Australian **Civil Aviation Order 48.1 Instrument 2019** (Compilation No. 3, F2021C01239).

Designed for deployment on [RapidAPI Hub](https://rapidapi.com/).

## Features

- **Regulatory Content** — query the text of CAO 48.1 sections and appendices
- **Calculation** — calculate maximum FDP limits and minimum off-duty periods
- **Validation** — validate duty periods, cumulative limits, and full rosters
- **Clause-referenced** — every check result cites the specific CAO 48.1 clause

Covers Appendices 1 through 6 (Basic Limits, Multi-Pilot, Any Operations, Balloon, Medical Transport, Aerial Work, Daylight Aerial Work, Flight Training).

## Quick Start

### Local Development

```bash
# Clone and enter the project
cd cao481-api

# Copy environment file
cp .env.example .env

# Option 1: Docker Compose (recommended)
docker compose up --build

# Option 2: Direct Python
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

### Verify It Works

```bash
# Health check
curl http://localhost:8000/api/v1/cao481/health | python -m json.tool

# OpenAPI spec (this is what gets uploaded to RapidAPI)
curl http://localhost:8000/openapi.json | python -m json.tool

# Interactive docs
open http://localhost:8000/docs
```

### Run Tests

```bash
pip install pytest httpx
pytest tests/ -v
```

## RapidAPI Deployment

### 1. Deploy the Docker Container

Host the container on any cloud provider with HTTPS:
- AWS ECS / Fargate
- Google Cloud Run
- Railway
- Render
- DigitalOcean App Platform

The container exposes port 8000 and includes a built-in health check.

### 2. Register on RapidAPI Hub

1. Go to [rapidapi.com/studio](https://rapidapi.com/studio)
2. Click **Add API Project**
3. Name: `CAO 48.1 Compliance` / Category: `Other`
4. Import the OpenAPI spec from your deployed instance: `https://your-domain.com/openapi.json`

### 3. Configure Settings

In the RapidAPI Provider Dashboard:

- **Base URL**: `https://your-domain.com`
- **Security**: Copy the `X-RapidAPI-Proxy-Secret` and set it as the `RAPIDAPI_PROXY_SECRET` environment variable on your server
- **Environment**: Set `ENVIRONMENT=production` on your server

### 4. Set Pricing (Optional)

Configure tiers in the RapidAPI Monetisation tab.

## Project Structure

```
cao481-api/
├── app/
│   ├── __init__.py
│   ├── config.py          # Pydantic Settings configuration
│   ├── main.py            # FastAPI application and endpoints
│   ├── middleware.py       # RapidAPI proxy secret validation
│   └── models/
│       ├── __init__.py
│       └── health.py      # Health endpoint response models
├── tests/
│   ├── __init__.py
│   └── test_health.py     # Health endpoint tests
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── README.md
└── requirements.txt
```

## Build Phases

| Phase | Scope | Status |
|-------|-------|--------|
| **0** | Health endpoint + skeleton + Docker + RapidAPI deploy | ✅ Complete |
| **1** | Regulatory content + FDP table lookups | 🔲 Planned |
| **2** | Max FDP / min off-duty calculators | 🔲 Planned |
| **3** | FDP and off-duty validation | 🔲 Planned |
| **4** | Cumulative and sequence validation | 🔲 Planned |
| **5** | Full roster validation | 🔲 Planned |
| **6** | MCP server wrapper | 🔲 Planned |

## Disclaimer

This API is derived from CAO 48.1 Instrument 2019 and is provided for reference purposes only. It does not replace your operator's approved Fatigue Management Manual (FMM), a qualified fatigue risk management assessment, or professional regulatory advice. Always verify compliance with your operator's approved procedures and the current in-force legislation.

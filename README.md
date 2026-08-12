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
4. Import the OpenAPI spec from your deployed instance: `https://cao481-api.jwboon.workers.dev/openapi.json`

### 3. Configure Settings

In the RapidAPI Provider Dashboard:

- **Base URL**: `https://cao481-api.jwboon.workers.dev`
- **Security**: Copy the `X-RapidAPI-Proxy-Secret` and set it as the `RAPIDAPI_PROXY_SECRET` environment variable on your server
- **Environment**: Set `ENVIRONMENT=production` on your server

### 4. Set Pricing (Optional)

Configure tiers in the RapidAPI Monetisation tab.

## Endpoints

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cao481/health` | API status and feature discovery |

### Regulatory Content
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cao481/sections` | Table of contents for CAO 48.1 |
| GET | `/api/v1/cao481/sections/{section_id}` | Full text of a specific section or appendix |

### Limits (Reference Data)
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cao481/limits/fdp-table/{appendix}` | FDP lookup table for an appendix |
| GET | `/api/v1/cao481/limits/cumulative/{appendix}` | Cumulative limit thresholds |

### Calculation
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/cao481/calculate/max-fdp` | Calculate maximum permissible FDP |
| POST | `/api/v1/cao481/calculate/min-off-duty` | Calculate minimum required off-duty period |

### Validation
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/cao481/validate/fdp` | Validate a single FDP against calculated limits |
| POST | `/api/v1/cao481/validate/off-duty` | Validate an off-duty period against minimum requirements |
| POST | `/api/v1/cao481/validate/cumulative` | Check rolling-window cumulative limits against a log or summary |
| POST | `/api/v1/cao481/validate/sequence` | Validate a chronological FDP/ODP sequence including §13.2 WOCL and consecutive-start rules |
| POST | `/api/v1/cao481/validate/roster` | Full roster validation — all FDPs, ODPs and rest days in one call |

### Guide
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cao481/guide` | Structured usage guide for all endpoints — purpose, parameters, examples, common mistakes |

## Project Structure

```
cao481-api/
├── app/
│   ├── __init__.py
│   ├── config.py              # Pydantic Settings configuration
│   ├── main.py                # FastAPI application and endpoint wiring
│   ├── middleware.py           # RapidAPI proxy secret validation
│   ├── parser.py              # CAO 48.1 markdown legislation parser
│   ├── data/
│   │   ├── cao481.md          # Full CAO 48.1 legislation text
│   │   ├── fdp_tables.py      # FDP lookup tables for all 9 appendices
│   │   ├── cumulative_limits.py # Cumulative flight/duty time thresholds
│   │   ├── off_duty_rules.py  # Off-duty period rules per appendix
│   │   └── guide.py           # /guide endpoint content
│   ├── engines/
│   │   ├── fdp_calculator.py  # Max FDP calculation logic
│   │   ├── off_duty_calculator.py # Min off-duty calculation logic
│   │   ├── fdp_validator.py   # FDP validation logic
│   │   ├── off_duty_validator.py  # Off-duty validation logic
│   │   ├── cumulative_validator.py # Rolling-window cumulative limits validator
│   │   ├── sequence_validator.py  # Ordered FDP/ODP sequence validator
│   │   └── roster_validator.py    # Full roster validation (Phase 5)
│   ├── models/
│   │   ├── health.py          # Health endpoint response models
│   │   ├── sections.py        # Regulatory content response models
│   │   ├── limits.py          # Limits endpoint response models
│   │   ├── calculation.py     # Calculation request/response models
│   │   └── validation.py      # Validation request/response models
│   └── routes/
│       ├── limits.py          # /limits/* route handlers
│       ├── calculate.py       # /calculate/* route handlers
│       ├── validate.py        # /validate/* route handlers
│       └── guide.py           # /guide route handler
├── tests/
│   ├── test_health.py         # Health endpoint + middleware tests
│   ├── test_sections.py       # Regulatory content tests
│   ├── test_limits_endpoints.py        # Limits endpoint tests
│   ├── test_fdp_calculator.py          # FDP calculation engine tests
│   ├── test_off_duty_calculator.py     # Off-duty calculation engine tests
│   ├── test_calculate_endpoints.py     # Calculation endpoint tests
│   ├── test_fdp_validator.py           # FDP validation engine tests
│   ├── test_off_duty_validator.py      # Off-duty validation engine tests
│   ├── test_validate_endpoints.py      # Validation endpoint tests (Phase 3)
│   ├── test_cumulative_validator.py    # Cumulative validation engine tests
│   ├── test_sequence_validator.py      # Sequence validation engine tests
│   ├── test_validate_phase4_endpoints.py # Phase 4 endpoint tests
│   ├── test_roster_validator.py        # Roster validation engine tests (Phase 5)
│   ├── test_validate_phase5_endpoints.py # Phase 5 endpoint tests
│   └── test_guide_endpoint.py          # Guide endpoint tests (Phase 6)
├── src/
│   └── index.js               # Cloudflare Worker proxy
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── wrangler.jsonc
├── README.md
└── requirements.txt
```

## Build Phases

| Phase | Scope | Status |
|-------|-------|--------|
| **0** | Health endpoint + skeleton + Docker + RapidAPI deploy | ✅ Complete |
| **1** | Regulatory content endpoints + legislation parser | ✅ Complete |
| **2** | FDP tables, cumulative limits, max-FDP & min-off-duty calculators | ✅ Complete |
| **3** | FDP and off-duty validation | ✅ Complete |
| **4** | Cumulative and sequence validation | ✅ Complete |
| **5** | Full roster validation | ✅ Complete |
| **6** | Self-describing `/guide` endpoint for LLM and integration consumers | ✅ Complete |

## Disclaimer

This API is derived from CAO 48.1 Instrument 2019 and is provided for reference purposes only. It does not replace your operator's approved Fatigue Management Manual (FMM), a qualified fatigue risk management assessment, or professional regulatory advice. Always verify compliance with your operator's approved procedures and the current in-force legislation.

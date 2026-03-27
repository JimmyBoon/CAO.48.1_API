# CAO 48.1 Compliance API — Specification

> **Version:** 0.2.0 (Draft)
> **Date:** 27 March 2026
> **Author:** James Boon
> **Status:** Design Phase — RapidAPI Deployment Target

---

## 1. Overview

A stateless REST API for validating flight crew duty periods against the Australian Civil Aviation Order 48.1 Instrument 2019 (Compilation No. 3). The API covers Appendices 1 through 6 and provides both validation (pass/fail with clause references) and calculation (max FDP, min ODP) endpoints, plus direct access to the legislative text.

All duty history required for rolling-window checks (cumulative limits, recovery periods, WOCL streaks) must be supplied in the request payload. The API maintains no state between requests.

---

## 2. Design Principles

- **Stateless** — all inputs (including duty history) passed per request; no database or session.
- **Explicit appendix** — the caller specifies which appendix applies; no inference.
- **Exhaustive failures** — validation endpoints return *all* violations found, not just the first.
- **Clause-referenced** — every check result cites the specific CAO 48.1 clause.
- **UTC-internal, local-time-aware** — all datetimes in UTC (ISO 8601); local time offset provided separately for WOCL/twilight calculations.
- **RapidAPI-native** — designed for deployment on RapidAPI Hub with OpenAPI auto-generation, proxy secret validation, and tiered access.

---

## 3. RapidAPI Integration

### 3.1 Architecture

```
Consumer → RapidAPI Runtime (proxy) → CAO 48.1 API (FastAPI on Docker)
```

RapidAPI acts as a reverse proxy. Consumers authenticate with RapidAPI using `X-RapidAPI-Key` and `X-RapidAPI-Host` headers. The runtime forwards requests to our API server with additional provider-side headers.

### 3.2 Provider-Side Headers

The following headers are injected by the RapidAPI Runtime on every forwarded request. The API server validates or logs these as appropriate.

| Header                     | Purpose                                              | Required |
|---------------------------|------------------------------------------------------|----------|
| `X-RapidAPI-Proxy-Secret` | Unique secret per API — validate server-side to ensure requests come via RapidAPI | Yes (production) |
| `X-RapidAPI-User`         | Username of the consumer making the request          | Logged   |
| `X-RapidAPI-Subscription` | Subscription tier: `BASIC`, `PRO`, `ULTRA`, `MEGA`, `CUSTOM` | Logged / rate-limiting |
| `X-Forwarded-For`         | Client IP address                                    | Logged   |

### 3.3 Proxy Secret Validation

In production, every request must include a valid `X-RapidAPI-Proxy-Secret` header matching the secret shown in the RapidAPI Provider Dashboard. Requests without a valid secret receive `403 Forbidden`.

In local development (`ENVIRONMENT=development`), this validation is skipped.

### 3.4 OpenAPI Specification

FastAPI auto-generates an OpenAPI 3.1 spec at `/openapi.json`. This is uploaded to RapidAPI to define all endpoints, parameters, and response schemas. To ensure clean import:

- Every endpoint has `summary`, `description`, and `tags`
- All Pydantic models include `Field(description=...)` and `json_schema_extra` with examples
- The `info` block includes `title`, `description`, `version`, `contact`, and `termsOfService`
- Endpoint tags map to RapidAPI endpoint groups: `Health`, `Regulatory Content`, `Calculation`, `Validation`

### 3.5 CORS

The API permits cross-origin requests to support RapidAPI's browser-based test console:

```python
origins = [
    "https://rapidapi.com",
    "https://*.rapidapi.com",
]
```

### 3.6 Pricing Tiers (Proposed)

| Tier   | Endpoints                                      | Rate Limit     |
|--------|------------------------------------------------|----------------|
| Free   | `GET /health`, `GET /sections`, `GET /sections/{id}`, `GET /limits/*` | 100 req/day    |
| Basic  | All Free + `POST /calculate/*`, `POST /validate/fdp`, `POST /validate/off-duty` | 1,000 req/day  |
| Pro    | All Basic + `POST /validate/cumulative`, `POST /validate/sequence` | 5,000 req/day  |
| Ultra  | All Pro + `POST /validate/roster`              | 10,000 req/day |

---

## 4. Base URL

```
/api/v1/cao481
```

The full RapidAPI consumer URL will be:
```
https://cao481-compliance.p.rapidapi.com/api/v1/cao481/...
```

---

## 5. Endpoints

### 5.0 Health & Status

#### `GET /health`

Returns the API status, version, and available appendices. Use this to verify the API is running and to discover which appendices and endpoints are available.

**Tags:** `Health`

**Response (200):**
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "api": "CAO 48.1 Compliance API",
  "description": "Stateless REST API for validating flight crew duty periods against Australian Civil Aviation Order 48.1 Instrument 2019",
  "legislation": {
    "title": "Civil Aviation Order 48.1 Instrument 2019",
    "compilation": "F2021C01239",
    "compilation_number": 3
  },
  "supported_appendices": [
    {
      "id": "1",
      "title": "Basic Limits",
      "status": "planned"
    },
    {
      "id": "2",
      "title": "Multi-Pilot Operations",
      "status": "planned"
    },
    {
      "id": "3",
      "title": "Multi-Pilot Except Complex",
      "status": "planned"
    },
    {
      "id": "4",
      "title": "Any Operations",
      "status": "planned"
    },
    {
      "id": "4A",
      "title": "Balloon Operations",
      "status": "planned"
    },
    {
      "id": "4B",
      "title": "Medical Transport & Emergency Service",
      "status": "planned"
    },
    {
      "id": "5",
      "title": "Aerial Work & Associated Flight Training",
      "status": "planned"
    },
    {
      "id": "5A",
      "title": "Daylight Aerial Work",
      "status": "planned"
    },
    {
      "id": "6",
      "title": "Flight Training",
      "status": "planned"
    }
  ],
  "endpoints": {
    "available": ["/health"],
    "planned": [
      "/sections",
      "/sections/{section_id}",
      "/limits/fdp-table/{appendix}",
      "/limits/cumulative/{appendix}",
      "/calculate/max-fdp",
      "/calculate/min-off-duty",
      "/validate/fdp",
      "/validate/off-duty",
      "/validate/cumulative",
      "/validate/sequence",
      "/validate/roster"
    ]
  }
}
```

---

### 5.1 Regulatory Content

#### `GET /sections`

Returns the table of contents for CAO 48.1.

**Response:**
```json
{
  "title": "Civil Aviation Order 48.1 Instrument 2019",
  "compilation": "F2021C01239 (Compilation No. 3)",
  "parts": [
    {
      "id": "PART 1",
      "title": "General",
      "sections": [
        { "id": "1", "title": "Name of instrument" },
        { "id": "4", "title": "Application" },
        { "id": "5", "title": "When the CAO takes effect" },
        { "id": "6", "title": "Definitions" },
        { "id": "7", "title": "Determination of acclimatisation" }
      ]
    }
  ],
  "appendices": [
    {
      "id": "APPENDIX 1",
      "title": "Basic Limits",
      "sections": [
        { "id": "1", "title": "Sleep opportunity before an FDP" },
        { "id": "2", "title": "FDP and flight time limits" },
        { "id": "3", "title": "Extensions" },
        { "id": "4", "title": "Off-duty period limits" },
        { "id": "5", "title": "Limit on cumulative flight time" }
      ]
    }
  ]
}
```

---

#### `GET /sections/{section_id}`

Returns the full regulatory text for a specific section or appendix.

**Path Parameters:**

| Parameter    | Type   | Description                                                                 |
|-------------|--------|-----------------------------------------------------------------------------|
| `section_id` | string | Section identifier, e.g. `"6"`, `"APPENDIX 2"`, `"APPENDIX 2.3"`, `"APPENDIX 3.8"` |

**Response:**
```json
{
  "section_id": "APPENDIX 3.2",
  "title": "FDP and flight time limits",
  "appendix": "APPENDIX 3",
  "text": "2.1 An FCM must not be assigned an FDP longer than...",
  "tables": [
    {
      "id": "Table 2.1",
      "title": "Maximum FDP (in hours) for an FCM according to number of sectors and local time at the start of the FDP",
      "headers": ["Local time at start of FDP", "1-3", "4", "5", "6", "7", "8+"],
      "rows": [
        ["0000-0459", 10, 9.5, 9, 8.5, 8, 7.5],
        ["0500-0559", 11, 10.5, 10, 9.5, 9, 8.5],
        ["0600-0659", 12, 11.5, 11, 10.5, 10, 9.5],
        ["0700-1259", 13, 12.5, 12, 11.5, 11, 10.5],
        ["1300-1359", 12, 11.5, 11, 10.5, 10, 9.5],
        ["1400-1459", 11, 10.5, 10, 9.5, 9, 8.5],
        ["1500-2359", 10, 9.5, 9, 8.5, 8, 7.5]
      ]
    }
  ],
  "notes": [
    "See paragraph 6.2 of this CAO for duties that infringe a WOCL."
  ],
  "disclaimer": "This output is derived from CAO 48.1 Instrument 2019..."
}
```

---

### 5.2 Lookup / Calculation

#### `GET /limits/fdp-table/{appendix}`

Returns the FDP lookup table for a given appendix.

**Path Parameters:**

| Parameter  | Type   | Description                                                        |
|-----------|--------|--------------------------------------------------------------------|
| `appendix` | string | Appendix identifier: `1`, `2`, `3`, `4`, `4A`, `4B`, `5`, `5A`, `6` |

**Response:**
```json
{
  "appendix": "3",
  "table_id": "Table 2.1",
  "lookup_key": "local_time_and_sectors",
  "flight_time_limit_hours": 10.5,
  "rows": [
    {
      "time_band": "0000-0459",
      "sectors": { "1-3": 10, "4": 9.5, "5": 9, "6": 8.5, "7": 8, "8+": 7.5 }
    }
  ],
  "split_duty_cap_hours": 16,
  "post_split_max_hours": 6,
  "notes": "Uses local time (not acclimatised time). No augmented crew provisions."
}
```

---

#### `GET /limits/cumulative/{appendix}`

Returns the cumulative limit thresholds for a given appendix.

**Response:**
```json
{
  "appendix": "3",
  "flight_time": {
    "28_day_hours": 100,
    "365_day_hours": 1000,
    "reset_after_days_off": null
  },
  "duty_time": {
    "168_hour_hours": 60,
    "336_hour_hours": 100
  },
  "recovery": {
    "168_hour_block": { "min_hours": 36, "local_nights": 2 },
    "28_day_days_off": 6
  }
}
```

---

#### `POST /calculate/max-fdp`

Given operational parameters, returns the maximum permissible FDP and the calculation breakdown.

**Request Body:**
```json
{
  "appendix": "3",
  "fdp_start_utc": "2026-03-28T22:00:00Z",
  "local_time_offset_hours": 8,
  "sectors": 3,
  "acclimatisation": {
    "state": "acclimatised",
    "acclimatised_time_offset_hours": 8
  },
  "augmented_crew": null,
  "split_duty": {
    "rest_start_utc": "2026-03-29T04:00:00Z",
    "rest_end_utc": "2026-03-29T08:00:00Z",
    "accommodation": "sleeping",
    "duration_hours": 4
  },
  "consecutive_early_starts": 2,
  "consecutive_wocl_infringements": 1
}
```

**Response:**
```json
{
  "appendix": "3",
  "base_max_fdp_hours": 13.0,
  "adjustments": [
    {
      "clause": "§3.1",
      "description": "Split-duty rest ≥4h with sleeping accommodation: +4h (capped at 16h)",
      "adjustment_hours": 3.0,
      "running_total_hours": 16.0
    }
  ],
  "wocl_early_start_reduction_hours": 0,
  "final_max_fdp_hours": 16.0,
  "max_extension_hours": 1.0,
  "absolute_max_with_extension_hours": 17.0,
  "post_split_max_hours": 6.0,
  "flight_time_limit_hours": 10.5,
  "calculation_notes": [
    "FDP start local time: 0600 → Table 2.1 band 0600-0659, 1-3 sectors = 12h",
    "Split duty: 4h sleeping accommodation → +4h, capped at 16h (§3.1)",
    "Post-split FDP must not exceed 6h (§3.5)"
  ]
}
```

---

#### `POST /calculate/min-off-duty`

Given the preceding FDP details, returns the minimum required off-duty period.

**Request Body:**
```json
{
  "appendix": "3",
  "preceding_fdp": {
    "start_utc": "2026-03-28T22:00:00Z",
    "end_utc": "2026-03-29T08:30:00Z",
    "duration_hours": 10.5,
    "post_fdp_duty_hours": 0.5,
    "location": "away",
    "split_duty": {
      "duration_hours": 4,
      "accommodation": "sleeping",
      "overlaps_2300_0529": false
    },
    "was_extended": false,
    "extension_hours": 0
  },
  "preceding_off_duty": {
    "duration_hours": 13,
    "included_local_night": true
  },
  "following_off_duty_location": "away",
  "following_off_duty_includes_local_night": true,
  "acclimatisation_state": "not_applicable"
}
```

**Response:**
```json
{
  "appendix": "3",
  "fdp_plus_post_duty_hours": 11.0,
  "exceeds_12h": false,
  "base_min_odp_hours": 10.0,
  "clause": "§8.1a",
  "split_duty_credit_hours": 2.0,
  "split_duty_credit_clause": "§3.2",
  "effective_duration_for_calc_hours": 9.0,
  "reduction_applicable": {
    "eligible": true,
    "clause": "§8.3",
    "conditions_met": [
      "Previous ODP ≥12h including local night",
      "ODP over a local night",
      "ODP away from home base",
      "Next-next ODP ≥12h including local night (caller must verify)"
    ],
    "reduced_min_odp_hours": 9.0
  },
  "final_min_odp_hours": 9.0,
  "calculation_notes": [
    "FDP + post-FDP duty = 11.0h (≤12h → §8.1 applies)",
    "Away from home base → base 10h (§8.1a)",
    "Split duty credit: −2h from effective FDP for ODP calc (§3.2)",
    "Reduction §8.3 eligible: may reduce to 9h subject to conditions"
  ]
}
```

---

### 5.3 Validation

#### `POST /validate/fdp`

Validates a single proposed FDP against all applicable rules for the specified appendix. Returns all violations found.

**Request Body:**
```json
{
  "appendix": "3",
  "fcm_id": "FCM-001",
  "fdp": {
    "start_utc": "2026-03-28T22:00:00Z",
    "end_utc": "2026-03-29T09:00:00Z",
    "local_time_offset_hours": 8,
    "location_start": "home_base",
    "location_end": "away",
    "sectors": 4,
    "flight_time_hours": 8.5,
    "includes_flight_training": false
  },
  "sleep_opportunity": {
    "hours": 8.5,
    "consecutive": true,
    "window_hours": 12
  },
  "split_duty": null,
  "augmented_crew": null,
  "acclimatisation": {
    "state": "not_applicable"
  },
  "extension": null
}
```

**Response:**
```json
{
  "valid": true,
  "appendix": "3",
  "fcm_id": "FCM-001",
  "checks": [
    {
      "check": "sleep_opportunity",
      "clause": "§1.2",
      "passed": true,
      "required": "≥8h consecutive within 12h (home base)",
      "actual": "8.5h consecutive within 12h",
      "detail": null
    },
    {
      "check": "fdp_limit",
      "clause": "§2.1 Table 2.1",
      "passed": true,
      "required": "≤12.5h (0600 local, 4 sectors)",
      "actual": "11.0h",
      "detail": "Local start time 0600, band 0600-0659, 4 sectors = 12.5h max"
    },
    {
      "check": "flight_time_limit",
      "clause": "§2.2",
      "passed": true,
      "required": "≤10.5h",
      "actual": "8.5h",
      "detail": null
    }
  ],
  "violations": [],
  "warnings": []
}
```

**Example with violations:**
```json
{
  "valid": false,
  "appendix": "3",
  "fcm_id": "FCM-001",
  "checks": ["..."],
  "violations": [
    {
      "check": "flight_time_limit",
      "clause": "§2.2",
      "severity": "hard_limit",
      "required": "≤10.5h",
      "actual": "11.2h",
      "excess": "0.7h",
      "detail": "Flight time 11.2h exceeds 10.5h limit. No extension provision for flight time beyond 30min (§5.5).",
      "remediation": "Reduce flight time by at least 0.7h or consider augmented crew under Appendix 2."
    },
    {
      "check": "consecutive_early_starts",
      "clause": "§11.1",
      "severity": "hard_limit",
      "required": "≤5 consecutive early starts (4th: −2h, 5th: −4h)",
      "actual": "6th consecutive early start",
      "excess": null,
      "detail": "FCM has had 5 consecutive early starts. A 6th is not permitted under §11.1/§11.3.",
      "remediation": "Schedule an intervening off-duty period including a local night before next early start."
    }
  ],
  "warnings": [
    {
      "check": "fdp_approaching_limit",
      "clause": "§2.1",
      "detail": "FDP is within 30min of maximum (10.5h of 11h limit). Consider fatigue risk."
    }
  ]
}
```

---

#### `POST /validate/off-duty`

Validates an off-duty period between two FDPs.

**Request Body:**
```json
{
  "appendix": "3",
  "fcm_id": "FCM-001",
  "preceding_fdp": {
    "start_utc": "2026-03-28T22:00:00Z",
    "end_utc": "2026-03-29T08:00:00Z",
    "duration_hours": 10.0,
    "post_fdp_duty_hours": 0,
    "location_end": "away",
    "split_duty": null,
    "was_extended": false,
    "extension_hours": 0
  },
  "off_duty_period": {
    "start_utc": "2026-03-29T08:00:00Z",
    "end_utc": "2026-03-29T18:00:00Z",
    "duration_hours": 10.0,
    "location": "away",
    "includes_local_night": false
  },
  "following_fdp": {
    "start_utc": "2026-03-29T18:00:00Z",
    "appendix": "3"
  },
  "acclimatisation_state": "not_applicable"
}
```

**Response:** Same structure as `/validate/fdp` with relevant ODP checks.

---

#### `POST /validate/cumulative`

Validates cumulative flight time, duty time, and recovery period limits against a duty history.

**Request Body:**
```json
{
  "appendix": "3",
  "fcm_id": "FCM-001",
  "reference_datetime_utc": "2026-03-29T09:00:00Z",
  "duty_history": [
    {
      "type": "fdp",
      "start_utc": "2026-03-20T22:00:00Z",
      "end_utc": "2026-03-21T06:00:00Z",
      "flight_time_hours": 5.5,
      "duty_hours": 8.0
    },
    {
      "type": "off_duty",
      "start_utc": "2026-03-21T06:00:00Z",
      "end_utc": "2026-03-22T22:00:00Z",
      "duration_hours": 40.0,
      "local_nights": 2,
      "is_day_off": true
    }
  ]
}
```

**Response:**
```json
{
  "valid": true,
  "appendix": "3",
  "fcm_id": "FCM-001",
  "checks": [
    {
      "check": "cumulative_flight_time_28d",
      "clause": "§9.1",
      "passed": true,
      "limit_hours": 100,
      "actual_hours": 62.5,
      "remaining_hours": 37.5,
      "window": "28-day rolling"
    },
    {
      "check": "cumulative_flight_time_365d",
      "clause": "§9.2",
      "passed": true,
      "limit_hours": 1000,
      "actual_hours": 480.0,
      "remaining_hours": 520.0,
      "window": "365-day rolling"
    },
    {
      "check": "cumulative_duty_168h",
      "clause": "§10.1",
      "passed": true,
      "limit_hours": 60,
      "actual_hours": 42.0,
      "remaining_hours": 18.0,
      "window": "168-hour rolling"
    },
    {
      "check": "cumulative_duty_336h",
      "clause": "§10.2",
      "passed": true,
      "limit_hours": 100,
      "actual_hours": 78.0,
      "remaining_hours": 22.0,
      "window": "336-hour rolling"
    },
    {
      "check": "recovery_36h_2ln_168h",
      "clause": "§8.5",
      "passed": true,
      "detail": "40h off-duty block with 2 local nights found within 168h window"
    },
    {
      "check": "days_off_28d",
      "clause": "§8.6",
      "passed": true,
      "required": 6,
      "actual": 8,
      "detail": "8 days off in preceding 28 days"
    }
  ],
  "violations": [],
  "warnings": [
    {
      "check": "cumulative_duty_168h",
      "clause": "§10.1",
      "detail": "42.0h of 60h used (70%). Consider fatigue risk for remaining capacity."
    }
  ]
}
```

---

#### `POST /validate/sequence`

Validates pattern-based rules across a sequence of duties: WOCL infringement streaks, consecutive early starts, late FDP counts, and unknown acclimatisation consecutive FDP limits.

**Request Body:**
```json
{
  "appendix": "3",
  "fcm_id": "FCM-001",
  "duty_sequence": [
    {
      "type": "fdp",
      "start_utc": "2026-03-25T21:30:00Z",
      "end_utc": "2026-03-26T05:00:00Z",
      "local_time_offset_hours": 8,
      "is_early_start": true,
      "infringes_wocl": false,
      "ends_after_2200_local": false
    },
    {
      "type": "off_duty",
      "start_utc": "2026-03-26T05:00:00Z",
      "end_utc": "2026-03-26T17:00:00Z",
      "includes_local_night": false
    },
    {
      "type": "fdp",
      "start_utc": "2026-03-26T21:30:00Z",
      "end_utc": "2026-03-27T05:00:00Z",
      "local_time_offset_hours": 8,
      "is_early_start": true,
      "infringes_wocl": false,
      "ends_after_2200_local": false
    }
  ]
}
```

**Response:** Same violation/check structure.

---

#### `POST /validate/roster`

Comprehensive validation of a roster block for one or more FCMs. Orchestrates all checks and returns **all** violations found across the entire roster.

**Request Body:**
```json
{
  "roster_period": {
    "start_utc": "2026-03-25T00:00:00Z",
    "end_utc": "2026-04-01T00:00:00Z"
  },
  "fcm_rosters": [
    {
      "fcm_id": "FCM-001",
      "appendix": "3",
      "home_base_offset_hours": 8,
      "duties": [
        {
          "type": "fdp",
          "start_utc": "2026-03-25T21:30:00Z",
          "end_utc": "2026-03-26T05:00:00Z",
          "sectors": 2,
          "flight_time_hours": 5.5,
          "location_start": "home_base",
          "location_end": "away",
          "split_duty": null,
          "includes_flight_training": false
        },
        {
          "type": "off_duty",
          "start_utc": "2026-03-26T05:00:00Z",
          "end_utc": "2026-03-26T17:00:00Z",
          "location": "away"
        },
        {
          "type": "fdp",
          "start_utc": "2026-03-26T21:30:00Z",
          "end_utc": "2026-03-27T05:30:00Z",
          "sectors": 2,
          "flight_time_hours": 6.0,
          "location_start": "away",
          "location_end": "home_base",
          "split_duty": null,
          "includes_flight_training": false
        }
      ],
      "prior_duty_history": [
        {
          "type": "fdp",
          "start_utc": "2026-03-18T22:00:00Z",
          "end_utc": "2026-03-19T06:00:00Z",
          "flight_time_hours": 5.5,
          "duty_hours": 8.0
        }
      ]
    }
  ]
}
```

**Response:**
```json
{
  "roster_period": {
    "start_utc": "2026-03-25T00:00:00Z",
    "end_utc": "2026-04-01T00:00:00Z"
  },
  "overall_valid": true,
  "summary": {
    "fcms_checked": 1,
    "total_fdps_checked": 2,
    "total_violations": 0,
    "total_warnings": 1
  },
  "fcm_results": [
    {
      "fcm_id": "FCM-001",
      "appendix": "3",
      "valid": true,
      "fdp_results": [
        {
          "fdp_index": 0,
          "fdp_start_utc": "2026-03-25T21:30:00Z",
          "valid": true,
          "violations": [],
          "warnings": []
        },
        {
          "fdp_index": 1,
          "fdp_start_utc": "2026-03-26T21:30:00Z",
          "valid": true,
          "violations": [],
          "warnings": [
            {
              "check": "off_duty_period",
              "clause": "§8.1a",
              "detail": "ODP of 12h meets minimum 10h (away), but is tight."
            }
          ]
        }
      ],
      "cumulative_results": {
        "valid": true,
        "violations": [],
        "checks": ["...as per /validate/cumulative response..."]
      },
      "sequence_results": {
        "valid": true,
        "violations": [],
        "checks": ["...as per /validate/sequence response..."]
      }
    }
  ]
}
```

---

## 6. Common Data Types

### 5.1 Enumerations

```
AppendixId:     "1" | "2" | "3" | "4" | "4A" | "4B" | "5" | "5A" | "6"

DutyType:       "fdp" | "off_duty" | "standby" | "positioning" | "ground_duty"

Location:       "home_base" | "away"

AcclimState:    "acclimatised" | "unknown" | "not_applicable"

Accommodation:  "sleeping" | "resting" | "none"

Severity:       "hard_limit" | "soft_limit" | "warning"

CrewRestClass:  "class_1" | "class_2" | "class_3"
```

### 5.2 Core Objects

#### SplitDuty
```json
{
  "rest_start_utc": "ISO 8601",
  "rest_end_utc": "ISO 8601",
  "duration_hours": 4.0,
  "accommodation": "sleeping | resting | none",
  "overlaps_2300_0529": false
}
```

#### AugmentedCrew (Appendix 2 only)
```json
{
  "additional_fcms": 1,
  "rest_facility_class": "class_1 | class_2 | class_3",
  "in_flight_rest_hours_per_fcm": [
    { "fcm_id": "FCM-002", "rest_hours": 2.0, "at_controls_final_landing": false },
    { "fcm_id": "FCM-003", "rest_hours": 2.5, "at_controls_final_landing": true }
  ]
}
```

#### Extension
```json
{
  "type": "unforeseen | urgent | final_sector",
  "extension_hours": 1.0,
  "fdp_commenced": true,
  "operationally_necessary": true,
  "fcm_fit_confirmed": true,
  "pic_consulted_crew": true,
  "clause": "§5.3"
}
```

#### CheckResult
```json
{
  "check": "string — check identifier",
  "clause": "string — CAO 48.1 clause reference",
  "passed": true,
  "required": "string — what the rule requires",
  "actual": "string — what was found",
  "detail": "string | null — human-readable explanation"
}
```

#### Violation
```json
{
  "check": "string",
  "clause": "string",
  "severity": "hard_limit | soft_limit",
  "required": "string",
  "actual": "string",
  "excess": "string | null",
  "detail": "string",
  "remediation": "string — suggested corrective action"
}
```

---

## 7. Error Handling

### HTTP Status Codes

| Code | Meaning                                        |
|------|------------------------------------------------|
| 200  | Validation completed (even if violations found) |
| 400  | Invalid request body (missing fields, bad types)|
| 403  | Forbidden — invalid or missing `X-RapidAPI-Proxy-Secret` |
| 404  | Section not found (for `/sections/{id}`)        |
| 422  | Unprocessable — valid JSON but logically invalid (e.g. FDP end before start) |
| 500  | Internal server error                           |

### Error Response
```json
{
  "error": "validation_error",
  "message": "FDP end time (2026-03-28T05:00:00Z) is before start time (2026-03-28T22:00:00Z)",
  "field": "fdp.end_utc"
}
```

---

## 8. Appendix-Specific Variations

The following table summarises which checks apply to each appendix, informing which validation logic branches are active:

| Check                        | 1 | 2 | 3 | 4 | 4A | 4B | 5 | 5A | 6 |
|------------------------------|---|---|---|---|----|----|---|----|---|
| Sleep opportunity            | ✓ | ✓ | ✓ | ✓ | ✓  | —  | — | ✓  | ✓ |
| FDP table lookup             | ✓ | ✓ | ✓ | ✓ | ✓  | ✓  | ✓ | ✓  | ✓ |
| Sectors in FDP table         | — | ✓ | ✓ | — | —  | ✓  | ✓ | —  | — |
| Acclimatisation branching    | — | ✓ | — | — | —  | —  | — | —  | — |
| Augmented crew               | — | ✓ | — | — | —  | —  | — | —  | — |
| Split duty                   | — | ✓ | ✓ | ✓ | ✓  | ✓  | ✓ | —  | ✓ |
| Increased FDP (2 per 168h)   | — | — | — | — | —  | ✓  | ✓ | —  | — |
| Non-flying duty reduction    | — | — | — | — | —  | ✓  | ✓ | —  | — |
| WOCL / early starts          | — | ✓ | ✓ | ✓ | —  | —  | — | —  | ✓ |
| Late FDP count               | ✓ | — | — | — | —  | ✓  | ✓ | —  | — |
| Daylight window              | — | — | — | — | —  | —  | — | ✓  | — |
| 3-night prior duty check     | — | — | — | — | —  | —  | — | ✓  | — |
| Flight time per-FDP limit    | — | ✓ | ✓ | — | —  | —  | — | —  | ✓ |
| Standby provisions           | — | ✓ | ✓ | ✓ | —  | ✓  | — | —  | ✓ |
| Delay provisions             | — | ✓ | ✓ | ✓ | —  | —  | — | —  | — |
| Displacement time in ODP     | — | ✓ | — | ✓ | —  | ✓  | — | —  | — |
| Urgent ops extension (+4h)   | — | — | — | — | —  | ✓  | — | —  | — |
| Cumulative flight time       | ✓ | ✓ | ✓ | ✓ | ✓  | ✓  | ✓ | ✓  | ✓ |
| Cumulative duty time         | — | ✓ | ✓ | ✓ | ✓  | ✓  | — | —  | ✓ |
| Recovery periods             | ✓ | ✓ | ✓ | ✓ | ✓  | ✓  | ✓ | ✓  | ✓ |

---

## 9. Implementation Notes

### 9.1 Technology Stack
- **Framework:** FastAPI (Python 3.12+) — aligns with existing MCP server stack, auto-generates OpenAPI spec
- **Validation:** Pydantic v2 models for request/response schemas with rich field descriptions
- **Deployment:** Dockerised, same pattern as the Leon MCP server
- **Hosting:** Cloud-hosted with HTTPS (required by RapidAPI)
- **Testing:** pytest with parametric test cases per appendix, per clause
- **CI/CD:** OpenAPI spec auto-uploaded to RapidAPI on deploy via GitHub Actions

### 9.2 RapidAPI Deployment

#### Provider Setup
1. Register the API on RapidAPI Hub at `rapidapi.com/studio`
2. Upload the auto-generated `openapi.json` to populate endpoint definitions
3. Configure the base URL to point to the hosted Docker container
4. Set `X-RapidAPI-Proxy-Secret` in the Security tab
5. Configure pricing tiers per Section 3.6
6. Add API description, logo, and documentation

#### Required Middleware (FastAPI)
```python
# Proxy secret validation — ensures requests come via RapidAPI
@app.middleware("http")
async def validate_rapidapi_proxy(request: Request, call_next):
    if settings.environment == "production":
        proxy_secret = request.headers.get("X-RapidAPI-Proxy-Secret")
        if proxy_secret != settings.rapidapi_proxy_secret:
            return JSONResponse(status_code=403, content={"error": "forbidden"})
    response = await call_next(request)
    return response
```

#### Environment Variables
```
ENVIRONMENT=production|development
RAPIDAPI_PROXY_SECRET=<from RapidAPI Provider Dashboard>
API_VERSION=0.1.0
```

### 9.3 MCP Server Wrapping
Once the API is built, the MCP server layer is thin — each endpoint maps to an MCP tool:
- `cao481_health` → `GET /health`
- `cao481_get_sections` → `GET /sections`
- `cao481_get_section` → `GET /sections/{section_id}`
- `cao481_get_fdp_table` → `GET /limits/fdp-table/{appendix}`
- `cao481_get_cumulative_limits` → `GET /limits/cumulative/{appendix}`
- `cao481_calculate_max_fdp` → `POST /calculate/max-fdp`
- `cao481_calculate_min_off_duty` → `POST /calculate/min-off-duty`
- `cao481_validate_fdp` → `POST /validate/fdp`
- `cao481_validate_off_duty` → `POST /validate/off-duty`
- `cao481_validate_cumulative` → `POST /validate/cumulative`
- `cao481_validate_sequence` → `POST /validate/sequence`
- `cao481_validate_roster` → `POST /validate/roster`

### 9.4 Phased Build
Suggested implementation order:
1. **Phase 0:** Health endpoint + FastAPI skeleton + Dockerfile + RapidAPI deployment (prove the pipeline)
2. **Phase 1:** Regulatory content endpoints + FDP table lookups (low complexity, immediate value)
3. **Phase 2:** `/calculate/max-fdp` and `/calculate/min-off-duty` (core logic, testable in isolation)
4. **Phase 3:** `/validate/fdp` and `/validate/off-duty` (builds on Phase 2)
5. **Phase 4:** `/validate/cumulative` and `/validate/sequence` (rolling-window logic)
6. **Phase 5:** `/validate/roster` (orchestration layer)
7. **Phase 6:** MCP server wrapper

### 9.5 Test Strategy
Each clause in every appendix should have at least:
- A **passing** test case (just within limits)
- A **boundary** test case (exactly at the limit)
- A **failing** test case (just beyond the limit)
- Where applicable, an **extension** test case (over limit but valid extension)

The flowchart `.mermaid` files serve as the test-case design reference — each red terminal node maps to at least one failing test case.


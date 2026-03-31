# CAO 48.1 API — Manual Test Checklist

**Base URL:** `https://cao481-api.jwboon.workers.dev/api/v1/cao481`  
**Postman Collection:** `postman/cao481_manual_tests.postman_collection.json`  
**Total Tests:** 103

---

## How to Use

1. Import the Postman collection from `postman/cao481_manual_tests.postman_collection.json`
2. The base URL variable `{{baseUrl}}` is pre-configured
3. Run each test and verify the expected result
4. Mark tests off below as you complete them: change `[ ]` to `[x]`

---

## 01 — Health & Discovery (3 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T001 | Health check returns 200 with correct structure | GET | `/health` | 200 — Response has `status: "healthy"`, `version`, `api`, `legislation`, `supported_appendices`, `endpoints` | [ ] |
| T002 | Health check lists all 9 appendices | GET | `/health` | `supported_appendices` has 9 entries: 1, 2, 3, 4, 4A, 4B, 5, 5A, 6 | [ ] |
| T003 | Health check lists all available endpoints | GET | `/health` | `endpoints.available` includes `/health`, `/sections`, `/calculate/max-fdp`, `/validate/fdp`, `/validate/off-duty`, `/validate/cumulative`, `/validate/sequence`, `/validate/roster`, `/guide` | [ ] |

---

## 02 — Sections (7 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T004 | Table of contents | GET | `/sections` | 200 — Has `title`, `compilation`, `groups` array with parts and appendices | [ ] |
| T005 | Part group (PART 1) | GET | `/sections/PART 1` | 200 — Has `section_id: "PART 1"`, `title: "General"`, `sections` array | [ ] |
| T006 | Appendix group (APPENDIX 3) | GET | `/sections/APPENDIX 3` | 200 — Has `section_id: "APPENDIX 3"`, `title` contains "MULTI-PILOT", `sections` array | [ ] |
| T007 | Specific section (APPENDIX 3.2) | GET | `/sections/APPENDIX 3.2` | 200 — Has `section_id: "APPENDIX 3.2"`, `parent_id: "APPENDIX 3"`, `text` with content | [ ] |
| T008 | Definitions section (6) | GET | `/sections/6` | 200 — Has `section_id: "6"`, `title: "Definitions"`, `text` with content | [ ] |
| T009 | Non-existent section | GET | `/sections/NONEXISTENT` | 404 — Error response | [ ] |
| T010 | Non-existent appendix | GET | `/sections/APPENDIX 99` | 404 — Error response | [ ] |

---

## 03 — Limits: FDP Tables (10 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T011 | FDP table Appendix 1 (Basic Limits) | GET | `/limits/fdp-table/1` | 200 — Has `appendix: "1"`, `table_id`, `rows` array with time bands and sector keys `1-3`, `4`, `5`, `6`, `7`, `8+` | [ ] |
| T012 | FDP table Appendix 2 (Multi-Pilot) | GET | `/limits/fdp-table/2` | 200 — Has `appendix: "2"`, may have multiple sub-tables (acclimatised/unknown) | [ ] |
| T013 | FDP table Appendix 3 | GET | `/limits/fdp-table/3` | 200 — Has `appendix: "3"`, `flight_time_limit_hours: 10.5`, rows with standard sector keys | [ ] |
| T014 | FDP table Appendix 4 | GET | `/limits/fdp-table/4` | 200 — Has `appendix: "4"`, rows with sector keys | [ ] |
| T015 | FDP table Appendix 4A (Balloon) | GET | `/limits/fdp-table/4A` | 200 — Has `appendix: "4A"`, likely simpler table with `all` sector key | [ ] |
| T016 | FDP table Appendix 4B (Medical) | GET | `/limits/fdp-table/4B` | 200 — Has `appendix: "4B"`, rows present | [ ] |
| T017 | FDP table Appendix 5 (Aerial Work) | GET | `/limits/fdp-table/5` | 200 — Has `appendix: "5"`, sector keys may include `single_pilot`, `multi_1_2`, `multi_3+` | [ ] |
| T018 | FDP table Appendix 5A (Daylight Aerial) | GET | `/limits/fdp-table/5A` | 200 — Has `appendix: "5A"` | [ ] |
| T019 | FDP table Appendix 6 (Flight Training) | GET | `/limits/fdp-table/6` | 200 — Has `appendix: "6"` | [ ] |
| T020 | Invalid appendix 99 | GET | `/limits/fdp-table/99` | 404 — Error response | [ ] |

---

## 04 — Limits: Cumulative (6 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T021 | Cumulative Appendix 1 | GET | `/limits/cumulative/1` | 200 — `flight_time.period_28d_hours: 100`, `flight_time.period_365d_hours: 1000`, `recovery.period_168h_block.min_hours: 36` | [ ] |
| T022 | Cumulative Appendix 3 | GET | `/limits/cumulative/3` | 200 — `duty_time.period_168h_hours: 60`, `duty_time.period_336h_hours: 100`, `recovery.period_28d_days_off: 6` | [ ] |
| T023 | Cumulative Appendix 4A (Balloon) | GET | `/limits/cumulative/4A` | 200 — Different structure: `flight_time.period_28d_hours: 50`, `duty_time.period_168h_hours: 45` | [ ] |
| T024 | Cumulative Appendix 5 (Aerial Work) | GET | `/limits/cumulative/5` | 200 — Unique limits: multiple flight time windows (168h, 28d, 90d, 365d) | [ ] |
| T025 | Cumulative Appendix 5A | GET | `/limits/cumulative/5A` | 200 — `flight_time.period_384h_hours: 100`, `flight_time.period_365d_hours: 1200` | [ ] |
| T026 | Invalid appendix | GET | `/limits/cumulative/INVALID` | 404 — Error response | [ ] |

---

## 05 — Calculate: Max FDP (21 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T027 | App 1 basic (0700 local, 3 sectors) | POST | `/calculate/max-fdp` | 200 — `base_max_fdp_hours` from 0700–1259 band, 1-3 sectors (expect ~13h) | [ ] |
| T028 | App 1 early morning (0500 local, 4 sectors) | POST | `/calculate/max-fdp` | 200 — 0500–0559 band, 4 sectors (lower than midday) | [ ] |
| T029 | App 1 night (0200 local, 1 sector) | POST | `/calculate/max-fdp` | 200 — 0000–0459 band values (shortest FDP limits) | [ ] |
| T030 | App 1 with 8+ sectors | POST | `/calculate/max-fdp` | 200 — Uses `8+` column (smallest per-band values) | [ ] |
| T031 | App 3 split duty sleeping 4h | POST | `/calculate/max-fdp` | 200 — `base_max_fdp_hours` + 4h sleeping extension, capped at 16h, `post_split_max_hours: 6` | [ ] |
| T032 | App 3 split duty resting 3h | POST | `/calculate/max-fdp` | 200 — Resting adds 50% of rest hours (1.5h), capped appropriately | [ ] |
| T033 | App 2 acclimatised (3 sectors) | POST | `/calculate/max-fdp` | 200 — Uses acclimatised time table | [ ] |
| T034 | App 2 unknown acclimatisation | POST | `/calculate/max-fdp` | 200 — Uses unknown/worst-case table lookup | [ ] |
| T035 | App 2 augmented crew (1 FCM, class 1) | POST | `/calculate/max-fdp` | 200 — Extended FDP from augmented crew provisions | [ ] |
| T036 | App 2 augmented crew (2 FCMs, class 2) | POST | `/calculate/max-fdp` | 200 — Larger extension than 1 FCM | [ ] |
| T037 | App 4 (Any Operations, 2 sectors) | POST | `/calculate/max-fdp` | 200 — Appendix 4 specific limits | [ ] |
| T038 | App 4A (Balloon) | POST | `/calculate/max-fdp` | 200 — Balloon-specific limits (simpler table) | [ ] |
| T039 | App 4B (Medical, single pilot) | POST | `/calculate/max-fdp` | 200 — Single pilot medical transport limits | [ ] |
| T040 | App 5 (Aerial Work, single pilot) | POST | `/calculate/max-fdp` | 200 — Uses `single_pilot` sector key | [ ] |
| T041 | App 5A (Daylight Aerial Work) | POST | `/calculate/max-fdp` | 200 — Daylight-only limits | [ ] |
| T042 | App 6 (Flight Training) | POST | `/calculate/max-fdp` | 200 — Flight training specific limits | [ ] |
| T043 | Consecutive early starts reduction | POST | `/calculate/max-fdp` | 200 — `wocl_early_start_reduction_hours > 0` when 3 consecutive early starts | [ ] |
| T044 | Consecutive WOCL infringements | POST | `/calculate/max-fdp` | 200 — Reduction or warning after 3 consecutive WOCL infringements | [ ] |
| T045 | Missing required fields | POST | `/calculate/max-fdp` | 422 — Validation error listing missing fields | [ ] |
| T046 | Invalid appendix "99" | POST | `/calculate/max-fdp` | 422 — Validation error for invalid appendix enum | [ ] |
| T047 | Sectors = 0 (invalid) | POST | `/calculate/max-fdp` | 422 — Validation error (sectors must be ≥ 1) | [ ] |

---

## 06 — Calculate: Min Off-Duty (8 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T048 | App 3 basic (away base) | POST | `/calculate/min-off-duty` | 200 — `base_min_odp_hours: 10`, check `final_min_odp_hours` | [ ] |
| T049 | App 3 home base | POST | `/calculate/min-off-duty` | 200 — Home base may differ from away base minimum | [ ] |
| T050 | FDP+post-duty exceeds 12h | POST | `/calculate/min-off-duty` | 200 — `exceeds_12h: true`, higher minimum off-duty required | [ ] |
| T051 | Reduction applicable (prior ODP ≥12h with local night) | POST | `/calculate/min-off-duty` | 200 — `reduction_applicable.eligible: true`, `reduced_min_odp_hours` < `base_min_odp_hours` | [ ] |
| T052 | Split duty credit applied | POST | `/calculate/min-off-duty` | 200 — `split_duty_credit_hours: 2.0`, `effective_duration_for_calc_hours` reduced by credit | [ ] |
| T053 | App 1 minimum off-duty | POST | `/calculate/min-off-duty` | 200 — Appendix 1 specific minimum | [ ] |
| T054 | App 5 (Aerial Work) | POST | `/calculate/min-off-duty` | 200 — Aerial work specific off-duty rules | [ ] |
| T055 | Missing required fields | POST | `/calculate/min-off-duty` | 422 — Validation error | [ ] |

---

## 07 — Validate: FDP (11 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T056 | FDP within limit (App 3, 12h) | POST | `/validate/fdp` | 200 — `valid: true`, all checks passed, no violations | [ ] |
| T057 | FDP exceeds limit (16h FDP) | POST | `/validate/fdp` | 200 — `valid: false`, `violations` includes `fdp_within_limit` failure | [ ] |
| T058 | Flight time exceeds per-FDP limit | POST | `/validate/fdp` | 200 — `valid: false`, `violations` includes `flight_time_within_limit` failure (limit is 10.5h) | [ ] |
| T059 | Unforeseen extension (valid, 1h) | POST | `/validate/fdp` | 200 — `valid: true`, checks show extension within allowed max | [ ] |
| T060 | Extension exceeds max (3h used) | POST | `/validate/fdp` | 200 — `valid: false`, violation for extension exceeding max (1h allowed) | [ ] |
| T061 | App 1 (Basic Limits) valid FDP | POST | `/validate/fdp` | 200 — `valid: true`, Appendix 1 limits applied | [ ] |
| T062 | App 2 with augmented crew | POST | `/validate/fdp` | 200 — Augmented crew provisions applied, check extended limit | [ ] |
| T063 | App 4B (Medical Transport, single pilot) | POST | `/validate/fdp` | 200 — Single pilot limits applied | [ ] |
| T064 | Split duty within post-split cap | POST | `/validate/fdp` | 200 — `valid: true`, split duty extension applied, post-split ≤ 6h | [ ] |
| T065 | Missing required fields | POST | `/validate/fdp` | 422 — Missing `fdp_start_utc`, `fdp_end_utc` | [ ] |
| T066 | Empty body | POST | `/validate/fdp` | 422 — Validation error for missing all required fields | [ ] |

---

## 08 — Validate: Off-Duty (6 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T067 | Off-duty valid (10.5h actual, ~10h min) | POST | `/validate/off-duty` | 200 — `valid: true`, checks passed | [ ] |
| T068 | Off-duty too short (7h, violation) | POST | `/validate/off-duty` | 200 — `valid: false`, `violations` includes off-duty period too short | [ ] |
| T069 | Reduction claimed with qualifying prior ODP | POST | `/validate/off-duty` | 200 — Reduction validated, reduced minimum applied | [ ] |
| T070 | Off-duty after extended FDP | POST | `/validate/off-duty` | 200 — Longer minimum required after extended FDP | [ ] |
| T071 | App 1 basic off-duty | POST | `/validate/off-duty` | 200 — Appendix 1 off-duty rules applied | [ ] |
| T072 | Missing required fields | POST | `/validate/off-duty` | 422 — Validation error | [ ] |

---

## 09 — Validate: Cumulative (9 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T073 | fdp_log within limits | POST | `/validate/cumulative` | 200 — `valid: true`, all cumulative checks passed | [ ] |
| T074 | Summary within limits | POST | `/validate/cumulative` | 200 — `valid: true`, summary-based validation works | [ ] |
| T075 | Flight time 28d exceeds 100h | POST | `/validate/cumulative` | 200 — `valid: false`, violation for `flight_time_28d` | [ ] |
| T076 | Flight time 365d exceeds 1000h | POST | `/validate/cumulative` | 200 — `valid: false`, violation for `flight_time_365d` | [ ] |
| T077 | Duty time 168h exceeds 60h | POST | `/validate/cumulative` | 200 — `valid: false`, violation for `duty_time_168h` | [ ] |
| T078 | No recovery block in 168h | POST | `/validate/cumulative` | 200 — `valid: false`, violation for missing recovery block | [ ] |
| T079 | Insufficient days off in 28d | POST | `/validate/cumulative` | 200 — `valid: false`, violation for < 6 days off | [ ] |
| T080 | App 4A (Balloon, different limits) | POST | `/validate/cumulative` | 200 — Balloon-specific limits (50h/28d, 45h/168h duty) | [ ] |
| T081 | Missing both fdp_log and summary | POST | `/validate/cumulative` | 422 — Must provide at least one of fdp_log or summary | [ ] |

---

## 10 — Validate: Sequence (6 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T082 | Valid 2-FDP sequence with adequate off-duty | POST | `/validate/sequence` | 200 — `valid: true`, sequence checks passed | [ ] |
| T083 | Insufficient off-duty gap between FDPs | POST | `/validate/sequence` | 200 — `valid: false`, off-duty violation in sequence | [ ] |
| T084 | Consecutive WOCL crossings (3 FDPs) | POST | `/validate/sequence` | 200 — Warning or violation for consecutive WOCL infringements | [ ] |
| T085 | Single FDP only (no sequence checks) | POST | `/validate/sequence` | 200 — `valid: true`, minimal sequence | [ ] |
| T086 | Consecutive early starts (3 FDPs at 0500 local) | POST | `/validate/sequence` | 200 — Early start tracking, potential warnings | [ ] |
| T087 | Empty events array | POST | `/validate/sequence` | 422 — Events must have at least 1 item | [ ] |

---

## 11 — Validate: Roster (8 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T088 | Valid roster (2 FDPs, 1 ODP, 1 rest day) | POST | `/validate/roster` | 200 — `valid: true`, `summary` shows totals, `total_violations: 0` | [ ] |
| T089 | Roster with FDP violation (16h FDP) | POST | `/validate/roster` | 200 — `valid: false`, `fdp_results[0].valid: false`, `summary.fdp_violations > 0` | [ ] |
| T090 | Roster with prior_summary for cumulative | POST | `/validate/roster` | 200 — `cumulative_result` reflects prior + roster totals | [ ] |
| T091 | Roster with extension on FDP | POST | `/validate/roster` | 200 — Extension applied to FDP validation within roster | [ ] |
| T092 | Roster with split duty FDP | POST | `/validate/roster` | 200 — Split duty extension applied within roster context | [ ] |
| T093 | Roster Appendix 1 (Basic Limits) | POST | `/validate/roster` | 200 — Appendix 1 rules applied to entire roster | [ ] |
| T094 | Missing required fields | POST | `/validate/roster` | 422 — Missing `roster_start_utc`, `roster_end_utc`, `events` | [ ] |
| T095 | Empty events array | POST | `/validate/roster` | 422 — Events must have at least 1 item | [ ] |

---

## 12 — Guide (1 test)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T096 | Guide returns content | GET | `/guide` | 200 — Response contains structured guide with endpoint summaries and worked examples | [ ] |

---

## 13 — Error Handling & Edge Cases (7 tests)

| # | Test | Method | Endpoint | Expected | Done |
|---|------|--------|----------|----------|------|
| T097 | Non-existent endpoint | GET | `/nonexistent` | 404 — Not found error | [ ] |
| T098 | POST to GET-only endpoint | POST | `/health` | 405 — Method not allowed | [ ] |
| T099 | Invalid JSON body | POST | `/validate/fdp` | 422 — Parse error for malformed JSON | [ ] |
| T100 | Negative local time offset | POST | `/calculate/max-fdp` | 200 — Correctly handles negative offset (e.g. UTC-5) | [ ] |
| T101 | fdp_end before fdp_start | POST | `/validate/fdp` | 422 — Validation error (end must be after start) | [ ] |
| T102 | Zero duration FDP for off-duty calc | POST | `/calculate/min-off-duty` | 422 — Validation error (duration must be > 0) | [ ] |
| T103 | App 5 multi-pilot crew | POST | `/validate/fdp` | 200 — `single_pilot: false` uses multi-pilot sector keys | [ ] |

---

## Summary

| Category | Count | Passed | Failed |
|----------|-------|--------|--------|
| 01 — Health & Discovery | 3 | | |
| 02 — Sections | 7 | | |
| 03 — Limits: FDP Tables | 10 | | |
| 04 — Limits: Cumulative | 6 | | |
| 05 — Calculate: Max FDP | 21 | | |
| 06 — Calculate: Min Off-Duty | 8 | | |
| 07 — Validate: FDP | 11 | | |
| 08 — Validate: Off-Duty | 6 | | |
| 09 — Validate: Cumulative | 9 | | |
| 10 — Validate: Sequence | 6 | | |
| 11 — Validate: Roster | 8 | | |
| 12 — Guide | 1 | | |
| 13 — Error Handling & Edge Cases | 7 | | |
| **TOTAL** | **103** | | |

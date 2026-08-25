"""
Guide data for the GET /guide endpoint.

Structured documentation for every endpoint in the CAO 48.1 Compliance API,
designed to be fetched once by an LLM or integration at the start of a session.

Version field is intentionally left as a placeholder — the route handler
overwrites it with settings.app_version at runtime.
"""

GUIDE: dict = {
    "title": "CAO 48.1 Compliance API — Integration Guide",
    "version": "dynamic",  # replaced at runtime with settings.app_version
    "api_base_path": "/api/v1/cao481",
    "description": (
        "Call GET /guide once at the start of a session. This guide covers every "
        "endpoint's purpose, when to use it versus alternatives, the non-obvious "
        "parameter semantics, a worked example, and common integration mistakes."
    ),
    "important_notes": [
        "All timestamps must be UTC ISO 8601 strings (e.g. '2026-03-24T22:00:00Z').",
        "FDP time-band lookups use LOCAL time, not UTC. Always provide "
        "local_time_offset_hours (hours ahead of UTC, e.g. AEST = 10.0, IST = 5.5) "
        "so the API can convert FDP start UTC → local time of day.",
        "The API is stateless — there is no session memory between requests. For "
        "cumulative rolling-window checks you must supply the prior FDP history on "
        "every call via prior_fdp_log or prior_summary.",
        "Validation responses always include a top-level 'valid' boolean and a "
        "'violations' list. Each violation includes a CAO 48.1 clause reference "
        "and a remediation suggestion.",
        "This API validates against CAO 48.1 Instrument 2019 (Compilation No. 3, "
        "F2021C01239). Always cross-check with the current in-force legislation and "
        "your operator's approved Fatigue Management Manual (FMM).",
        "The /validate/* endpoints check compliance rules. They do NOT replace the "
        "/calculate/* endpoints. For a full check on a given FDP, call "
        "/calculate/max-fdp first to determine the limit, then /validate/fdp on "
        "the actual times.",
    ],
    "appendices": [
        {
            "id": "1",
            "title": "Basic Limits",
            "operations": "Single-pilot operations on any aircraft",
            "has_wocl_rules": False,
            "has_augmented_crew": False,
        },
        {
            "id": "2",
            "title": "Multi-Pilot Operations (complex aircraft)",
            "operations": "Multi-pilot operations on complex aircraft (e.g. airliners requiring a type rating)",
            "has_wocl_rules": True,
            "has_augmented_crew": True,
            "note": (
                "Has sub-tables for acclimatised / not_acclimatised crew and 3-pilot / 4-pilot "
                "augmented operations. Supply acclimatisation and augmented_crew / augmented_crew_size "
                "to select the correct table."
            ),
        },
        {
            "id": "3",
            "title": "Multi-Pilot Operations Except Complex",
            "operations": "Multi-pilot operations on non-complex aircraft",
            "has_wocl_rules": True,
            "has_augmented_crew": False,
        },
        {
            "id": "4",
            "title": "Any Operations",
            "operations": "Operations not covered by other appendices",
            "has_wocl_rules": True,
            "has_augmented_crew": False,
        },
        {
            "id": "4A",
            "title": "Balloon Operations",
            "operations": "Balloon flights",
            "has_wocl_rules": False,
            "has_augmented_crew": False,
        },
        {
            "id": "4B",
            "title": "Medical Transport & Emergency Service Operations",
            "operations": "Aeromedical and emergency service flights",
            "has_wocl_rules": False,
            "has_augmented_crew": False,
        },
        {
            "id": "5",
            "title": "Aerial Work & Associated Flight Training",
            "operations": "Aerial application, survey, patrol, associated training",
            "has_wocl_rules": False,
            "has_augmented_crew": False,
        },
        {
            "id": "5A",
            "title": "Daylight Aerial Work",
            "operations": "Aerial work conducted entirely within daylight hours",
            "has_wocl_rules": False,
            "has_augmented_crew": False,
        },
        {
            "id": "6",
            "title": "Flight Training",
            "operations": "Flying school and ab-initio instructor operations",
            "has_wocl_rules": False,
            "has_augmented_crew": False,
        },
    ],
    "quick_reference": [
        {
            "task": "Validate a single completed FDP",
            "endpoint": "POST /validate/fdp",
        },
        {
            "task": "Find the maximum permissible FDP duration before it starts (planning)",
            "endpoint": "POST /calculate/max-fdp",
        },
        {
            "task": "Find the minimum off-duty period after a given FDP",
            "endpoint": "POST /calculate/min-off-duty",
        },
        {
            "task": "Validate an off-duty period between two FDPs",
            "endpoint": "POST /validate/off-duty",
        },
        {
            "task": "Validate all FDPs, ODPs and rest days across a roster period (full compliance check)",
            "endpoint": "POST /validate/roster",
            "note": "Preferred over calling /validate/sequence and /validate/cumulative separately.",
        },
        {
            "task": "Validate a sequence of FDPs/ODPs without cumulative limits",
            "endpoint": "POST /validate/sequence",
            "note": "Use /validate/roster if you also need cumulative rolling-window checks.",
        },
        {
            "task": "Check rolling-window cumulative flight and duty time limits alone",
            "endpoint": "POST /validate/cumulative",
        },
        {
            "task": "Look up the raw FDP limits table for an appendix",
            "endpoint": "GET /limits/fdp-table/{appendix}",
            "note": "For a computed limit at a specific start time, use /calculate/max-fdp instead.",
        },
        {
            "task": "Look up cumulative limit thresholds for an appendix",
            "endpoint": "GET /limits/cumulative/{appendix}",
        },
        {
            "task": "Retrieve the legislative text of a CAO 48.1 section",
            "endpoint": "GET /sections/{section_id}",
        },
    ],
    "endpoints": [
        # ── Health & Reference ────────────────────────────────────────
        {
            "path": "/health",
            "method": "GET",
            "group": "Health & Reference",
            "summary": "API health and endpoint registry",
            "purpose": (
                "Returns API version, operational status, the list of available and planned "
                "endpoints, and the supported appendices. Use this to confirm the API is "
                "reachable and to discover available routes."
            ),
            "when_to_use": "Connectivity checks, version verification, listing available endpoints.",
            "when_not_to_use": "Never use this for compliance calculations — it is infrastructure only.",
            "parameters": [],
            "example_response_shape": {
                "status": "ok",
                "version": "0.3.0",
                "endpoints": {
                    "available": ["/health", "/validate/fdp", "..."],
                    "planned": [],
                },
                "appendices": [{"id": "1", "title": "Basic Limits", "status": "available"}],
            },
            "common_mistakes": [],
        },
        {
            "path": "/sections",
            "method": "GET",
            "group": "Health & Reference",
            "summary": "Table of contents for CAO 48.1",
            "purpose": (
                "Returns all section and appendix IDs for use with GET /sections/{section_id}. "
                "Fetch this once to discover valid section_id values."
            ),
            "when_to_use": "Discovery — find the section_id you need before fetching the text.",
            "when_not_to_use": "Do not call this on every request — fetch once and cache the IDs.",
            "parameters": [],
            "example_response_shape": {
                "groups": [
                    {
                        "id": "appendices",
                        "title": "Appendices",
                        "sections": [
                            {"id": "appendix-3", "title": "Appendix 3 — Multi-Pilot Operations Except Complex", "type": "appendix"}
                        ],
                    }
                ]
            },
            "common_mistakes": [],
        },
        {
            "path": "/sections/{section_id}",
            "method": "GET",
            "group": "Health & Reference",
            "summary": "Full text of a CAO 48.1 section or appendix",
            "purpose": "Returns the legislative text for a section. Use this to quote the exact rule behind a violation.",
            "when_to_use": "When a user asks for the rule text behind a violation or limit.",
            "when_not_to_use": "Not a compliance check — this is legislative reference text only.",
            "parameters": [
                {
                    "name": "section_id",
                    "in": "path",
                    "type": "string",
                    "required": True,
                    "description": (
                        "Section ID from GET /sections (e.g. 'appendix-3', 'section-13'). "
                        "Not the same as the appendix number — use GET /sections first."
                    ),
                }
            ],
            "example_request": {"path": "/sections/appendix-3"},
            "example_response_shape": {
                "id": "appendix-3",
                "title": "Appendix 3 — Multi-Pilot Operations Except Complex",
                "content": "...(legislative text)...",
            },
            "common_mistakes": [
                "Using a bare appendix number like '3' instead of 'appendix-3' — "
                "call GET /sections first to get the correct IDs."
            ],
        },
        # ── Limits ────────────────────────────────────────────────────
        {
            "path": "/limits/fdp-table/{appendix}",
            "method": "GET",
            "group": "Limits",
            "summary": "FDP lookup table for an appendix",
            "purpose": (
                "Returns the raw FDP limit table: time bands (local start time blocks), "
                "sector-based FDP caps, split-duty rules, and flight time limits. "
                "This is the source data used by POST /calculate/max-fdp."
            ),
            "when_to_use": "When you need to display or reason about the raw FDP table structure.",
            "when_not_to_use": (
                "Do not manually interpolate this table to derive a limit — "
                "use POST /calculate/max-fdp which handles sub-table selection, "
                "WOCL/early-start adjustments, acclimatisation, and split-duty extensions."
            ),
            "parameters": [
                {
                    "name": "appendix",
                    "in": "path",
                    "type": "string",
                    "required": True,
                    "description": "Appendix ID: '1','2','3','4','4A','4B','5','5A','6'. Case-insensitive.",
                }
            ],
            "example_request": {"path": "/limits/fdp-table/3"},
            "example_response_shape": {
                "appendix": "3",
                "title": "Multi-Pilot Operations Except Complex",
                "tables": {
                    "standard": {
                        "table_id": "app3_standard",
                        "rows": [{"time_band": "0600-0659", "sectors": {"1-2": 9.5, "3": 9.0, "4+": 8.5}}],
                    }
                },
                "split_duty": {"available": True},
            },
            "common_mistakes": [
                "Reading the table directly to determine a limit without calling /calculate/max-fdp — "
                "the calculator applies sub-table selection, WOCL/early-start reductions, and split-duty extensions."
            ],
        },
        {
            "path": "/limits/cumulative/{appendix}",
            "method": "GET",
            "group": "Limits",
            "summary": "Cumulative limit thresholds for an appendix",
            "purpose": (
                "Returns the rolling-window thresholds: maximum flight time in 28, 90, 365 days; "
                "maximum duty time in 28 days."
            ),
            "when_to_use": "Displaying or auditing the cumulative limits for an appendix.",
            "when_not_to_use": (
                "For actual compliance checking against real history, use POST /validate/cumulative "
                "or supply prior_fdp_log to POST /validate/roster."
            ),
            "parameters": [
                {
                    "name": "appendix",
                    "in": "path",
                    "type": "string",
                    "required": True,
                    "description": "Appendix ID. Case-insensitive.",
                }
            ],
            "example_response_shape": {
                "appendix": "3",
                "flight_time": {"days_28": 100.0, "days_90": 300.0, "days_365": 1000.0},
                "duty_time": {"days_28": 200.0},
            },
            "common_mistakes": [],
        },
        # ── Calculation ───────────────────────────────────────────────
        {
            "path": "/calculate/max-fdp",
            "method": "POST",
            "group": "Calculation",
            "summary": "Calculate the maximum permissible FDP",
            "purpose": (
                "Given appendix, local start time, sector count and crew configuration, "
                "returns the maximum FDP cap in hours plus whether the start falls in an "
                "early-start (0500-0659 local) or WOCL (0200-0459 local) window."
            ),
            "when_to_use": (
                "Before an FDP starts, to determine the legal limit. "
                "Combine with POST /validate/fdp on completion to check actual compliance."
            ),
            "when_not_to_use": "This returns a limit, not a pass/fail result — use /validate/fdp for that.",
            "parameters": [
                {
                    "name": "appendix",
                    "type": "string",
                    "required": True,
                    "description": "Appendix ID.",
                },
                {
                    "name": "local_start_time_of_day_hours",
                    "type": "number",
                    "required": True,
                    "description": (
                        "LOCAL time of FDP start as decimal hours from midnight (0.0–23.99). "
                        "NOT the UTC time. Example: FDP starts 22:00 UTC, offset +8 → local = 06:00 → supply 6.0. "
                        "This determines which time band row the FDP falls into."
                    ),
                },
                {
                    "name": "sectors",
                    "type": "integer",
                    "required": True,
                    "description": "Number of sectors (takeoff-to-landing segments) in the FDP.",
                },
                {
                    "name": "acclimatisation",
                    "type": "string",
                    "required": False,
                    "description": (
                        "Crew acclimatisation state — only meaningful for Appendix 2. "
                        "'acclimatised': crew has been at departure station ≥3 days. "
                        "'not_acclimatised': <3 days. "
                        "'unknown': API applies the conservative not_acclimatised limits."
                    ),
                    "valid_values": ["acclimatised", "not_acclimatised", "unknown"],
                    "default": "unknown",
                },
                {
                    "name": "augmented_crew",
                    "type": "boolean",
                    "required": False,
                    "description": (
                        "True if a relief crew member is carried (3- or 4-pilot augmented operation). "
                        "For Appendix 2 only. When True, also supply augmented_crew_size ('3' or '4')."
                    ),
                    "default": False,
                },
                {
                    "name": "split_duty_rest_hours",
                    "type": "number",
                    "required": False,
                    "description": (
                        "Duration of the in-FDP rest break if split duty applies (hours). "
                        "The API computes the FDP extension from this, subject to type and cap rules."
                    ),
                },
                {
                    "name": "split_duty_facility",
                    "type": "string",
                    "required": False,
                    "description": "Type of rest facility during the split-duty break.",
                    "valid_values": ["sleeping", "resting"],
                },
            ],
            "example_request": {
                "appendix": "3",
                "local_start_time_of_day_hours": 6.0,
                "sectors": 3,
                "acclimatisation": "acclimatised",
            },
            "example_response_shape": {
                "appendix": "3",
                "max_fdp_hours": 10.0,
                "time_band": "0600-0659",
                "is_early_start": True,
                "crosses_wocl": False,
                "notes": [],
            },
            "common_mistakes": [
                "Supplying UTC time instead of LOCAL time for local_start_time_of_day_hours. "
                "Convert: local_hours = (utc_start_hour + local_offset) % 24.",
                "Omitting augmented_crew=True for 3- or 4-pilot operations — the FDP limit is higher but "
                "requires different table selection.",
                "Using acclimatisation='unknown' when the crew is known to be acclimatised — "
                "this gives a more conservative limit than necessary.",
            ],
        },
        {
            "path": "/calculate/min-off-duty",
            "method": "POST",
            "group": "Calculation",
            "summary": "Calculate the minimum required off-duty period",
            "purpose": (
                "Given an appendix and the preceding FDP's actual duration, returns the minimum "
                "off-duty period required before the next FDP may start, in hours."
            ),
            "when_to_use": "After an FDP completes, to determine when crew may next commence duty.",
            "when_not_to_use": "For pass/fail validation of a known off-duty period, use /validate/off-duty.",
            "parameters": [
                {
                    "name": "appendix",
                    "type": "string",
                    "required": True,
                    "description": "Appendix ID.",
                },
                {
                    "name": "preceding_fdp_hours",
                    "type": "number",
                    "required": True,
                    "description": "Actual duration of the preceding FDP in hours.",
                },
                {
                    "name": "includes_local_night",
                    "type": "boolean",
                    "required": False,
                    "description": (
                        "True if the off-duty period will include a local night opportunity "
                        "(local time crossing 0000-0559). Affects minimum rest in some appendices."
                    ),
                    "default": False,
                },
            ],
            "example_request": {
                "appendix": "3",
                "preceding_fdp_hours": 10.0,
                "includes_local_night": True,
            },
            "example_response_shape": {
                "appendix": "3",
                "min_off_duty_hours": 10.0,
                "notes": [],
            },
            "common_mistakes": [],
        },
        # ── Validation — single FDP ───────────────────────────────────
        {
            "path": "/validate/fdp",
            "method": "POST",
            "group": "Validation",
            "summary": "Validate a single FDP",
            "purpose": (
                "Checks a single completed FDP against all applicable CAO 48.1 rules for the given "
                "appendix. Returns every check performed (passed and failed) plus violations with "
                "clause references and remediation suggestions."
            ),
            "when_to_use": "When you have actual FDP start/end times and want a full single-FDP compliance check.",
            "when_not_to_use": (
                "For consecutive-FDP rules (consecutive early starts, §13.2 WOCL limits, consecutive "
                "extension restrictions), use /validate/sequence or /validate/roster — those track "
                "state across FDPs."
            ),
            "parameters": [
                {
                    "name": "appendix",
                    "type": "string",
                    "required": True,
                    "description": "Appendix ID.",
                },
                {
                    "name": "fdp_start_utc",
                    "type": "string (ISO 8601 UTC)",
                    "required": True,
                    "description": "FDP commencement time in UTC.",
                },
                {
                    "name": "fdp_end_utc",
                    "type": "string (ISO 8601 UTC)",
                    "required": True,
                    "description": "FDP end time in UTC.",
                },
                {
                    "name": "local_time_offset_hours",
                    "type": "number",
                    "required": True,
                    "description": (
                        "Hours ahead of UTC at the departure station (e.g. AEST = 10.0, AEDT = 11.0, IST = 5.5). "
                        "Used to determine the local start time of day for FDP table lookup."
                    ),
                },
                {
                    "name": "sectors",
                    "type": "integer",
                    "required": True,
                    "description": "Number of sectors (takeoff-to-landing segments) in the FDP.",
                },
                {
                    "name": "crosses_wocl",
                    "type": "boolean",
                    "required": True,
                    "description": (
                        "True if the FDP crosses the Window of Circadian Low (0200-0559 local time). "
                        "Relevant for Appendix 2, 3, 4. Set this yourself based on local times — "
                        "the API does not derive it from UTC, because DST and offset logic is your responsibility."
                    ),
                },
                {
                    "name": "actual_flight_time_hours",
                    "type": "number",
                    "required": False,
                    "description": "Actual block-to-block flight time in hours. If provided, checked against per-FDP flight time limit.",
                },
                {
                    "name": "actual_duty_time_hours",
                    "type": "number",
                    "required": False,
                    "description": "Total duty time in hours (may exceed FDP if post-flight duty applies).",
                },
                {
                    "name": "acclimatisation",
                    "type": "string",
                    "required": False,
                    "description": "Crew acclimatisation state (Appendix 2 only). See /calculate/max-fdp for definition.",
                    "valid_values": ["acclimatised", "not_acclimatised", "unknown"],
                    "default": "unknown",
                },
                {
                    "name": "augmented_crew",
                    "type": "boolean",
                    "required": False,
                    "description": "True for 3- or 4-pilot augmented operations (Appendix 2 only).",
                    "default": False,
                },
                {
                    "name": "extension",
                    "type": "string",
                    "required": False,
                    "description": (
                        "Commander extension invoked. "
                        "'captain_discretion' — pilot-in-command discretion under CAO 48.1. "
                        "'approved_unforeseen' — operator-approved unforeseen circumstances extension."
                    ),
                    "valid_values": ["captain_discretion", "approved_unforeseen"],
                },
                {
                    "name": "extension_hours",
                    "type": "number",
                    "required": False,
                    "description": "Amount of extension invoked in hours. Must be ≤ the applicable extension cap.",
                },
                {
                    "name": "preceding_fdp_hours",
                    "type": "number",
                    "required": False,
                    "description": (
                        "Actual duration of the immediately preceding FDP in hours. "
                        "Required to validate the consecutive-extension restriction: "
                        "if both this FDP and the preceding FDP are extended, tighter limits apply."
                    ),
                },
                {
                    "name": "preceding_fdp_was_extended",
                    "type": "boolean",
                    "required": False,
                    "description": "True if the immediately preceding FDP was also extended.",
                    "default": False,
                },
                {
                    "name": "split_duty_rest_hours",
                    "type": "number",
                    "required": False,
                    "description": "Duration of the in-FDP rest break for split duty in hours.",
                },
                {
                    "name": "split_duty_facility",
                    "type": "string",
                    "required": False,
                    "description": "Type of rest facility.",
                    "valid_values": ["sleeping", "resting"],
                },
            ],
            "example_request": {
                "appendix": "3",
                "fdp_start_utc": "2026-03-24T22:00:00Z",
                "fdp_end_utc": "2026-03-25T08:00:00Z",
                "local_time_offset_hours": 8.0,
                "sectors": 3,
                "crosses_wocl": False,
                "actual_flight_time_hours": 7.5,
                "actual_duty_time_hours": 10.0,
            },
            "example_response_shape": {
                "valid": True,
                "appendix": "3",
                "fdp_duration_hours": 10.0,
                "max_fdp_hours": 10.0,
                "checks": [{"check": "fdp_duration", "passed": True, "rule": "CAO 48.1 §..."}],
                "violations": [],
                "warnings": [],
            },
            "common_mistakes": [
                "Setting crosses_wocl=False when the FDP runs overnight through 0200-0559 local — "
                "derive this from the local start and end times before calling.",
                "Omitting preceding_fdp_hours and preceding_fdp_was_extended when validating a "
                "second consecutive extended FDP — the consecutive-extension check will be skipped.",
                "Supplying local_time_offset_hours without accounting for Daylight Saving Time.",
                "Using appendix '2' for non-complex multi-pilot aircraft — use appendix '3'.",
            ],
        },
        # ── Validation — off-duty ─────────────────────────────────────
        {
            "path": "/validate/off-duty",
            "method": "POST",
            "group": "Validation",
            "summary": "Validate an off-duty period between two FDPs",
            "purpose": (
                "Checks that an off-duty period meets the minimum required rest for the following FDP. "
                "Returns the minimum required hours and whether the actual rest satisfies it."
            ),
            "when_to_use": "When you have an actual off-duty start/end and need to verify it meets the minimum.",
            "when_not_to_use": (
                "For a sequence of FDPs, use /validate/sequence or /validate/roster — "
                "they track context (preceding FDP duration) across events automatically."
            ),
            "parameters": [
                {
                    "name": "appendix",
                    "type": "string",
                    "required": True,
                    "description": "Appendix ID.",
                },
                {
                    "name": "start_utc",
                    "type": "string (ISO 8601 UTC)",
                    "required": True,
                    "description": "Start of the off-duty period in UTC.",
                },
                {
                    "name": "end_utc",
                    "type": "string (ISO 8601 UTC)",
                    "required": True,
                    "description": "End of the off-duty period in UTC.",
                },
                {
                    "name": "duration_hours",
                    "type": "number",
                    "required": True,
                    "description": (
                        "Actual duration in hours. Must be consistent with end_utc − start_utc. "
                        "Both are required because the API validates their consistency."
                    ),
                },
                {
                    "name": "preceding_fdp_hours",
                    "type": "number",
                    "required": False,
                    "description": "Duration of the FDP that preceded this off-duty period.",
                },
                {
                    "name": "includes_local_night",
                    "type": "boolean",
                    "required": False,
                    "description": (
                        "True if this off-duty period includes a local night opportunity "
                        "(0000-0559 local falls within the period). Affects qualified rest classification."
                    ),
                    "default": False,
                },
                {
                    "name": "location",
                    "type": "string",
                    "required": False,
                    "description": "Rest location type.",
                    "valid_values": ["home_base", "suitable_accommodation", "away"],
                },
            ],
            "example_request": {
                "appendix": "3",
                "start_utc": "2026-03-25T08:00:00Z",
                "end_utc": "2026-03-25T22:00:00Z",
                "duration_hours": 14.0,
                "preceding_fdp_hours": 10.0,
                "includes_local_night": True,
                "location": "away",
            },
            "example_response_shape": {
                "valid": True,
                "appendix": "3",
                "actual_duration_hours": 14.0,
                "min_required_hours": 10.0,
                "checks": [{"check": "minimum_rest", "passed": True, "rule": "CAO 48.1 §..."}],
                "violations": [],
                "warnings": [],
            },
            "common_mistakes": [
                "Supplying duration_hours that does not match end_utc − start_utc — be consistent.",
                "Setting includes_local_night=False for an overnight rest — check whether "
                "0000-0559 local falls within the rest window.",
            ],
        },
        # ── Validation — cumulative ───────────────────────────────────
        {
            "path": "/validate/cumulative",
            "method": "POST",
            "group": "Validation",
            "summary": "Validate rolling-window cumulative limits",
            "purpose": (
                "Checks whether cumulative flight time and duty time over rolling 28-day, 90-day, "
                "and 365-day windows are within the appendix limits. Supply either a full fdp_log "
                "(the API computes windows from it) or a pre-aggregated summary."
            ),
            "when_to_use": (
                "Standalone cumulative compliance check. "
                "Note: POST /validate/roster runs this automatically — "
                "prefer /validate/roster if you are also validating FDP/ODP details."
            ),
            "when_not_to_use": "Not for individual FDP validation — use /validate/fdp for that.",
            "parameters": [
                {
                    "name": "appendix",
                    "type": "string",
                    "required": True,
                    "description": "Appendix ID.",
                },
                {
                    "name": "as_of_utc",
                    "type": "string (ISO 8601 UTC)",
                    "required": True,
                    "description": (
                        "Reference date for rolling-window calculations. "
                        "Typically today's date or the end of the period being checked. "
                        "The 28-day window is as_of_utc − 28 days to as_of_utc, etc."
                    ),
                },
                {
                    "name": "fdp_log",
                    "type": "array",
                    "required": False,
                    "description": (
                        "List of historical FDP records to compute windows from. "
                        "Include at least the past 365 days. "
                        "Each record: fdp_start_utc, fdp_end_utc, actual_flight_time_hours, "
                        "actual_duty_time_hours, local_time_offset_hours. "
                        "Either fdp_log or summary must be provided."
                    ),
                },
                {
                    "name": "summary",
                    "type": "object",
                    "required": False,
                    "description": (
                        "Pre-aggregated cumulative totals (alternative to fdp_log). "
                        "Fields: flight_time_28d, flight_time_90d, flight_time_365d, duty_time_28d. "
                        "Use when you have pre-computed totals rather than individual FDP records."
                    ),
                },
            ],
            "example_request": {
                "appendix": "3",
                "as_of_utc": "2026-03-29T00:00:00Z",
                "fdp_log": [
                    {
                        "fdp_start_utc": "2026-03-24T22:00:00Z",
                        "fdp_end_utc": "2026-03-25T08:00:00Z",
                        "actual_flight_time_hours": 7.5,
                        "actual_duty_time_hours": 10.0,
                        "local_time_offset_hours": 8.0,
                    }
                ],
            },
            "example_response_shape": {
                "valid": True,
                "appendix": "3",
                "limits": {"flight_time_28d": 100.0, "flight_time_90d": 300.0, "flight_time_365d": 1000.0},
                "totals": {"flight_time_28d": 7.5, "flight_time_90d": 7.5, "flight_time_365d": 7.5},
                "checks": [{"check": "flight_time_28d", "passed": True, "rule": "CAO 48.1 §..."}],
                "violations": [],
            },
            "common_mistakes": [
                "Providing only recent FDPs and omitting older flights within the 90/365-day windows — "
                "supply the full available history.",
                "Providing neither fdp_log nor summary — one is required.",
                "Using summary with zeros when actual history exists — this undercounts cumulative usage "
                "and will give a falsely passing result.",
            ],
        },
        # ── Validation — sequence ─────────────────────────────────────
        {
            "path": "/validate/sequence",
            "method": "POST",
            "group": "Validation",
            "summary": "Validate a chronological FDP/ODP sequence",
            "purpose": (
                "Validates each FDP and off-duty period in chronological order, tracking cross-FDP "
                "state: consecutive early-start counts, §13.2 WOCL violation checks, and preceding "
                "FDP context for extension eligibility. Does not run cumulative rolling-window checks."
            ),
            "when_to_use": "A sequence of FDPs and ODPs needing per-FDP validation plus cross-FDP rules, without cumulative checks.",
            "when_not_to_use": (
                "If you also need cumulative rolling-window limits checked, use /validate/roster. "
                "For a single FDP, /validate/fdp is simpler."
            ),
            "parameters": [
                {
                    "name": "appendix",
                    "type": "string",
                    "required": True,
                    "description": "Appendix ID.",
                },
                {
                    "name": "events",
                    "type": "array",
                    "required": True,
                    "description": (
                        "Chronological list of events. Discriminated by event_type. "
                        "FDP events (event_type='fdp'): fdp_start_utc, fdp_end_utc, "
                        "local_time_offset_hours, sectors, actual_flight_time_hours, "
                        "actual_duty_time_hours. ODP events (event_type='off_duty'): "
                        "start_utc, end_utc, duration_hours, location. Events must be in "
                        "chronological order. Do not omit ODPs between FDPs — the origin "
                        "derives whether each FDP infringes the WOCL and whether each ODP "
                        "includes a local night purely from timestamps and offsets, so a "
                        "missing ODP breaks the §13.2 consecutive-WOCL sequence. There is no "
                        "crosses_wocl or includes_local_night input field — neither is "
                        "accepted; both are always computed server-side and surfaced in "
                        "calculation_notes (e.g. 'FDP 2: crosses_wocl=True (derived, not "
                        "caller-supplied)')."
                    ),
                },
            ],
            "example_request": {
                "appendix": "3",
                "events": [
                    {
                        "event_type": "fdp",
                        "fdp_start_utc": "2026-03-24T22:00:00Z",
                        "fdp_end_utc": "2026-03-25T08:00:00Z",
                        "local_time_offset_hours": 8.0,
                        "sectors": 3,
                        "actual_flight_time_hours": 7.5,
                        "actual_duty_time_hours": 10.0,
                    },
                    {
                        "event_type": "off_duty",
                        "start_utc": "2026-03-25T08:00:00Z",
                        "end_utc": "2026-03-25T22:00:00Z",
                        "duration_hours": 14.0,
                        "location": "away",
                    },
                ],
            },
            "example_response_shape": {
                "valid": True,
                "appendix": "3",
                "violations": [],
                "checks": [{"check": "fdp1_fdp_within_limit", "passed": True, "clause": "CAO 48.1 Appendix 3"}],
                "warnings": [],
                "calculation_notes": [
                    "FDP 1: crosses_wocl=False (derived, not caller-supplied)",
                    "ODP 1: includes_local_night=True (derived, not caller-supplied)",
                ],
            },
            "common_mistakes": [
                "Omitting ODPs between FDPs — the §13.2 WOCL consecutive counter resets when an ODP "
                "spans a full local night, which the origin derives from the ODP's own timestamps, "
                "so skipping ODPs gives wrong consecutive WOCL counts.",
                "Assuming crosses_wocl or includes_local_night must be sent — neither is an "
                "accepted field; both are computed server-side from timestamps.",
                "Sending events out of chronological order — the validator processes them sequentially.",
            ],
        },
        # ── Validation — roster ───────────────────────────────────────
        {
            "path": "/validate/roster",
            "method": "POST",
            "group": "Validation",
            "summary": "Full roster validation",
            "purpose": (
                "The most comprehensive endpoint. Validates every FDP, ODP, and rest day in a "
                "roster period in a single call: per-FDP compliance, §13.2 WOCL sequence checks, "
                "and rolling-window cumulative limits. Optionally accepts prior FDP history for "
                "accurate cumulative windows."
            ),
            "when_to_use": "Complete roster compliance checking. Prefer this over calling /validate/sequence and /validate/cumulative separately.",
            "when_not_to_use": (
                "A single FDP in isolation → use /validate/fdp. "
                "Standalone cumulative tracking without FDP details → use /validate/cumulative."
            ),
            "parameters": [
                {
                    "name": "appendix",
                    "type": "string",
                    "required": True,
                    "description": "Appendix ID.",
                },
                {
                    "name": "roster_start_utc",
                    "type": "string (ISO 8601 UTC)",
                    "required": True,
                    "description": "Start of the roster period in UTC.",
                },
                {
                    "name": "roster_end_utc",
                    "type": "string (ISO 8601 UTC)",
                    "required": True,
                    "description": "End of the roster period in UTC.",
                },
                {
                    "name": "events",
                    "type": "array",
                    "required": True,
                    "description": (
                        "Chronological list of events. Three event_type values are supported: "
                        "'fdp' — same fields as /validate/fdp; "
                        "'off_duty' — same fields as /validate/sequence ODP events, plus "
                        "following_includes_local_night (still caller-supplied — used only for "
                        "the §10.4 reduced-ODP eligibility check, not for §13.2); "
                        "'rest_day' — start_utc, end_utc, count (integer ≥1), includes_local_night. "
                        "Rest days reset the consecutive early-start and WOCL counters when "
                        "count ≥ 2 or (count ≥ 1 and includes_local_night is True). "
                        "'fdp' events have no crosses_wocl field and 'off_duty' events have no "
                        "includes_local_night field — neither is accepted as input; both are "
                        "always computed server-side from each event's own timestamps and offset "
                        "and returned on the corresponding fdp_results / odp_results item "
                        "(crosses_wocl, includes_local_night respectively). Only rest_day's "
                        "includes_local_night remains caller-supplied, since a rest day is defined "
                        "by a day count rather than a single offset period. Minimum 1 event."
                    ),
                },
                {
                    "name": "prior_fdp_log",
                    "type": "array",
                    "required": False,
                    "description": (
                        "FDP records from before this roster period, for accurate cumulative window calculations. "
                        "Include at least the past 365 days. "
                        "If omitted, the cumulative check only sees FDPs within this roster period — "
                        "prior usage is invisible to the validator."
                    ),
                },
                {
                    "name": "prior_summary",
                    "type": "object",
                    "required": False,
                    "description": (
                        "Pre-aggregated prior cumulative totals (alternative to prior_fdp_log). "
                        "Fields: flight_time_28d, flight_time_90d, flight_time_365d, duty_time_28d. "
                        "Use when individual prior FDP records are not available."
                    ),
                },
            ],
            "example_request": {
                "appendix": "3",
                "roster_start_utc": "2026-03-24T00:00:00Z",
                "roster_end_utc": "2026-03-27T00:00:00Z",
                "events": [
                    {
                        "event_type": "fdp",
                        "fdp_start_utc": "2026-03-24T22:00:00Z",
                        "fdp_end_utc": "2026-03-25T08:00:00Z",
                        "local_time_offset_hours": 8.0,
                        "sectors": 3,
                        "actual_flight_time_hours": 7.5,
                        "actual_duty_time_hours": 10.0,
                    },
                    {
                        "event_type": "off_duty",
                        "start_utc": "2026-03-25T08:00:00Z",
                        "end_utc": "2026-03-25T22:00:00Z",
                        "duration_hours": 14.0,
                        "location": "away",
                    },
                    {
                        "event_type": "fdp",
                        "fdp_start_utc": "2026-03-25T22:00:00Z",
                        "fdp_end_utc": "2026-03-26T08:00:00Z",
                        "local_time_offset_hours": 8.0,
                        "sectors": 3,
                        "actual_flight_time_hours": 8.0,
                        "actual_duty_time_hours": 10.0,
                    },
                ],
                "prior_fdp_log": [
                    {
                        "fdp_start_utc": "2026-03-01T22:00:00Z",
                        "fdp_end_utc": "2026-03-02T08:00:00Z",
                        "actual_flight_time_hours": 8.0,
                        "actual_duty_time_hours": 10.0,
                        "local_time_offset_hours": 8.0,
                    }
                ],
            },
            "example_response_shape": {
                "valid": True,
                "appendix": "3",
                "roster_start_utc": "2026-03-24T00:00:00Z",
                "roster_end_utc": "2026-03-27T00:00:00Z",
                "summary": {
                    "total_fdps": 2,
                    "total_off_duty_periods": 1,
                    "total_rest_days": 0,
                    "total_flight_time_hours": 15.5,
                    "total_duty_time_hours": 20.0,
                    "fdp_violations": 0,
                    "odp_violations": 0,
                    "sequence_violations": 0,
                    "cumulative_violations": 0,
                    "total_violations": 0,
                },
                "fdp_results": [
                    {"fdp_number": 1, "crosses_wocl": False, "valid": True, "violations": [], "checks": []}
                ],
                "odp_results": [
                    {"odp_number": 1, "includes_local_night": True, "valid": True, "violations": []}
                ],
                "sequence_checks": [],
                "sequence_violations": [],
                "cumulative_result": {"valid": True, "violations": []},
                "all_violations": [],
                "warnings": [],
            },
            "common_mistakes": [
                "Not providing prior_fdp_log or prior_summary — the cumulative check will only see "
                "flights within the current roster period, missing earlier usage.",
                "Omitting ODPs between FDPs — affects WOCL counter resets and ODP validation.",
                "Sending an empty events list — at least one event is required.",
                "Using prior_summary with zeros when actual prior history exists — undercounts usage "
                "and gives a falsely passing cumulative result.",
                "Assuming crosses_wocl or includes_local_night must be sent on 'fdp'/'off_duty' "
                "events — neither is an accepted field; both are computed server-side from each "
                "event's own timestamps and offset (and, for acclimatised Appendix 2 FDPs, "
                "acclimatised_time_offset_hours) and returned in fdp_results / odp_results.",
            ],
        },
        # ── Guide ─────────────────────────────────────────────────────
        {
            "path": "/guide",
            "method": "GET",
            "group": "Guide",
            "summary": "API usage guide (this document)",
            "purpose": (
                "Returns this structured guide. Call once at the start of a session to understand "
                "every endpoint, its parameters, worked examples, and common mistakes."
            ),
            "when_to_use": "At session start, before making compliance calls.",
            "when_not_to_use": "Do not call this on every request — it is a one-time orientation document.",
            "parameters": [],
            "example_response_shape": {
                "title": "CAO 48.1 Compliance API — Integration Guide",
                "version": "0.3.0",
                "endpoints": ["..."],
            },
            "common_mistakes": [],
        },
    ],
}

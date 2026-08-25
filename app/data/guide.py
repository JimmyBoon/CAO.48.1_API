"""
Guide data for the GET /guide endpoint.

Structured documentation for every endpoint in the CAO 48.1 Compliance API,
designed to be fetched once by an LLM or integration at the start of a session.

**Parameter documentation is generated, not written here.** Each POST entry
names its `request_model`; `build_guide()` expands that into a `parameters`
list from the running Pydantic model. Hand-maintained parameter prose is what
drifted: the guide went on describing `local_start_time_of_day_hours`, a
boolean `augmented_crew`, a string `extension`, and an
`acclimatisation: "not_acclimatised"` enum value long after the API stopped
accepting any of them, so a caller following the guide got a 422.

What stays hand-written is the prose that cannot be derived from a type:
`purpose`, `when_to_use`, `when_not_to_use`, `common_mistakes`, and the worked
examples. `tests/test_guide_contract.py` holds those to account — every
parameter named in the prose must exist on the model, and every
`example_request` must execute successfully against its own endpoint.

The version field is a placeholder; the route handler overwrites it with
settings.app_version at runtime.
"""

from __future__ import annotations

from typing import Any

_REQUEST_MODELS: dict[str, Any] = {}


def _request_models() -> dict[str, Any]:
    """Resolve request-model names lazily to avoid a circular import."""
    if not _REQUEST_MODELS:
        from app.models import calculation, validation

        for module in (calculation, validation):
            for name in dir(module):
                obj = getattr(module, name)
                if isinstance(obj, type) and name.endswith("Request"):
                    _REQUEST_MODELS[name] = obj
    return _REQUEST_MODELS


def build_guide(version: str | None = None) -> dict:
    """
    Return the guide with `parameters` generated from the request models.

    Endpoints that name a `request_model` get their parameter list built from
    that model, so the guide cannot describe a field the API does not accept,
    nor omit one it requires.
    """
    import copy

    from app.data.guide_params import describe_model

    guide = copy.deepcopy(GUIDE)
    if version is not None:
        guide["version"] = version

    # Capability flags are derived from the rule tables and the corpus, not
    # asserted by hand. has_wocl_rules was False for Appendix 6, which does
    # have consecutive WOCL and early-start limits (§10), and Appendix 4B was
    # flagged as having no night rules at all when it has §8.
    from app.data.fdp_tables import FDP_CONFIGS
    from app.parser import get_legislation

    legislation = get_legislation()
    for entry in guide["appendices"]:
        config = FDP_CONFIGS.get(entry["id"])
        if config is None:
            continue
        entry["has_wocl_rules"] = bool(
            config.wocl_early_start and config.early_starts.available
        )
        entry["has_augmented_crew"] = "augmented_acclimatised" in config.tables
        group = legislation.group_index.get(f"APPENDIX {entry['id']}")
        night = [
            section.id for section in (group.sections if group else [])
            if "late-night" in section.title.lower()
        ]
        entry["has_night_operation_limits"] = bool(night)
        if night:
            entry["night_operation_limits_section"] = night[0]

    from app.data.guide_params import response_shape

    # Response models come from the routes themselves, so the documented shape
    # is whatever FastAPI actually returns.
    from app.main import app as _app

    response_models: dict[tuple[str, str], Any] = {}
    for route in _app.routes:
        model = getattr(route, "response_model", None)
        if model is None or not hasattr(model, "model_fields"):
            continue
        path = route.path.replace(guide["api_base_path"], "")
        for method in getattr(route, "methods", set()):
            response_models[(method, path)] = model

    models = _request_models()
    for endpoint in guide["endpoints"]:
        model = response_models.get((endpoint["method"], endpoint["path"]))
        if model is not None:
            endpoint["example_response_shape"] = response_shape(model)
            endpoint["response_generated_from"] = model.__name__
        model_name = endpoint.get("request_model")
        if not model_name:
            endpoint.setdefault("parameters", [])
            continue
        model = models[model_name]
        endpoint["parameters"] = describe_model(model)
        endpoint["parameters_generated_from"] = model_name

        # The worked example comes from the model's own schema example, so it
        # is the same payload the OpenAPI docs show and cannot drift from what
        # the endpoint accepts. Three of the hand-written ones had already
        # drifted far enough to 422.
        examples = (model.model_config.get("json_schema_extra") or {}).get("examples")
        if examples:
            endpoint["example_request"] = examples[0]
    return guide


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
                "Has sub-tables for acclimatised and unknown-acclimatisation crew, each "
                "with an augmented-crew variant. Supply `acclimatisation` (an object: "
                "{state, acclimatised_time_offset_hours}) and, for augmented operations, "
                "`augmented_crew` (an object: {additional_fcms, rest_facility_class, "
                "in_flight_rest_hours_per_fcm}) to select the correct table. The §5.3 "
                "conditions gate the augmented tables — see /validate/fdp."
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
                "version": "0.5.0",
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
                        "id": "APPENDIX 3",
                        "title": "MULTI-PILOT OPERATIONS EXCEPT COMPLEX",
                        "type": "appendix",
                        "sections": [
                            {
                                "id": "APPENDIX 3.2",
                                "section_number": "2",
                                "title": "FDP and flight time limits",
                            }
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
                        "Section ID exactly as GET /sections returns it — e.g. 'APPENDIX 3' "
                    "for a whole appendix, 'APPENDIX 3.3' for a clause, or '13' "
                    "for a numbered section of the CAO itself. "
                        "Not the same as the appendix number — use GET /sections first."
                    ),
                }
            ],
            "example_request": {"path": "/sections/APPENDIX 3.3"},
            "example_response_shape": {
                "section_id": "APPENDIX 3.3",
                "title": "Increase in FDP limits by split duty",
                "section_number": "3",
                "parent_id": "APPENDIX 3",
                "parent_title": "MULTI-PILOT OPERATIONS EXCEPT COMPLEX",
                "text": "3.1 Subject to subclause 3.4, where an FDP contains a "
                        "split-duty rest period of at least 4 consecutive hours ...",
                "disclaimer": "This output is derived from Civil Aviation Order "
                              "48.1 Instrument 2019 ...",
            },
            "common_mistakes": [
                "Lower-casing or hyphenating the id — 'appendix-3' is NOT accepted; "
                "use 'APPENDIX 3' exactly as GET /sections returns it. "
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
                "table_id": "Table 2.1",
                "lookup_key": "local_time_and_sectors",
                "flight_time_limit_hours": 10.5,
                "rows": [
                    {
                        "time_band": "0000-0459",
                        "sectors": {"1-3": 10.0, "4": 9.5, "5": 9.0,
                                    "6": 8.5, "7": 8.0, "8+": 7.5},
                    }
                ],
                "split_duty_cap_hours": 16.0,
                "post_split_max_hours": 6.0,
                "notes": "",
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
                "flight_time": {
                    "period_28d_hours": 100.0,
                    "period_365d_hours": 1000.0,
                    "period_168h_hours": None,
                    "period_90d_hours": None,
                    "period_384h_hours": None,
                },
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
            "request_model": "MaxFdpRequest",
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
                "Supplying a local wall-clock time instead of a UTC instant. The API takes "
                "`fdp_start_utc` (a UTC ISO 8601 timestamp) plus "
                "`local_time_offset_hours`, and derives local time itself. "
                "The API does the conversion: it reads fdp_start_utc and applies "
                "local_time_offset_hours to get the local time of day for the "
                "table lookup. Offsets outside [-12, +14] are rejected with a "
                "422 rather than wrapped.",
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
            "request_model": "MinOffDutyRequest",
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
            "request_model": "ValidateFdpRequest",
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
                "Omitting `preceding_fdp` (an object with start_utc, end_utc, duration_hours "
                "and location) when validating a "
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
            "request_model": "ValidateOffDutyRequest",
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
            "request_model": "ValidateCumulativeRequest",
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
                "limits": {"flight_time_28d": 100.0, "flight_time_365d": 1000.0,
                           "duty_time_168h": 60.0, "duty_time_336h": 100.0},
                "totals": {"flight_time_28d": 7.5, "flight_time_365d": 7.5,
                           "duty_time_168h": 10.0, "duty_time_336h": 10.0},
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
            "request_model": "ValidateSequenceRequest",
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
            "request_model": "ValidateRosterRequest",
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
                "version": "0.5.0",
                "endpoints": ["..."],
            },
            "common_mistakes": [],
        },
    ],
}

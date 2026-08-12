"""
Guide data for the GET /guide endpoint.

Structured documentation for every endpoint in the CAO 48.1 Compliance API,
designed to be fetched once by an LLM or integration at the start of a session.

**How this file works.** Only the editorial content lives here — what an
endpoint is for, when to reach for it instead of another one, and the mistakes
integrators actually make. Every parameter list, response field list and worked
example is generated from the live Pydantic models by `guide_builder`, at import
time. That is deliberate: the previous hand-maintained version of this file
documented a `local_start_time_of_day_hours` parameter the API had stopped
accepting, a flat parameter set for /calculate/min-off-duty that had since
become a nested object, an acclimatisation enum value the API rejects, and a
three-day acclimatisation rule that appears nowhere in CAO 48.1 — while omitting
`adjustments[]` and `acclimatised_time_offset_hours` entirely. Generated
documentation cannot drift from the code it documents.

If you are adding an endpoint: add a narrative entry to ENDPOINT_NARRATIVES and
point it at the request and response models. The parameters look after
themselves.
"""

from __future__ import annotations

from app.data.guide_builder import describe_endpoint
from app.models.acclimatisation import (
    AcclimatisationRequest,
    AcclimatisationResponse,
    AdaptationTableResponse,
)
from app.models.calculation import (
    MaxFdpRequest,
    MaxFdpResponse,
    MinOffDutyRequest,
    MinOffDutyResponse,
)
from app.models.health import HealthResponse
from app.models.limits import CumulativeLimitsResponse, FdpTableResponse
from app.models.sections import SectionDetailResponse, TableOfContentsResponse
from app.models.validation import (
    RosterValidationResponse,
    ValidateCumulativeRequest,
    ValidateFdpRequest,
    ValidateOffDutyRequest,
    ValidateRosterRequest,
    ValidateSequenceRequest,
    ValidationResponse,
)

# ─── Reusable path parameter descriptions ─────────────────────────────

_APPENDIX_PATH_PARAM = {
    "name": "appendix",
    "in": "path",
    "type": "string (enum)",
    "required": True,
    "valid_values": ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"],
    "description": "Appendix identifier. Case-insensitive for the lettered ones.",
}

_SECTION_PATH_PARAM = {
    "name": "section_id",
    "in": "path",
    "type": "string",
    "required": True,
    "description": (
        "Section identifier. Group-level: 'PART 1', 'APPENDIX 2'. "
        "Section-level: '6' (Definitions), '7' (Determination of "
        "acclimatisation), 'APPENDIX 3.2'. Use GET /sections to discover IDs."
    ),
}


# ═══════════════════════════════════════════════════════════════════════
# Editorial content — hand-written, per endpoint
# ═══════════════════════════════════════════════════════════════════════

ENDPOINT_NARRATIVES: list[dict] = [
    {
        "path": "/health",
        "method": "GET",
        "group": "Health",
        "summary": "API status and feature discovery",
        "purpose": (
            "Confirms the API is running and reports the version, the supported "
            "appendices and which endpoints are live versus planned."
        ),
        "when_to_use": (
            "At the start of a session, to discover what this deployment "
            "supports before assuming an endpoint exists."
        ),
        "when_not_to_use": (
            "Not a compliance endpoint — it tells you nothing about a duty period."
        ),
        "response_model": HealthResponse,
        "common_mistakes": [
            "Assuming the endpoint list is static across deployments — read it "
            "rather than hard-coding paths.",
        ],
    },
    {
        "path": "/sections",
        "method": "GET",
        "group": "Regulatory Content",
        "summary": "Table of contents for CAO 48.1",
        "purpose": (
            "Lists every Part and Appendix with its constituent sections and "
            "their IDs."
        ),
        "when_to_use": (
            "To discover section IDs before fetching text, or to render a "
            "navigable index of the instrument."
        ),
        "when_not_to_use": (
            "It returns structure, not text — use /sections/{section_id} for that."
        ),
        "response_model": TableOfContentsResponse,
        "common_mistakes": [
            "Guessing section IDs instead of reading them from here.",
        ],
    },
    {
        "path": "/sections/{section_id}",
        "method": "GET",
        "group": "Regulatory Content",
        "summary": "Full text of a section, Part or Appendix",
        "purpose": (
            "Returns the legislative text, so a validation result can be shown "
            "alongside the rule that produced it."
        ),
        "when_to_use": (
            "To cite or display the rule behind a violation. Section 6 holds the "
            "definitions — including 'acclimatised time', 'local night' and "
            "'time zone' — and section 7 the determination of acclimatisation."
        ),
        "when_not_to_use": (
            "Do not parse the text to reimplement a calculation. Call the "
            "calculation endpoints so the two can never disagree."
        ),
        "path_parameters": [_SECTION_PATH_PARAM],
        "response_model": SectionDetailResponse,
        "common_mistakes": [
            "Requesting a lower-case or hyphenated ID such as 'appendix-3' "
            "instead of 'APPENDIX 3'.",
        ],
    },
    {
        "path": "/limits/fdp-table/{appendix}",
        "method": "GET",
        "group": "Limits",
        "summary": "FDP lookup table for an appendix",
        "purpose": (
            "Returns the raw FDP time-band table: bands, sector columns, split "
            "duty caps and any per-FDP flight time limit."
        ),
        "when_to_use": (
            "To render a reference table, or to show a crew member the whole "
            "table rather than a single answer."
        ),
        "when_not_to_use": (
            "Do not perform the lookup yourself. Appendix 2 in particular has "
            "sub-tables for unknown acclimatisation and augmented crew that this "
            "endpoint does not return, and its band, early-start and WOCL "
            "determinations are keyed to acclimatised time rather than the "
            "departure point. Call POST /calculate/max-fdp."
        ),
        "path_parameters": [_APPENDIX_PATH_PARAM],
        "response_model": FdpTableResponse,
        "common_mistakes": [
            "Treating the Appendix 2 response as the whole picture — it is the "
            "acclimatised table only.",
            "Reading the time bands against the departure point's clock. Under "
            "Appendix 2 they are read against acclimatised time (§6).",
        ],
    },
    {
        "path": "/limits/cumulative/{appendix}",
        "method": "GET",
        "group": "Limits",
        "summary": "Cumulative limit thresholds for an appendix",
        "purpose": (
            "Returns the rolling-window flight time, duty time and recovery "
            "thresholds an operator must track."
        ),
        "when_to_use": "To display thresholds, or to build a tracking dashboard.",
        "when_not_to_use": (
            "This returns thresholds only. To check a crew member against them, "
            "call POST /validate/cumulative with their history."
        ),
        "path_parameters": [_APPENDIX_PATH_PARAM],
        "response_model": CumulativeLimitsResponse,
        "common_mistakes": [
            "Assuming every appendix has every window — many fields are null.",
        ],
    },
    {
        "path": "/limits/adaptation-table",
        "method": "GET",
        "group": "Limits",
        "summary": "Table 7.1 — adaptation period to become acclimatised",
        "purpose": (
            "Returns Table 7.1 as data: the continuous off-duty period required "
            "to become acclimatised to a new location, by time zone change and "
            "direction of travel."
        ),
        "when_to_use": (
            "To render Table 7.1 as a reference page. Static data — safe to "
            "cache or prerender."
        ),
        "when_not_to_use": (
            "Do not apply the table yourself. Selecting the row requires the "
            "GREATEST displacement across every later location (§7.5(b)), not "
            "the current one, and the period may be reduced by 12 hours per "
            "qualifying preceding off-duty period (§7.4(b)). Call POST "
            "/calculate/acclimatisation."
        ),
        "response_model": AdaptationTableResponse,
        "common_mistakes": [
            "Selecting the row from the current location's displacement rather "
            "than the greatest displacement since last acclimatised.",
            "Using the westward column for eastward travel — eastward "
            "adaptation periods are materially longer.",
        ],
    },
    {
        "path": "/calculate/max-fdp",
        "method": "POST",
        "group": "Calculation",
        "summary": "Calculate the maximum permissible FDP",
        "purpose": (
            "Given the appendix, start instant, sector count and crew "
            "configuration, returns the maximum permissible FDP with a "
            "clause-referenced breakdown of every adjustment applied."
        ),
        "when_to_use": (
            "When planning, before an FDP starts, to establish the legal limit. "
            "Pair it with POST /validate/fdp once the actual times are known."
        ),
        "when_not_to_use": (
            "It returns a limit, not a pass or fail. Use /validate/fdp for that."
        ),
        "request_model": MaxFdpRequest,
        "response_model": MaxFdpResponse,
        "common_mistakes": [
            "Supplying only local_time_offset_hours for an Appendix 2 crew "
            "member who is acclimatised somewhere other than the departure "
            "point. Under Appendix 2 the table band, the early-start test and "
            "the WOCL determination are all defined against local time at the "
            "location the FCM is acclimatised to (§6). Supply "
            "acclimatisation.acclimatised_time_offset_hours as well — a "
            "Perth-acclimatised crew member signing on in Singapore is the "
            "everyday case, and getting it wrong moves the limit by hours.",
            "Putting the preceding off-duty duration inside the acclimatisation "
            "object. The field is the TOP-LEVEL preceding_off_duty_hours. It "
            "selects the <30h or >=30h row of Table 3.1 for unknown-state crew, "
            "and the difference between those rows is two hours of FDP.",
            "Omitting acclimatisation.state on an Appendix 2 augmented-crew "
            "request. Tables 5.1 and 5.2 are selected by acclimatisation state, "
            "so the request is rejected with a 422 rather than guessed at.",
            "Reading the adjustments[] entries with the wrong keys. Each entry "
            "is exactly clause, description, adjustment_hours and "
            "running_total_hours — see response_fields below.",
            "Assuming a split-duty rest that touches 2300-0529 gets the ordinary "
            "4-hour treatment. Once the rest includes any part of that window "
            "the stricter regime governs: 7 continuous hours with sleeping "
            "accommodation, or no extension at all.",
        ],
    },
    {
        "path": "/calculate/acclimatisation",
        "method": "POST",
        "group": "Calculation",
        "summary": "Determine an FCM's state of acclimatisation",
        "purpose": (
            "Determines a crew member's state of acclimatisation at a nominated "
            "moment under §7, from where they were last acclimatised and every "
            "FDP or off-duty period commenced since. Returns the state, the "
            "location they are acclimatised TO, and the clause that produced the "
            "determination."
        ),
        "when_to_use": (
            "Before calling /calculate/max-fdp or /validate/fdp for an "
            "Appendix 2 crew member, instead of asking them to self-declare. "
            "Feed the returned acclimatised_to.utc_offset_hours straight into "
            "acclimatisation.acclimatised_time_offset_hours on those endpoints. "
            "It also answers 'when do I become acclimatised?' via "
            "adaptation.acclimatised_at_utc, which is the question crew actually "
            "ask."
        ),
        "when_not_to_use": (
            "It determines state; it does not calculate an FDP limit. Chain it "
            "into /calculate/max-fdp for that."
        ),
        "request_model": AcclimatisationRequest,
        "response_model": AcclimatisationResponse,
        "common_mistakes": [
            "Treating 'indeterminate' as a conservative synonym for 'unknown'. "
            "They are different things: §7.3 'unknown' is a DETERMINATION with "
            "its own FDP tables (3.1 and 5.2), whereas 'indeterminate' means the "
            "supplied history was not sufficient to reach any determination. "
            "Never feed 'indeterminate' into a table lookup.",
            "Starting the 36-hour clock from arrival at the new location. §7.2 "
            "and §7.3 run it from when the FCM commenced a DUTY PERIOD at the "
            "original location — that is what duty_commenced_utc is for.",
            "Supplying only the current location in events[]. The §7.5 selection "
            "needs every later location, because the row is chosen from the "
            "greatest displacement, which is often not the most recent.",
            "Omitting home_base and then expecting the §7.4(b) reduction. It "
            "applies only to adaptation periods taken away from home base.",
            "Sending events out of chronological order. §7.4(b) counts "
            "immediately preceding off-duty periods, so order changes the "
            "answer; out-of-order lists are rejected rather than silently sorted.",
        ],
    },
    {
        "path": "/calculate/min-off-duty",
        "method": "POST",
        "group": "Calculation",
        "summary": "Calculate the minimum required off-duty period",
        "purpose": (
            "Given the preceding FDP and its context, returns the minimum "
            "required off-duty period with clause references and an assessment "
            "of whether any reduction provision is available."
        ),
        "when_to_use": (
            "When building a roster, to work out the earliest legal next sign-on."
        ),
        "when_not_to_use": (
            "To check an off-duty period that has already been rostered, use "
            "POST /validate/off-duty."
        ),
        "request_model": MinOffDutyRequest,
        "response_model": MinOffDutyResponse,
        "common_mistakes": [
            "Leaving acclimatisation_state at its default under Appendix 2. "
            "§10.1(c) and §10.2(b) are SEPARATE branches for an unknown state, "
            "not modifiers on the acclimatised ones: the base is 14 hours rather "
            "than 10 or 12, the home base / away distinction does not apply, and "
            "the FULL displacement time is added rather than only the excess. "
            "Getting this wrong under-reports a minimum rest period by up to "
            "four hours. Appendices 3 and 4 have no unknown-state branch.",
            "Omitting the two displacement offsets. Displacement time is an "
            "ADDEND in §10.1, §10.2, §8.1, §8.2 and Appendix 4B §5.1, not an "
            "optional extra. Supply "
            "preceding_fdp.commencement_utc_offset_hours and "
            "following_off_duty_utc_offset_hours and the API derives the "
            "magnitude and the direction; without them the answer is a floor "
            "rather than a total, and calculation_notes says so.",
            "Sending a flat parameter set. The preceding FDP details go inside "
            "the nested preceding_fdp object.",
            "Omitting post_fdp_duty_hours. Post-flight duties count towards the "
            "12-hour threshold that changes which rule applies.",
            "Reading reduction_applicable.eligible as permission. It reports "
            "that the conditions for a reduction are met; applying it remains an "
            "operator decision under the approved FMM. Note also that the 9-hour "
            "reduction is only available where FDP plus other duty does not "
            "exceed 10 hours, and that under Appendix 2 both reductions require "
            "an acclimatised state.",
        ],
    },
    {
        "path": "/validate/fdp",
        "method": "POST",
        "group": "Validation",
        "summary": "Validate a single FDP against its limits",
        "purpose": (
            "Checks an actual or planned FDP against the maximum FDP, the "
            "per-FDP flight time limit and any extension provisions, returning "
            "every violation with a clause reference and a remediation note."
        ),
        "when_to_use": "For a pass or fail on one FDP whose times are known.",
        "when_not_to_use": (
            "It sees one FDP only. Rules that span duties — consecutive early "
            "starts, consecutive WOCL infringements, the four-consecutive-"
            "unknown-state limit — need /validate/sequence or /validate/roster."
        ),
        "request_model": ValidateFdpRequest,
        "response_model": ValidationResponse,
        "common_mistakes": [
            "Leaving consecutive_early_starts and consecutive_wocl_infringements "
            "at zero when they are not. This endpoint cannot see prior duties, "
            "so it trusts what you send.",
            "Omitting acclimatisation.acclimatised_time_offset_hours under "
            "Appendix 2 when the FCM signs on away from the location they are "
            "acclimatised to — see /calculate/max-fdp.",
        ],
    },
    {
        "path": "/validate/off-duty",
        "method": "POST",
        "group": "Validation",
        "summary": "Validate an off-duty period",
        "purpose": (
            "Checks an actual off-duty period against the minimum required, "
            "including whether a claimed reduction is properly supported."
        ),
        "when_to_use": (
            "After a duty, or when checking a rostered rest period. Set "
            "reduction_claimed when relying on a reduction so the eligibility "
            "conditions are actually tested."
        ),
        "when_not_to_use": (
            "To find the required minimum rather than test an actual, call "
            "POST /calculate/min-off-duty."
        ),
        "request_model": ValidateOffDutyRequest,
        "response_model": ValidationResponse,
        "common_mistakes": [
            "Claiming a reduction without supplying preceding_off_duty — the "
            "eligibility conditions cannot be evaluated without it.",
        ],
    },
    {
        "path": "/validate/cumulative",
        "method": "POST",
        "group": "Validation",
        "summary": "Validate rolling-window cumulative limits",
        "purpose": (
            "Checks flight time, duty time and recovery requirements across "
            "every rolling window applicable to the appendix."
        ),
        "when_to_use": (
            "Before assigning a duty, to confirm it will not breach a 28-day, "
            "365-day or other rolling limit."
        ),
        "when_not_to_use": (
            "It does not check the duty itself — pair it with /validate/fdp."
        ),
        "request_model": ValidateCumulativeRequest,
        "response_model": ValidationResponse,
        "common_mistakes": [
            "Supplying too little history. Provide at least 365 days in fdp_log "
            "for full coverage; short logs silently under-report long windows.",
            "Omitting local_time_offset_hours on history records — local-night "
            "detection for recovery blocks is then skipped.",
            "Sending both fdp_log and summary and expecting summary to win. "
            "fdp_log is preferred; summary is a fallback.",
        ],
    },
    {
        "path": "/validate/sequence",
        "method": "POST",
        "group": "Validation",
        "summary": "Validate an ordered sequence of duties and rest",
        "purpose": (
            "Walks a chronological sequence of FDP and off-duty events, "
            "maintaining the state that single-duty endpoints cannot see: "
            "consecutive early starts, consecutive WOCL infringements, the "
            "Appendix 2 limit of four consecutive FDPs in an unknown state of "
            "acclimatisation, and the cumulative totals across the whole run."
        ),
        "when_to_use": (
            "For a pattern, a tour or a swing — anywhere the rules depend on "
            "what came before."
        ),
        "when_not_to_use": (
            "For a full roster with rest days and summary statistics, use "
            "POST /validate/roster."
        ),
        "request_model": ValidateSequenceRequest,
        "response_model": ValidationResponse,
        "common_mistakes": [
            "Sending events out of chronological order — the state machine "
            "depends on the order.",
            "Leaving acclimatisation_state at its default on Appendix 2 events. "
            "The four-consecutive-unknown-state rule (Appendix 2 §3.4) can only "
            "be checked if each FDP declares its state.",
            "Omitting off-duty events between FDPs. Rest periods are what reset "
            "the early-start and WOCL streaks.",
        ],
    },
    {
        "path": "/validate/roster",
        "method": "POST",
        "group": "Validation",
        "summary": "Validate a full roster",
        "purpose": (
            "The most complete check available: every FDP, every off-duty "
            "period, sequence-level state, cumulative windows and days off, "
            "returned per-item and in summary."
        ),
        "when_to_use": (
            "For a published or draft roster period. This is the endpoint to "
            "reach for when the question is 'is this roster legal?'."
        ),
        "when_not_to_use": (
            "It is the heaviest call in the API. For a single duty, "
            "/validate/fdp is far cheaper."
        ),
        "request_model": ValidateRosterRequest,
        "response_model": RosterValidationResponse,
        "common_mistakes": [
            "Omitting rest day events — days-off requirements cannot be checked "
            "without them.",
            "Supplying only the roster period itself when a cumulative window "
            "extends further back. Include enough prior history.",
            "Reading only the summary and missing per-item violations.",
        ],
    },
    {
        "path": "/guide",
        "method": "GET",
        "group": "Guide",
        "summary": "This document",
        "purpose": (
            "Structured documentation for every endpoint, intended to orient an "
            "LLM or integration at the start of a session."
        ),
        "when_to_use": "Once per session, before making compliance calls.",
        "when_not_to_use": (
            "Not per-request — the content is stable and may be cached for the "
            "session."
        ),
        "common_mistakes": [
            "Caching it across API version changes — check the version field "
            "against /health.",
        ],
    },
]


# ═══════════════════════════════════════════════════════════════════════
# Assembly
# ═══════════════════════════════════════════════════════════════════════

def _build_endpoints() -> list[dict]:
    """
    Merge the editorial narrative with model-generated documentation.

    Narrative keys are copied verbatim; parameters, response fields and
    examples come from the models via guide_builder.
    """
    endpoints: list[dict] = []

    for narrative in ENDPOINT_NARRATIVES:
        entry = {
            key: value
            for key, value in narrative.items()
            if key not in ("request_model", "response_model", "path_parameters")
        }
        entry.update(
            describe_endpoint(
                request_model=narrative.get("request_model"),
                response_model=narrative.get("response_model"),
                path_parameters=narrative.get("path_parameters"),
            )
        )
        endpoints.append(entry)

    return endpoints


GUIDE: dict = {
    "title": "CAO 48.1 Compliance API — Integration Guide",
    "version": "dynamic",  # replaced at runtime with settings.app_version
    "api_base_path": "/api/v1/cao481",
    "description": (
        "Call GET /guide once at the start of a session. This guide covers every "
        "endpoint's purpose, when to use it versus alternatives, its full "
        "parameter and response shape, a worked example, and the mistakes "
        "integrators actually make.\n\n"
        "Parameter and response documentation is generated from the API's own "
        "request and response models at import time, so it cannot drift from "
        "what the API accepts and returns."
    ),
    "important_notes": [
        "All timestamps are UTC ISO 8601 strings, e.g. '2026-03-24T22:00:00Z'.",
        "FDP time-band lookups use LOCAL time, not UTC. Supply "
        "local_time_offset_hours as hours ahead of UTC (AEST = 10.0, ACST = 9.5, "
        "IST = 5.5) so the API can convert the UTC instant to a local time of day.",
        "Under APPENDIX 2 ONLY, the FDP table band, the early-start test and the "
        "WOCL determination are defined against 'acclimatised time' — local time "
        "at the location the FCM is acclimatised to, or where the state is "
        "unknown, the location they were last acclimatised to (§6). Supply that "
        "clock as acclimatisation.acclimatised_time_offset_hours. It defaults to "
        "local_time_offset_hours, which is correct only when the FCM signs on at "
        "the location they are acclimatised to. Every other appendix uses local "
        "time at the point the FDP commences, and this field is ignored.",
        "Acclimatisation state is one of 'acclimatised', 'unknown' or "
        "'not_applicable'. There is no three-day rule and no 'not_acclimatised' "
        "value — the test is §7.1 to §7.3: a 2-hour local time difference and a "
        "36-hour threshold running from commencement of duty at the original "
        "location. POST /calculate/acclimatisation determines it for you.",
        "The API is stateless — there is no session memory. Cumulative and "
        "sequence checks need the relevant history supplied on every call.",
        "Unknown fields are REJECTED with a 422 naming the offending key. On a "
        "fatigue calculator, silently dropping an input is more dangerous than "
        "refusing the request.",
        "Validation responses always include a top-level 'valid' boolean and a "
        "'violations' list. Each violation carries a CAO 48.1 clause reference "
        "and a remediation suggestion.",
        "The /validate/* endpoints do not replace the /calculate/* endpoints. "
        "For a full check, call /calculate/max-fdp for the limit, then "
        "/validate/fdp on the actual times.",
        "This API validates against CAO 48.1 Instrument 2019 (Compilation No. 3, "
        "F2021C01239). Always cross-check against the in-force legislation and "
        "your operator's approved Fatigue Management Manual.",
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
            "operations": (
                "Multi-pilot operations on complex aircraft, e.g. airliners "
                "requiring a type rating"
            ),
            "has_wocl_rules": True,
            "has_augmented_crew": True,
            "note": (
                "The only appendix with acclimatisation sub-tables. Table 2.1 "
                "covers acclimatised crew, Table 3.1 unknown-state crew (indexed "
                "by preceding off-duty duration rather than time of day), and "
                "Tables 5.1 and 5.2 augmented operations. Uniquely, its time "
                "bands, early-start test and WOCL determination are read against "
                "acclimatised time rather than the departure point's clock."
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
            "task": "Work out whether a crew member is acclimatised, and to where",
            "endpoint": "POST /calculate/acclimatisation",
        },
        {
            "task": "Find the maximum permissible FDP before it starts (planning)",
            "endpoint": "POST /calculate/max-fdp",
        },
        {
            "task": "Find the minimum off-duty period after a duty",
            "endpoint": "POST /calculate/min-off-duty",
        },
        {
            "task": "Validate a single completed FDP",
            "endpoint": "POST /validate/fdp",
        },
        {
            "task": "Validate an off-duty period, including a claimed reduction",
            "endpoint": "POST /validate/off-duty",
        },
        {
            "task": "Validate a pattern, tour or swing where prior duties matter",
            "endpoint": "POST /validate/sequence",
        },
        {
            "task": "Validate a full roster period",
            "endpoint": "POST /validate/roster",
        },
        {
            "task": "Check rolling-window flight time, duty time and recovery",
            "endpoint": "POST /validate/cumulative",
        },
        {
            "task": "Render the FDP table for an appendix",
            "endpoint": "GET /limits/fdp-table/{appendix}",
        },
        {
            "task": "Render the cumulative thresholds for an appendix",
            "endpoint": "GET /limits/cumulative/{appendix}",
        },
        {
            "task": "Render Table 7.1, the adaptation periods",
            "endpoint": "GET /limits/adaptation-table",
        },
        {
            "task": "Read the legislative text behind a result",
            "endpoint": "GET /sections/{section_id}",
        },
    ],
    "endpoints": _build_endpoints(),
}

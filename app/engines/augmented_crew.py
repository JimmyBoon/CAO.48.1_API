"""
Appendix 2 clause 5 — augmented crew operations.

§5.1 and §5.2 permit the Table 5.1 / Table 5.2 limits "**but only if** the
conditions in subclause 5.3 are met". §5.3 is therefore a gate on the table,
not advisory commentary alongside it. Before this module existed the tables
were applied unconditionally and every §5.3 condition went unevaluated,
including the ones the caller had already supplied the data to fail.

The conditions split three ways:

* **Sector limits** (§5.3(c), (f)(i), (g)(i)) — checkable from `sectors` and
  the FDP duration alone. These drive the FDP ceiling *down*; they are applied
  before a maximum is returned, not reported afterwards.
* **In-flight rest minima** (§5.3(d), (f)(ii), (g)(ii)) — checkable when the
  caller supplies `in_flight_rest_hours_per_fcm`, and reported as
  `data_unavailable` when they do not. Never assumed satisfied.
* **Facts outside this API** (§5.3(a) operations manual procedures, §5.3(b)
  same FCMs at start and end, §5.3(e) rest planned for the cruise phase) —
  surfaced as conditions the caller must verify, never as satisfied ones.

On flight time, see `augmented_flight_time_note()`.

Verified against the text served by GET /sections/APPENDIX 2.5.
"""

from __future__ import annotations

from typing import Any, Optional

# §5.3(c): the FDP must be limited to not more than 3 sectors.
MAX_SECTORS = 3

# §5.3(f)(i): an FDP exceeding 14 hours permits not more than 2 sectors.
# §5.3(g)(i): an FDP exceeding 16 hours permits only 1 sector.
# Read as a ceiling on the FDP for a given sector count, these give:
SECTOR_FDP_CEILINGS: dict[int, tuple[Optional[float], str]] = {
    1: (None, "§5.3(c)"),        # no sector-derived ceiling; the table governs
    2: (16.0, "§5.3(g)(i)"),     # >16h would require only 1 sector
    3: (14.0, "§5.3(f)(i)"),     # >14h would require not more than 2 sectors
}

# §5.3(d) — the baseline minima, and §5.3(g)(ii) — the minima above 16 hours.
# Keyed by (fdp_exceeds_16h, at_controls_final_landing).
REST_MINIMA: dict[tuple[bool, bool], tuple[float, str]] = {
    (False, False): (1.5, "§5.3(d)(i)"),
    (False, True): (2.0, "§5.3(d)(ii)"),
    (True, False): (2.0, "§5.3(g)(ii)(A)"),
    (True, True): (3.0, "§5.3(g)(ii)(B)"),
}

# Conditions this API cannot check against any supplied data.
CALLER_MUST_VERIFY: tuple[tuple[str, str], ...] = (
    ("§5.3(a)", "The AOC holder's operations manual has procedures for "
                "augmented crew operations"),
    ("§5.3(b)", "The FCMs at the end of the FDP are the same as those who "
                "commenced the first sector"),
    ("§5.3(e)", "The in-flight rest is planned for the cruise phase of the flight"),
)


def augmented_flight_time_note() -> str:
    """
    Why `flight_time_limit_hours` is null on the augmented path.

    Clause 5 is titled "Increase in FDP *and flight time* limits in an
    augmented crew operation", and the Note under Table 5.2 calls the tables
    "the maximum FDP and flight time limits under this Appendix", which reads
    as though the tables cap both. They do not. The operative rule is §2.2:

        "An acclimatised FCM must not be assigned flight time longer than
         10.5 hours **except in an augmented crew operation**."

    followed by its own Note: "There is no flight time limit for an augmented
    crew operation." A null flight time limit here is correct, not an omission.
    """
    return (
        "No flight time limit applies to an augmented crew operation "
        "(Appendix 2 §2.2 and its Note). The 10.5h limit applies only outside "
        "augmented crew operations."
    )


def _get(entry: Any, field: str, default=None):
    """Read a field from either a Pydantic model or a plain dict."""
    if isinstance(entry, dict):
        return entry.get(field, default)
    return getattr(entry, field, default)


def sector_ceiling(sectors: int) -> tuple[Optional[float], str]:
    """
    The FDP ceiling imposed by the sector count, with the clause imposing it.

    Returns (None, clause) where the sector count imposes no ceiling of its
    own and the table value governs.
    """
    return SECTOR_FDP_CEILINGS.get(sectors, (None, "§5.3(c)"))


def required_rest_hours(
    fdp_hours: float, at_controls_final_landing: bool,
) -> tuple[float, str]:
    """Minimum consecutive in-flight rest for one FCM, with its clause."""
    return REST_MINIMA[(fdp_hours > 16.0, bool(at_controls_final_landing))]


def check_sector_limit(sectors: int) -> Optional[dict]:
    """§5.3(c): not more than 3 sectors, unconditionally, for all augmented ops."""
    if sectors <= MAX_SECTORS:
        return None
    return {
        "check": "augmented_sector_limit",
        "clause": "§5.3(c)",
        "severity": "hard_limit",
        "actual": float(sectors),
        "limit": float(MAX_SECTORS),
        "detail": (
            f"{sectors} sectors assigned. §5.3(c) requires an augmented crew "
            f"FDP to be limited to not more than {MAX_SECTORS} sectors. The "
            f"Table 5.1 / 5.2 limits are available only if the §5.3 conditions "
            f"are met, so no augmented FDP limit applies to this assignment."
        ),
        "remediation": (
            f"Reduce the FDP to not more than {MAX_SECTORS} sectors, or plan "
            f"the operation without an augmented crew."
        ),
    }


def evaluate_conditions(
    augmented_crew: Any,
    sectors: int,
    fdp_hours: float,
) -> dict:
    """
    Evaluate the §5.3 conditions against an assigned augmented-crew FDP.

    Returns checks, violations and the conditions the caller must verify.
    A check the API could not evaluate carries status "data_unavailable" and
    `passed: None` — it is neither a pass nor a fail, and must not count
    toward a compliant verdict.
    """
    checks: list[dict] = []
    violations: list[dict] = []

    def add(check_id, passed, clause, actual, limit, detail, remediation="",
            status=None):
        checks.append({
            "check": check_id,
            "passed": passed,
            "status": status or ("passed" if passed else "failed"),
            "clause": clause,
            "actual": actual,
            "limit": limit,
            "detail": detail,
        })
        if passed is False:
            violations.append({
                "check": check_id,
                "clause": clause,
                "severity": "hard_limit",
                "actual": actual,
                "limit": limit,
                "detail": detail,
                "remediation": remediation,
            })

    # ─── §5.3(c) — sector limit ───────────────────────────────────────
    sector_violation = check_sector_limit(sectors)
    if sector_violation is not None:
        violations.append(sector_violation)
        checks.append({
            "check": sector_violation["check"],
            "passed": False,
            "status": "failed",
            "clause": sector_violation["clause"],
            "actual": sector_violation["actual"],
            "limit": sector_violation["limit"],
            "detail": sector_violation["detail"],
        })
    else:
        add(
            "augmented_sector_limit", True, "§5.3(c)",
            float(sectors), float(MAX_SECTORS),
            f"{sectors} sectors is within the {MAX_SECTORS}-sector limit for an "
            f"augmented crew operation.",
        )

    # ─── §5.3(f)(i) and §5.3(g)(i) — sectors permitted at this duration ──
    # §5.3 introduces a list: "the conditions are as follows". They are
    # cumulative, not alternatives. An 18-hour, 3-sector FDP breaches
    # §5.3(f)(i) (over 14h, so not more than 2 sectors) AND §5.3(g)(i) (over
    # 16h, so only 1 sector). Treating (g) as superseding (f) would report one
    # breach where two exist and would hide the shorter FDP the operator could
    # actually have flown.
    if fdp_hours > 14.0:
        add(
            "augmented_sectors_over_14h", sectors <= 2, "§5.3(f)(i)",
            float(sectors), 2.0,
            (
                f"FDP of {fdp_hours:.2f}h exceeds 14 hours; §5.3(f)(i) permits "
                f"not more than 2 sectors and {sectors} "
                f"{'were' if sectors != 1 else 'was'} assigned."
                if sectors > 2 else
                f"FDP of {fdp_hours:.2f}h exceeds 14 hours; {sectors} sectors "
                f"is within the 2 that §5.3(f)(i) permits."
            ),
            "Reduce to not more than 2 sectors, or reduce the FDP to 14 hours "
            "or less.",
        )

    if fdp_hours > 16.0:
        add(
            "augmented_sectors_over_16h", sectors <= 1, "§5.3(g)(i)",
            float(sectors), 1.0,
            (
                f"FDP of {fdp_hours:.2f}h exceeds 16 hours; §5.3(g)(i) permits "
                f"only 1 sector and {sectors} were assigned."
                if sectors > 1 else
                f"FDP of {fdp_hours:.2f}h exceeds 16 hours; 1 sector is what "
                f"§5.3(g)(i) permits."
            ),
            "Reduce to 1 sector, or reduce the FDP to 16 hours or less.",
        )

    if fdp_hours <= 14.0:
        ceiling, clause = sector_ceiling(sectors)
        add(
            "augmented_sectors_for_duration", True,
            clause if ceiling is not None else "§5.3(c)",
            fdp_hours, ceiling,
            (
                f"FDP of {fdp_hours:.2f}h does not exceed 14 hours, so neither "
                f"§5.3(f)(i) nor §5.3(g)(i) restricts the {sectors} sectors "
                f"assigned."
            ),
        )

    # ─── §5.3(d) and §5.3(g)(ii) — minimum in-flight rest ─────────────
    rest_entries = _get(augmented_crew, "in_flight_rest_hours_per_fcm")

    if not rest_entries:
        clauses = ["§5.3(d)"]
        if fdp_hours > 16.0:
            clauses.append("§5.3(g)(ii)")
        clause_not_at, clause_at = clauses[0], clauses[-1]
        checks.append({
            "check": "augmented_in_flight_rest",
            "passed": None,
            "status": "data_unavailable",
            "clause": " / ".join(dict.fromkeys(clauses)),
            "actual": None,
            "limit": None,
            "detail": (
                "In-flight rest could not be checked: "
                "augmented_crew.in_flight_rest_hours_per_fcm was not supplied. "
                "This condition gates the Table 5.1 / 5.2 limits and has NOT "
                "been verified — it is not a pass."
            ),
        })
    else:
        for entry in rest_entries:
            fcm_id = _get(entry, "fcm_id", "?")
            rest_hours = _get(entry, "rest_hours", 0.0) or 0.0
            at_controls = bool(_get(entry, "at_controls_final_landing", False))
            role = (
                "at the controls during the final landing" if at_controls
                else "not at the controls during the final landing"
            )

            # §5.3(d) is stated unconditionally and applies to every augmented
            # FDP. §5.3(g)(ii) adds a stricter minimum above 16 hours; it does
            # not replace (d). A 1-hour rest on an 18-hour FDP breaches both.
            tiers = [REST_MINIMA[(False, at_controls)]]
            if fdp_hours > 16.0:
                tiers.append(REST_MINIMA[(True, at_controls)])

            for required, clause in tiers:
                suffix = "" if clause.startswith("§5.3(d)") else "[over-16h]"
                add(
                    f"augmented_in_flight_rest{suffix}[{fcm_id}]",
                    rest_hours >= required,
                    clause,
                    rest_hours,
                    required,
                    (
                        f"FCM {fcm_id} ({role}) had {rest_hours}h consecutive "
                        f"in-flight rest; {clause} requires {required}h"
                        + (" on an FDP exceeding 16 hours"
                           if clause.startswith("§5.3(g)") else "")
                        + "."
                    ),
                    (
                        f"Provide at least {required} consecutive hours of "
                        f"in-flight rest for FCM {fcm_id}, or reduce the FDP."
                    ),
                )

    # ─── §5.3(f)(ii) — 2 sectors on an FDP exceeding 14 hours ─────────
    if sectors == 2 and fdp_hours > 14.0:
        second_sector = _get(
            augmented_crew, "second_sector_scheduled_flight_time_hours",
        )
        landing_crew = [
            entry for entry in (rest_entries or [])
            if _get(entry, "at_controls_final_landing", False)
        ]
        timing_known = landing_crew and all(
            _get(entry, "rest_within_8h_before_landing") is not None
            for entry in landing_crew
        )

        limb_b = second_sector is not None and second_sector >= 9.0
        limb_a = bool(landing_crew) and all(
            (_get(entry, "rest_hours", 0.0) or 0.0) >= 2.0
            and _get(entry, "rest_within_8h_before_landing") is True
            for entry in landing_crew
        )

        if limb_b or limb_a:
            satisfied_by = "§5.3(f)(ii)(B)" if limb_b else "§5.3(f)(ii)(A)"
            add(
                "augmented_two_sector_over_14h", True, satisfied_by, None, None,
                (
                    f"§5.3(f)(ii) satisfied by {satisfied_by}: "
                    + (
                        f"second sector scheduled flight time {second_sector}h "
                        f"is at least 9 hours."
                        if limb_b else
                        "each FCM at the controls for the second-sector landing "
                        "had at least 2 consecutive hours of in-flight rest "
                        "within the 8 hours ending at the scheduled landing."
                    )
                ),
            )
        elif second_sector is None and not timing_known:
            checks.append({
                "check": "augmented_two_sector_over_14h",
                "passed": None,
                "status": "data_unavailable",
                "clause": "§5.3(f)(ii)",
                "actual": None,
                "limit": None,
                "detail": (
                    "§5.3(f)(ii) could not be checked on this 2-sector FDP "
                    "exceeding 14 hours. Supply "
                    "augmented_crew.second_sector_scheduled_flight_time_hours "
                    "for limb (B), or rest_within_8h_before_landing on each "
                    "landing-controls FCM for limb (A). Not verified — not a pass."
                ),
            })
        else:
            add(
                "augmented_two_sector_over_14h", False, "§5.3(f)(ii)", None, None,
                (
                    f"§5.3(f)(ii) is not satisfied on this 2-sector FDP of "
                    f"{fdp_hours:.2f}h. Limb (A) requires each FCM at the "
                    f"controls for the second-sector landing to have had at "
                    f"least 2 consecutive hours of in-flight rest within the 8 "
                    f"hours ending at the scheduled landing; limb (B) requires "
                    f"the second sector's scheduled flight time to be at least "
                    f"9 hours"
                    + (f" (supplied: {second_sector}h)" if second_sector is not None else "")
                    + "."
                ),
                (
                    "Schedule the second sector for at least 9 hours of flight "
                    "time, or place 2 consecutive hours of in-flight rest within "
                    "the 8 hours before the scheduled landing for each "
                    "landing-controls FCM."
                ),
            )

    return {
        "checks": checks,
        "violations": violations,
        "conditions_caller_must_verify": [
            {"clause": clause, "description": description}
            for clause, description in CALLER_MUST_VERIFY
        ],
    }

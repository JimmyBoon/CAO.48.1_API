"""
Regression tests for the roster/sequence off-duty defects reported by
Aviation Toolbox, 30 July 2026, plus six found while investigating.

The reported item:
  1. /validate/roster dropped the split-duty §4.2 credit when computing the
     minimum off-duty period, over-reporting the required rest and so failing a
     compliant roster.

Found while verifying — the roster ODP call was passing only the FDP duration,
the extension and the location, so five further inputs were being dropped:
  2. post-FDP duty (from actual_duty_time_hours) — UNDER-reported
  3. acclimatisation state, so the §10.1(c) 14h unknown-state base never fired
     on a roster — UNDER-reported by up to 4 hours
  4. the preceding ODP's duration and local night, so the §10.3/§8.3 9-hour
     reduction could never be evaluated
  5. displacement time — no offsets existed on the event models
  6. odp_results carried no calculation_notes, so none of the working was
     auditable
  7. /validate/sequence could not express a split duty at all — SequenceFdpEvent
     had no such field and, with extra="forbid", returned a 422

The governing principle for all of these: the three endpoints must agree about
the same duty. Each test that can be expressed as a parity assertion is.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

PREFIX = "/api/v1/cao481"
pytestmark = pytest.mark.anyio


@pytest.fixture
def transport():
    return ASGITransport(app=app)


# ─── Shared fixtures: the brief's roster ──────────────────────────────
# Appendix 2, UTC+8. A 13-hour FDP with a 4-hour sleeping split-duty break,
# then a 12-hour off-duty period at home base.

_SPLIT_DUTY = {
    "rest_start_utc": "2026-07-30T02:00:00Z",
    "rest_end_utc": "2026-07-30T06:00:00Z",
    "accommodation": "sleeping",
    "duration_hours": 4,
    "overlaps_2300_0529": False,
}

_FDP_13H = {
    "event_type": "fdp",
    "fdp_start_utc": "2026-07-29T20:00:00Z",   # 0400 local
    "fdp_end_utc": "2026-07-30T09:00:00Z",     # 1700 local, 13h
    "local_time_offset_hours": 8,
    "sectors": 2,
    "actual_duty_time_hours": 13,
    "actual_flight_time_hours": 4,
}

_ODP_12H = {
    "event_type": "off_duty",
    "start_utc": "2026-07-30T09:00:00Z",
    "end_utc": "2026-07-30T21:00:00Z",
    "duration_hours": 12,
    "location": "home_base",
}


async def _roster(transport, events, appendix="2"):
    payload = {
        "appendix": appendix,
        "roster_start_utc": "2026-07-29T00:00:00Z",
        "roster_end_utc": "2026-07-31T00:00:00Z",
        "events": events,
    }
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"{PREFIX}/validate/roster", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _sequence(transport, events, appendix="2"):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            f"{PREFIX}/validate/sequence",
            json={"appendix": appendix, "events": events},
        )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _min_off_duty(transport, payload):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"{PREFIX}/calculate/min-off-duty", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _odp_check(roster_body, index=0):
    """The odp_meets_minimum check for one ODP in a roster response."""
    item = roster_body["odp_results"][index]
    return next(c for c in item["checks"] if c["check"] == "odp_meets_minimum")


def _sequence_odp_check(sequence_body, number=1):
    return next(
        c for c in sequence_body["checks"]
        if c["check"] == f"odp{number}_odp_meets_minimum"
    )


# ═══════════════════════════════════════════════════════════════════════
# Defect 1 — the split-duty credit
# ═══════════════════════════════════════════════════════════════════════

class TestSplitDutyCredit:
    """
    The reported defect. A 4-hour sleeping break earns a 2-hour §4.2 credit,
    taking the effective duty from 13h to 11h — under the threshold, so §10.1(b)
    applies instead of §10.2(a), and the minimum is 12h rather than 13.5h.
    """

    async def test_roster_applies_the_credit(self, transport):
        body = await _roster(
            transport, [{**_FDP_13H, "split_duty": _SPLIT_DUTY}, _ODP_12H],
        )
        check = _odp_check(body)
        assert check["limit"] == 12.0
        assert check["clause"] == "§10.1b"

    async def test_roster_reports_the_compliant_roster_as_valid(self, transport):
        """
        The consequence of the defect: a compliant roster failed.

        12 hours of rest satisfies a 12-hour minimum, but the endpoint was
        demanding 13.5 and raising a hard_limit violation.
        """
        body = await _roster(
            transport, [{**_FDP_13H, "split_duty": _SPLIT_DUTY}, _ODP_12H],
        )
        assert body["odp_results"][0]["valid"] is True
        assert not [
            v for v in body["all_violations"] if v["check"].endswith("odp_meets_minimum")
        ]

    async def test_without_split_duty_the_higher_figure_still_applies(self, transport):
        """The fix must not simply lower everything — no split duty, no credit."""
        body = await _roster(transport, [_FDP_13H, _ODP_12H])
        check = _odp_check(body)
        assert check["limit"] == 13.5
        assert check["clause"] == "§10.2a"

    async def test_credit_appears_in_the_odp_notes(self, transport):
        body = await _roster(
            transport, [{**_FDP_13H, "split_duty": _SPLIT_DUTY}, _ODP_12H],
        )
        notes = " ".join(body["odp_results"][0]["calculation_notes"])
        assert "Split duty credit" in notes
        assert "§4.2" in notes

    async def test_roster_matches_calculate_min_off_duty(self, transport):
        """Parity — the whole point. Same duty, same answer, same clause."""
        roster = _odp_check(await _roster(
            transport, [{**_FDP_13H, "split_duty": _SPLIT_DUTY}, _ODP_12H],
        ))
        calc = await _min_off_duty(transport, {
            "appendix": "2",
            "preceding_fdp": {
                "start_utc": "2026-07-29T20:00:00Z",
                "end_utc": "2026-07-30T09:00:00Z",
                "duration_hours": 13,
                "location": "home_base",
                "split_duty": {
                    "duration_hours": 4,
                    "accommodation": "sleeping",
                    "overlaps_2300_0529": False,
                },
            },
        })
        assert roster["limit"] == calc["final_min_odp_hours"]
        assert roster["clause"] == calc["clause"]

    async def test_split_duty_still_extends_the_fdp(self, transport):
        """
        The FDP side was always correct and must stay so. The split duty is read
        for both purposes now, not one.
        """
        body = await _roster(
            transport, [{**_FDP_13H, "split_duty": _SPLIT_DUTY}, _ODP_12H],
        )
        notes = " ".join(body["fdp_results"][0]["calculation_notes"])
        assert "Split duty" in notes


# ═══════════════════════════════════════════════════════════════════════
# Defect 7 — /validate/sequence could not express a split duty
# ═══════════════════════════════════════════════════════════════════════

class TestSequenceEventModel:
    """
    The brief guessed /validate/sequence "almost certainly shares the bug". It
    did not — it was worse: SequenceFdpEvent had no split_duty field, so with
    extra="forbid" the request was rejected outright with a 422.
    """

    async def test_sequence_accepts_split_duty(self, transport):
        body = await _sequence(
            transport, [{**_FDP_13H, "split_duty": _SPLIT_DUTY}, _ODP_12H],
        )
        check = _sequence_odp_check(body)
        assert check["limit"] == 12.0
        assert check["clause"] == "§10.1b"

    async def test_sequence_matches_roster(self, transport):
        events = [{**_FDP_13H, "split_duty": _SPLIT_DUTY}, _ODP_12H]
        roster = _odp_check(await _roster(transport, events))
        sequence = _sequence_odp_check(await _sequence(transport, events))
        assert roster["limit"] == sequence["limit"]
        assert roster["clause"] == sequence["clause"]

    @pytest.mark.parametrize(
        "field,value",
        [
            ("single_pilot", False),
            ("extension", {"type": "unforeseen", "hours_used": 1.0}),
            (
                "augmented_crew",
                {"additional_fcms": 1, "rest_facility_class": "class_2"},
            ),
        ],
    )
    async def test_sequence_accepts_the_other_roster_fields(
        self, transport, field, value,
    ):
        """SequenceFdpEvent should express the same duty a RosterFdpEvent can."""
        event = {**_FDP_13H, field: value}
        if field == "augmented_crew":
            # Appendix 2 augmented crew requires an explicit state (§5 tables).
            event["acclimatisation_state"] = "acclimatised"
        await _sequence(transport, [event, _ODP_12H])

    async def test_both_event_models_carry_the_same_duty_fields(self):
        """Guards against the two drifting apart again."""
        from app.models.validation import RosterFdpEvent, SequenceFdpEvent

        shared = {
            "split_duty", "extension", "augmented_crew", "single_pilot",
            "commencement_utc_offset_hours",
        }
        assert shared <= set(SequenceFdpEvent.model_fields)
        assert shared <= set(RosterFdpEvent.model_fields)


# ═══════════════════════════════════════════════════════════════════════
# Defect 2 — post-FDP duty
# ═══════════════════════════════════════════════════════════════════════

class TestPostFdpDuty:
    """
    actual_duty_time_hours covers the FDP plus pre/post-flight duty. Anything
    beyond the FDP's wall-clock duration counts towards the 12-hour threshold.

    This one UNDER-reported, which is the dangerous direction — the opposite of
    the reported defect.
    """

    _FDP_10H_WITH_POST_DUTY = {
        "event_type": "fdp",
        "fdp_start_utc": "2026-07-29T22:00:00Z",
        "fdp_end_utc": "2026-07-30T08:00:00Z",   # 10h wall clock
        "local_time_offset_hours": 8,
        "sectors": 2,
        "actual_duty_time_hours": 12.5,           # 2.5h of post-FDP duty
        "actual_flight_time_hours": 8,
    }

    _ODP = {
        "event_type": "off_duty",
        "start_utc": "2026-07-30T08:00:00Z",
        "end_utc": "2026-07-30T20:00:00Z",
        "duration_hours": 12,
        "location": "home_base",
    }

    async def test_roster_counts_post_fdp_duty(self, transport):
        """12.5h total duty crosses the threshold: §10.2a, not §10.1b."""
        check = _odp_check(await _roster(
            transport, [self._FDP_10H_WITH_POST_DUTY, self._ODP],
        ))
        assert check["limit"] == 12.75    # 12 + 1.5 x 0.5
        assert check["clause"] == "§10.2a"

    async def test_sequence_counts_post_fdp_duty(self, transport):
        check = _sequence_odp_check(await _sequence(
            transport, [self._FDP_10H_WITH_POST_DUTY, self._ODP],
        ))
        assert check["limit"] == 12.75

    async def test_matches_calculate_min_off_duty(self, transport):
        roster = _odp_check(await _roster(
            transport, [self._FDP_10H_WITH_POST_DUTY, self._ODP],
        ))
        calc = await _min_off_duty(transport, {
            "appendix": "2",
            "preceding_fdp": {
                "start_utc": "2026-07-29T22:00:00Z",
                "end_utc": "2026-07-30T08:00:00Z",
                "duration_hours": 10,
                "post_fdp_duty_hours": 2.5,
                "location": "home_base",
            },
        })
        assert roster["limit"] == calc["final_min_odp_hours"]
        assert roster["clause"] == calc["clause"]

    async def test_no_post_duty_means_no_change(self, transport):
        """actual_duty_time_hours equal to the FDP duration adds nothing."""
        event = {**self._FDP_10H_WITH_POST_DUTY, "actual_duty_time_hours": 10}
        check = _odp_check(await _roster(transport, [event, self._ODP]))
        assert check["limit"] == 12.0
        assert check["clause"] == "§10.1b"

    async def test_duty_less_than_fdp_duration_is_not_negative(self, transport):
        """Defensive: a caller under-reporting duty must not create a credit."""
        event = {**self._FDP_10H_WITH_POST_DUTY, "actual_duty_time_hours": 8}
        check = _odp_check(await _roster(transport, [event, self._ODP]))
        assert check["limit"] == 12.0


# ═══════════════════════════════════════════════════════════════════════
# Defect 3 — acclimatisation state
# ═══════════════════════════════════════════════════════════════════════

class TestAcclimatisationState:
    """
    The §10.1(c) 14-hour unknown-state base was fixed in 0.6.0 on
    /calculate/min-off-duty, but the roster path never passed the state through,
    so the fix could not reach it. UNDER-reported by up to four hours.
    """

    _FDP = {
        "event_type": "fdp",
        "fdp_start_utc": "2026-07-29T22:00:00Z",
        "fdp_end_utc": "2026-07-30T08:00:00Z",
        "local_time_offset_hours": 8,
        "sectors": 2,
        "actual_duty_time_hours": 10,
        "actual_flight_time_hours": 8,
    }

    _ODP = {
        "event_type": "off_duty",
        "start_utc": "2026-07-30T08:00:00Z",
        "end_utc": "2026-07-30T20:00:00Z",
        "duration_hours": 12,
        "location": "home_base",
    }

    async def test_roster_unknown_state_uses_the_14h_base(self, transport):
        event = {**self._FDP, "acclimatisation": {"state": "unknown"}}
        check = _odp_check(await _roster(transport, [event, self._ODP]))
        assert check["limit"] == 14.0
        assert check["clause"] == "§10.1c"

    async def test_roster_acclimatised_state_unchanged(self, transport):
        event = {**self._FDP, "acclimatisation": {"state": "acclimatised"}}
        check = _odp_check(await _roster(transport, [event, self._ODP]))
        assert check["limit"] == 12.0
        assert check["clause"] == "§10.1b"

    async def test_sequence_unknown_state_uses_the_14h_base(self, transport):
        event = {**self._FDP, "acclimatisation_state": "unknown"}
        check = _sequence_odp_check(await _sequence(transport, [event, self._ODP]))
        assert check["limit"] == 14.0
        assert check["clause"] == "§10.1c"

    async def test_appendix_3_unaffected(self, transport):
        """Appendix 3 §8 has no unknown-state branch."""
        event = {**self._FDP, "acclimatisation": {"state": "unknown"}}
        check = _odp_check(await _roster(transport, [event, self._ODP], appendix="3"))
        assert check["limit"] == 12.0


# ═══════════════════════════════════════════════════════════════════════
# Defect 4 — the preceding ODP, for the 9-hour reduction
# ═══════════════════════════════════════════════════════════════════════

class TestPrecedingOdpForReduction:
    """
    §10.3(a) / §8.3(a) make the 9-hour reduction conditional on the off-duty
    period immediately BEFORE the last FDP being at least 12 hours and including
    a local night. Neither validator supplied that, so the reduction could never
    be evaluated in a roster.
    """

    def _short_fdp(self, start, end):
        return {
            "event_type": "fdp",
            "fdp_start_utc": start,
            "fdp_end_utc": end,
            "local_time_offset_hours": 8,
            "sectors": 2,
            "actual_duty_time_hours": 10,
            "actual_flight_time_hours": 7,
            "acclimatisation": {"state": "acclimatised"},
        }

    def _odp(self, start, end, hours, night=True, location="away"):
        return {
            "event_type": "off_duty",
            "start_utc": start,
            "end_utc": end,
            "duration_hours": hours,
            "includes_local_night": night,
            "location": location,
        }

    async def test_reduction_offered_when_the_preceding_odp_qualifies(self, transport):
        """
        A qualifying 12h+local-night rest, then a 10h duty, then a 9h rest away
        from home base. §10.3 permits 9 hours, so the 9h rest passes.
        """
        events = [
            self._odp("2026-07-28T10:00:00Z", "2026-07-28T22:00:00Z", 12, night=True),
            self._short_fdp("2026-07-28T22:00:00Z", "2026-07-29T08:00:00Z"),
            self._odp("2026-07-29T08:00:00Z", "2026-07-29T17:00:00Z", 9, night=True),
        ]
        body = await _roster(transport, events)
        check = _odp_check(body, index=1)
        assert check["limit"] == 9.0
        assert check["passed"] is True

    async def test_reduction_withheld_when_the_preceding_odp_is_short(self, transport):
        """An 11-hour preceding rest does not satisfy §10.3(a)."""
        events = [
            self._odp("2026-07-28T11:00:00Z", "2026-07-28T22:00:00Z", 11, night=True),
            self._short_fdp("2026-07-28T22:00:00Z", "2026-07-29T08:00:00Z"),
            self._odp("2026-07-29T08:00:00Z", "2026-07-29T17:00:00Z", 9, night=True),
        ]
        check = _odp_check(await _roster(transport, events), index=1)
        assert check["limit"] == 10.0
        assert check["passed"] is False

    async def test_reduction_withheld_when_the_preceding_odp_had_no_local_night(
        self, transport,
    ):
        events = [
            self._odp("2026-07-28T10:00:00Z", "2026-07-28T22:00:00Z", 12, night=False),
            self._short_fdp("2026-07-28T22:00:00Z", "2026-07-29T08:00:00Z"),
            self._odp("2026-07-29T08:00:00Z", "2026-07-29T17:00:00Z", 9, night=True),
        ]
        check = _odp_check(await _roster(transport, events), index=1)
        assert check["limit"] == 10.0


# ═══════════════════════════════════════════════════════════════════════
# Defect 5 — displacement time
# ═══════════════════════════════════════════════════════════════════════

class TestDisplacementOnRosterAndSequence:
    _FDP = {
        "event_type": "fdp",
        "fdp_start_utc": "2026-07-29T22:00:00Z",
        "fdp_end_utc": "2026-07-30T08:00:00Z",
        "local_time_offset_hours": 8,
        "sectors": 2,
        "actual_duty_time_hours": 10,
        "actual_flight_time_hours": 8,
        "acclimatisation": {"state": "acclimatised"},
        "commencement_utc_offset_hours": 8.0,
    }

    _ODP = {
        "event_type": "off_duty",
        "start_utc": "2026-07-30T08:00:00Z",
        "end_utc": "2026-07-30T20:00:00Z",
        "duration_hours": 12,
        "location": "away",
        "utc_offset_hours": 3.0,               # 5h west
    }

    async def test_roster_adds_the_displacement_excess(self, transport):
        """Acclimatised: 10h base + (5h - 3h west threshold) = 12h."""
        check = _odp_check(await _roster(transport, [self._FDP, self._ODP]))
        assert check["limit"] == 12.0

    async def test_sequence_adds_the_displacement_excess(self, transport):
        event = {**self._FDP}
        event.pop("acclimatisation")
        event["acclimatisation_state"] = "acclimatised"
        check = _sequence_odp_check(await _sequence(transport, [event, self._ODP]))
        assert check["limit"] == 12.0

    async def test_unknown_state_adds_the_full_displacement(self, transport):
        event = {**self._FDP, "acclimatisation": {"state": "unknown"}}
        check = _odp_check(await _roster(transport, [event, self._ODP]))
        assert check["limit"] == 19.0    # 14 + 5, in full

    async def test_omitting_the_offsets_notes_the_figure_is_a_floor(self, transport):
        event = {k: v for k, v in self._FDP.items()
                 if k != "commencement_utc_offset_hours"}
        odp = {k: v for k, v in self._ODP.items() if k != "utc_offset_hours"}
        body = await _roster(transport, [event, odp])
        notes = " ".join(body["odp_results"][0]["calculation_notes"])
        assert "NOT included" in notes


# ═══════════════════════════════════════════════════════════════════════
# Defect 6 — the location default and the audit trail
# ═══════════════════════════════════════════════════════════════════════

class TestLocationDefaultAndNotes:
    """
    'away' requires 10 hours and 'home_base' 12, so the old default of 'away'
    was a silent guess in the permissive direction. It now defaults to
    'home_base' — the longer requirement — and says so.
    """

    _FDP = {
        "event_type": "fdp",
        "fdp_start_utc": "2026-07-29T22:00:00Z",
        "fdp_end_utc": "2026-07-30T08:00:00Z",
        "local_time_offset_hours": 8,
        "sectors": 2,
        "actual_duty_time_hours": 10,
        "actual_flight_time_hours": 8,
        "acclimatisation": {"state": "acclimatised"},
    }

    _ODP_NO_LOCATION = {
        "event_type": "off_duty",
        "start_utc": "2026-07-30T08:00:00Z",
        "end_utc": "2026-07-30T20:00:00Z",
        "duration_hours": 12,
    }

    async def test_default_is_the_conservative_one(self, transport):
        check = _odp_check(await _roster(
            transport, [self._FDP, self._ODP_NO_LOCATION],
        ))
        assert check["limit"] == 12.0
        assert check["clause"] == "§10.1b"

    async def test_default_is_disclosed_in_the_notes(self, transport):
        body = await _roster(transport, [self._FDP, self._ODP_NO_LOCATION])
        notes = " ".join(body["odp_results"][0]["calculation_notes"])
        assert "location not supplied" in notes
        assert "2 hours" in notes

    async def test_explicit_away_is_honoured_and_not_flagged(self, transport):
        odp = {**self._ODP_NO_LOCATION, "location": "away"}
        body = await _roster(transport, [self._FDP, odp])
        check = _odp_check(body)
        assert check["limit"] == 10.0
        assert check["clause"] == "§10.1a"
        notes = " ".join(body["odp_results"][0]["calculation_notes"])
        assert "location not supplied" not in notes

    async def test_sequence_discloses_the_default_too(self, transport):
        # Sequence events declare acclimatisation flat, not as a nested object —
        # see the note on this asymmetry in the handover.
        event = {k: v for k, v in self._FDP.items() if k != "acclimatisation"}
        event["acclimatisation_state"] = "acclimatised"
        body = await _sequence(transport, [event, self._ODP_NO_LOCATION])
        assert any("location not supplied" in n for n in body["calculation_notes"])

    async def test_odp_results_carry_calculation_notes(self, transport):
        """
        Previously odp_results had no notes field at all, while fdp_results did —
        so the ODP working was invisible in a roster response.
        """
        body = await _roster(transport, [self._FDP, self._ODP_NO_LOCATION])
        item = body["odp_results"][0]
        assert "calculation_notes" in item
        assert item["calculation_notes"], "notes must not be empty"
        assert any("§10.1b" in n for n in item["calculation_notes"])


# ═══════════════════════════════════════════════════════════════════════
# Cross-endpoint parity
# ═══════════════════════════════════════════════════════════════════════

class TestThreeWayParity:
    """
    The single assertion that would have caught every defect above: for the same
    duty, /calculate/min-off-duty, /validate/sequence and /validate/roster must
    agree on the minimum and on the clause.
    """

    @pytest.mark.parametrize(
        "appendix,duty_hours,split,state,location",
        [
            ("2", 13, True, "acclimatised", "home_base"),
            ("2", 13, False, "acclimatised", "home_base"),
            ("2", 13, True, "acclimatised", "away"),
            ("2", 10, False, "unknown", "away"),
            ("2", 10, False, "unknown", "home_base"),
            ("2", 14, False, "acclimatised", "away"),
            ("3", 13, True, "not_applicable", "home_base"),
            ("3", 10, False, "not_applicable", "away"),
            ("4", 13, False, "not_applicable", "home_base"),
        ],
    )
    async def test_all_three_endpoints_agree(
        self, transport, appendix, duty_hours, split, state, location,
    ):
        end_hour = 20 + duty_hours
        fdp_start = "2026-07-29T20:00:00Z"
        fdp_end = f"2026-07-{29 + end_hour // 24:02d}T{end_hour % 24:02d}:00:00Z"

        fdp_event = {
            "event_type": "fdp",
            "fdp_start_utc": fdp_start,
            "fdp_end_utc": fdp_end,
            "local_time_offset_hours": 8,
            "sectors": 2,
            "actual_duty_time_hours": duty_hours,
            "actual_flight_time_hours": 4,
        }
        if split:
            fdp_event["split_duty"] = _SPLIT_DUTY

        odp_event = {
            "event_type": "off_duty",
            "start_utc": fdp_end,
            "end_utc": "2026-07-31T20:00:00Z",
            "duration_hours": 20,
            "location": location,
        }

        calc_payload = {
            "appendix": appendix,
            "preceding_fdp": {
                "start_utc": fdp_start,
                "end_utc": fdp_end,
                "duration_hours": duty_hours,
                "location": location,
            },
            "acclimatisation_state": state,
        }
        if split:
            calc_payload["preceding_fdp"]["split_duty"] = {
                "duration_hours": 4,
                "accommodation": "sleeping",
                "overlaps_2300_0529": False,
            }

        roster = _odp_check(await _roster(
            transport,
            [{**fdp_event, "acclimatisation": {"state": state}}, odp_event],
            appendix=appendix,
        ))
        sequence = _sequence_odp_check(await _sequence(
            transport,
            [{**fdp_event, "acclimatisation_state": state}, odp_event],
            appendix=appendix,
        ))
        calc = await _min_off_duty(transport, calc_payload)

        assert roster["limit"] == calc["final_min_odp_hours"], (
            f"roster {roster['limit']} != calculate {calc['final_min_odp_hours']}"
        )
        assert sequence["limit"] == calc["final_min_odp_hours"], (
            f"sequence {sequence['limit']} != calculate {calc['final_min_odp_hours']}"
        )
        assert roster["clause"] == calc["clause"] == sequence["clause"]

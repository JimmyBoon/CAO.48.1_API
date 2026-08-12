"""
Regression tests for defects reported by the Aviation Toolbox build,
26 July 2026.

Each test names the defect it locks down. Two of them (§5.1 and §5.4) were
failures that OVER-reported the FDP limit, so they matter more than the count
of tests here suggests.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

PREFIX = "/api/v1/cao481"
pytestmark = pytest.mark.anyio


@pytest.fixture
def transport():
    return ASGITransport(app=app)


async def _post(transport, path: str, payload: dict):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.post(f"{PREFIX}{path}", json=payload)


# ═══════════════════════════════════════════════════════════════════════
# §5.1 — the early-start / WOCL clock
# ═══════════════════════════════════════════════════════════════════════

class TestAcclimatisedClockForEarlyStart:
    """
    Under Appendix 2 the early-start test uses acclimatised time, not the
    departure point's local time (§6, 'early start').

    The table band already honoured this; the early-start reduction did not,
    so an FCM acclimatised to Perth and signing on elsewhere had their
    consecutive-early-start reduction silently skipped — over-reporting the
    limit by up to 4 hours.
    """

    # 2130Z is 0530 in Perth (+8) and 2130 at a UTC+0 departure point.
    _BASE = {
        "appendix": "2",
        "sectors": 2,
        "fdp_start_utc": "2026-07-27T21:30:00Z",
        "local_time_offset_hours": 0,
    }

    async def test_band_uses_acclimatised_clock(self, transport):
        resp = await _post(transport, "/calculate/max-fdp", {
            **self._BASE,
            "acclimatisation": {
                "state": "acclimatised",
                "acclimatised_time_offset_hours": 8,
            },
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["base_max_fdp_hours"] == 11.0
        assert any("0500-0559" in note for note in body["calculation_notes"])

    async def test_fifth_consecutive_early_start_is_reduced(self, transport):
        """The defect: this used to return no reduction at all."""
        resp = await _post(transport, "/calculate/max-fdp", {
            **self._BASE,
            "consecutive_early_starts": 4,
            "acclimatisation": {
                "state": "acclimatised",
                "acclimatised_time_offset_hours": 8,
            },
        })
        body = resp.json()
        assert body["wocl_early_start_reduction_hours"] == 4.0
        assert body["final_max_fdp_hours"] == 7.0
        assert any(
            "acclimatised time" in note for note in body["calculation_notes"]
        ), "the notes must say which clock produced the determination"

    async def test_fourth_consecutive_early_start_reduced_by_two(self, transport):
        resp = await _post(transport, "/calculate/max-fdp", {
            **self._BASE,
            "consecutive_early_starts": 3,
            "acclimatisation": {
                "state": "acclimatised",
                "acclimatised_time_offset_hours": 8,
            },
        })
        assert resp.json()["wocl_early_start_reduction_hours"] == 2.0

    async def test_clock_divergence_is_disclosed(self, transport):
        resp = await _post(transport, "/calculate/max-fdp", {
            **self._BASE,
            "acclimatisation": {
                "state": "acclimatised",
                "acclimatised_time_offset_hours": 8,
            },
        })
        notes = " ".join(resp.json()["calculation_notes"])
        assert "2130" in notes and "0530" in notes, (
            "when the two clocks differ, both must appear in the audit trail"
        )

    async def test_other_appendices_still_use_departure_local_time(self, transport):
        """
        The fix must be Appendix 2 specific.

        For every other appendix the instrument specifies local time at the
        point the FDP commences, so a supplied acclimatised offset must be
        ignored.
        """
        payload = {
            "appendix": "3",
            "sectors": 2,
            "fdp_start_utc": "2026-07-27T21:30:00Z",
            "local_time_offset_hours": 0,
            "consecutive_early_starts": 4,
            "acclimatisation": {
                "state": "acclimatised",
                "acclimatised_time_offset_hours": 8,
            },
        }
        body = (await _post(transport, "/calculate/max-fdp", payload)).json()
        # 2130 local is not an early start, so no reduction.
        assert body["wocl_early_start_reduction_hours"] == 0.0

    async def test_existing_callers_unaffected(self, transport):
        """
        A request that does not supply the acclimatised offset must behave
        exactly as it did before — the departure point remains the default.
        """
        body = (await _post(transport, "/calculate/max-fdp", {
            "appendix": "2",
            "sectors": 2,
            "fdp_start_utc": "2026-07-27T21:30:00Z",
            "local_time_offset_hours": 8,
            "acclimatisation": {"state": "acclimatised"},
        })).json()
        assert body["base_max_fdp_hours"] == 11.0
        assert any("local time" in n for n in body["calculation_notes"])


# ═══════════════════════════════════════════════════════════════════════
# §5.4 — split duty across the night window
# ═══════════════════════════════════════════════════════════════════════

class TestSplitDutyNightWindow:
    """
    Once a split-duty rest includes any part of 2300-0529, the stricter
    regime governs: 7 continuous hours with sleeping accommodation.

    A sub-7-hour rest used to fall through to the ordinary 4-hour rule and
    collect the extension anyway.
    """

    _BASE = {
        "appendix": "2",
        "sectors": 2,
        "fdp_start_utc": "2026-07-27T22:00:00Z",
        "local_time_offset_hours": 8,
        "acclimatisation": {"state": "acclimatised"},
    }

    def _split(self, hours: float, accommodation: str, night: bool) -> dict:
        return {
            "rest_start_utc": "2026-07-28T04:00:00Z",
            "rest_end_utc": "2026-07-28T09:00:00Z",
            "accommodation": accommodation,
            "duration_hours": hours,
            "overlaps_2300_0529": night,
        }

    async def test_seven_hours_sleeping_over_night_window_extends(self, transport):
        body = (await _post(transport, "/calculate/max-fdp", {
            **self._BASE, "split_duty": self._split(7.0, "sleeping", True),
        })).json()
        assert body["final_max_fdp_hours"] > body["base_max_fdp_hours"]
        assert body["final_max_fdp_hours"] <= 16.0

    async def test_five_hours_sleeping_over_night_window_earns_nothing(self, transport):
        """The defect: this used to receive the ordinary §4.1 extension."""
        body = (await _post(transport, "/calculate/max-fdp", {
            **self._BASE, "split_duty": self._split(5.0, "sleeping", True),
        })).json()
        assert body["final_max_fdp_hours"] == body["base_max_fdp_hours"]
        assert body["adjustments"] == []
        assert any(
            "night window" in note for note in body["calculation_notes"]
        ), "the reason for refusing the extension must be stated"

    async def test_resting_accommodation_over_night_window_earns_nothing(self, transport):
        body = (await _post(transport, "/calculate/max-fdp", {
            **self._BASE, "split_duty": self._split(8.0, "resting", True),
        })).json()
        assert body["final_max_fdp_hours"] == body["base_max_fdp_hours"]

    async def test_five_hours_clear_of_night_window_still_extends(self, transport):
        """Outside the window the ordinary 4-hour rule is untouched."""
        body = (await _post(transport, "/calculate/max-fdp", {
            **self._BASE, "split_duty": self._split(5.0, "sleeping", False),
        })).json()
        assert body["final_max_fdp_hours"] > body["base_max_fdp_hours"]


# ═══════════════════════════════════════════════════════════════════════
# §6.1 — augmented crew without acclimatisation
# ═══════════════════════════════════════════════════════════════════════

class TestAugmentedCrewRequiresAcclimatisation:
    """Used to raise a KeyError and surface as a 500."""

    _AUGMENTED = {"additional_fcms": 1, "rest_facility_class": "class_2"}

    async def test_missing_acclimatisation_returns_422_naming_the_field(self, transport):
        resp = await _post(transport, "/calculate/max-fdp", {
            "appendix": "2",
            "sectors": 2,
            "local_time_offset_hours": 8,
            "fdp_start_utc": "2026-07-27T22:00:00Z",
            "augmented_crew": self._AUGMENTED,
        })
        assert resp.status_code == 422
        assert "acclimatisation.state" in resp.text

    async def test_not_applicable_state_also_rejected(self, transport):
        resp = await _post(transport, "/calculate/max-fdp", {
            "appendix": "2",
            "sectors": 2,
            "local_time_offset_hours": 8,
            "fdp_start_utc": "2026-07-27T22:00:00Z",
            "augmented_crew": self._AUGMENTED,
            "acclimatisation": {"state": "not_applicable"},
        })
        assert resp.status_code == 422

    @pytest.mark.parametrize("state", ["acclimatised", "unknown"])
    async def test_valid_states_return_200(self, transport, state):
        resp = await _post(transport, "/calculate/max-fdp", {
            "appendix": "2",
            "sectors": 2,
            "local_time_offset_hours": 8,
            "fdp_start_utc": "2026-07-27T22:00:00Z",
            "preceding_off_duty_hours": 32,
            "augmented_crew": self._AUGMENTED,
            "acclimatisation": {"state": state},
        })
        assert resp.status_code == 200

    async def test_validate_fdp_enforces_the_same_rule(self, transport):
        """The two endpoints must not drift apart."""
        resp = await _post(transport, "/validate/fdp", {
            "appendix": "2",
            "sectors": 2,
            "local_time_offset_hours": 8,
            "fdp_start_utc": "2026-07-27T22:00:00Z",
            "fdp_end_utc": "2026-07-28T08:00:00Z",
            "augmented_crew": self._AUGMENTED,
        })
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# §6.2 — silently ignored inputs
# ═══════════════════════════════════════════════════════════════════════

class TestUnknownFieldsRejected:
    """
    Silently discarding an input on a fatigue calculator is the dangerous
    failure mode: the caller gets a plausible answer computed from incomplete
    data with no indication anything went wrong.
    """

    async def test_misplaced_prior_off_duty_hours_is_rejected(self, transport):
        """The exact mistake that cost the website real time."""
        resp = await _post(transport, "/calculate/max-fdp", {
            "appendix": "2",
            "sectors": 4,
            "local_time_offset_hours": 8,
            "fdp_start_utc": "2026-07-27T21:30:00Z",
            "acclimatisation": {"state": "unknown", "prior_off_duty_hours": 32},
        })
        assert resp.status_code == 422
        assert "prior_off_duty_hours" in resp.text

    async def test_top_level_field_is_the_one_that_works(self, transport):
        """Sent correctly, 32 hours selects the >=30h row of Table 3.1."""
        under = (await _post(transport, "/calculate/max-fdp", {
            "appendix": "2",
            "sectors": 4,
            "local_time_offset_hours": 8,
            "fdp_start_utc": "2026-07-27T21:30:00Z",
            "acclimatisation": {"state": "unknown"},
            "preceding_off_duty_hours": 20,
        })).json()
        over = (await _post(transport, "/calculate/max-fdp", {
            "appendix": "2",
            "sectors": 4,
            "local_time_offset_hours": 8,
            "fdp_start_utc": "2026-07-27T21:30:00Z",
            "acclimatisation": {"state": "unknown"},
            "preceding_off_duty_hours": 32,
        })).json()
        assert over["base_max_fdp_hours"] > under["base_max_fdp_hours"]

    async def test_misspelled_top_level_field_is_rejected(self, transport):
        resp = await _post(transport, "/calculate/max-fdp", {
            "appendix": "3",
            "sectors": 2,
            "local_time_offset_hours": 8,
            "fdp_start_utc": "2026-07-27T22:00:00Z",
            "preceeding_off_duty_hours": 32,  # deliberate typo
        })
        assert resp.status_code == 422
        assert "preceeding_off_duty_hours" in resp.text


# ═══════════════════════════════════════════════════════════════════════
# §6.3 / §6.4 — the guide
# ═══════════════════════════════════════════════════════════════════════

class TestGuideIsGenerated:
    """
    The guide used to be hand-maintained and had drifted from the models.
    These tests assert against the models rather than against fixed strings,
    so they keep working as the API evolves.
    """

    @pytest.fixture
    async def guide(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"{PREFIX}/guide")
        return resp.json()

    def _endpoint(self, guide: dict, path: str) -> dict:
        return next(e for e in guide["endpoints"] if e["path"] == path)

    def _parameter_text(self, guide: dict) -> str:
        """
        Every generated parameter and response block, as one lower-case blob.

        Scoped to the generated sections deliberately: the hand-written
        important_notes now warn AGAINST the three-day rule and the
        `not_acclimatised` value by naming them, which is the opposite
        problem and must not trip these tests.
        """
        import json
        return json.dumps([
            {
                "parameters": entry.get("parameters"),
                "response_fields": entry.get("response_fields"),
            }
            for entry in guide["endpoints"]
        ]).lower()

    async def test_no_three_day_rule_in_parameter_docs(self, guide):
        """There is no three-day acclimatisation rule in CAO 48.1 §7."""
        text = self._parameter_text(guide)
        assert "3 days" not in text
        assert "≥3 days" not in text
        assert "three-day" not in text

    async def test_no_not_acclimatised_enum_value(self, guide):
        """`not_acclimatised` is not in the live enum and never was."""
        assert "not_acclimatised" not in self._parameter_text(guide)

    async def test_acclimatisation_enum_matches_the_model(self, guide):
        from app.models.calculation import AcclimatisationInput

        entry = self._endpoint(guide, "/calculate/max-fdp")
        accl = next(p for p in entry["parameters"] if p["name"] == "acclimatisation")
        state = next(f for f in accl["fields"] if f["name"] == "state")
        expected = list(
            AcclimatisationInput.model_fields["state"].annotation.__args__
        )
        assert state["valid_values"] == expected

    async def test_acclimatised_time_offset_is_documented(self, guide):
        """The shipped field the first integrator could not find."""
        entry = self._endpoint(guide, "/calculate/max-fdp")
        accl = next(p for p in entry["parameters"] if p["name"] == "acclimatisation")
        names = {f["name"] for f in accl["fields"]}
        assert "acclimatised_time_offset_hours" in names

    async def test_adjustments_shape_is_documented(self, guide):
        """§6.3 — the website guessed `detail` and `reason` and got neither."""
        entry = self._endpoint(guide, "/calculate/max-fdp")
        adjustments = next(
            f for f in entry["response_fields"] if f["name"] == "adjustments"
        )
        names = {f["name"] for f in adjustments["fields"]}
        assert names == {
            "clause", "description", "adjustment_hours", "running_total_hours",
        }

    async def test_parameters_match_the_request_model_exactly(self, guide):
        """
        Every documented endpoint's parameters are the model's fields — no
        more, no fewer. This is what stops the guide drifting again.
        """
        from app.data.guide import ENDPOINT_NARRATIVES

        for narrative in ENDPOINT_NARRATIVES:
            model = narrative.get("request_model")
            if model is None:
                continue
            entry = self._endpoint(guide, narrative["path"])
            documented = {
                p["name"] for p in entry["parameters"] if p.get("in") != "path"
            }
            assert documented == set(model.model_fields), (
                f"{narrative['path']} parameters have drifted from {model.__name__}"
            )

    async def test_min_off_duty_documents_the_nested_object(self, guide):
        """It used to document a flat parameter set."""
        entry = self._endpoint(guide, "/calculate/min-off-duty")
        preceding = next(
            p for p in entry["parameters"] if p["name"] == "preceding_fdp"
        )
        assert preceding.get("fields"), "preceding_fdp must be expanded"

    async def test_no_removed_parameter_survives(self, guide):
        """`local_start_time_of_day_hours` has not existed for some time."""
        import json
        assert "local_start_time_of_day_hours" not in json.dumps(guide)

    async def test_new_endpoints_documented(self, guide):
        paths = {e["path"] for e in guide["endpoints"]}
        assert "/calculate/acclimatisation" in paths
        assert "/limits/adaptation-table" in paths


# ═══════════════════════════════════════════════════════════════════════
# Appendix 2 §3.4 — consecutive unknown-state FDPs
# ═══════════════════════════════════════════════════════════════════════

class TestConsecutiveUnknownStateFdps:
    """
    'An FCM may only be assigned 4 consecutive FDPs in an unknown state of
    acclimatisation.' Nothing checked this before.
    """

    def _fdp(self, day: int, state: str = "unknown") -> dict:
        return {
            "event_type": "fdp",
            "fdp_start_utc": f"2026-07-{day:02d}T22:00:00Z",
            "fdp_end_utc": f"2026-07-{day + 1:02d}T06:00:00Z",
            "actual_flight_time_hours": 6.0,
            "actual_duty_time_hours": 8.0,
            "local_time_offset_hours": 8.0,
            "acclimatisation_state": state,
            "sectors": 2,
        }

    def _odp(self, day: int) -> dict:
        return {
            "event_type": "off_duty",
            "start_utc": f"2026-07-{day:02d}T06:00:00Z",
            "end_utc": f"2026-07-{day:02d}T22:00:00Z",
            "duration_hours": 16.0,
            "includes_local_night": True,
            "location": "away",
        }

    def _sequence(self, count: int, state: str = "unknown") -> dict:
        events = []
        for index in range(count):
            day = 1 + index * 2
            events.append(self._fdp(day, state))
            events.append(self._odp(day + 1))
        return {"appendix": "2", "events": events}

    def _violations(self, body: dict) -> list[dict]:
        return [
            v for v in body["violations"]
            if "consecutive_unknown_state_fdps" in v["check"]
        ]

    async def test_four_consecutive_is_permitted(self, transport):
        body = (await _post(
            transport, "/validate/sequence", self._sequence(4),
        )).json()
        assert self._violations(body) == []

    async def test_fifth_consecutive_raises_a_violation(self, transport):
        body = (await _post(
            transport, "/validate/sequence", self._sequence(5),
        )).json()
        violations = self._violations(body)
        assert len(violations) == 1
        assert violations[0]["clause"] == "Appendix 2 §3.4"
        assert violations[0]["actual"] == 5.0
        assert violations[0]["limit"] == 4.0

    async def test_acclimatised_fdp_resets_the_run(self, transport):
        """
        Four unknown, then an acclimatised FDP, then four more unknown.

        Declaring an FDP as acclimatised is how a caller expresses that an
        adaptation period has been completed.
        """
        events = self._sequence(4)["events"]
        events.append(self._fdp(9, "acclimatised"))
        events.append(self._odp(10))
        events.extend(self._sequence(4)["events"][:1])
        body = (await _post(
            transport, "/validate/sequence",
            {"appendix": "2", "events": events},
        )).json()
        assert self._violations(body) == []

    async def test_rule_does_not_apply_to_other_appendices(self, transport):
        payload = self._sequence(5)
        payload["appendix"] = "3"
        body = (await _post(transport, "/validate/sequence", payload)).json()
        assert self._violations(body) == []

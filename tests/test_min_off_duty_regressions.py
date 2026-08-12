"""
Regression tests for the /calculate/min-off-duty defects reported by
Aviation Toolbox, 26 July 2026, plus five found while investigating them.

The reported items:
  1. acclimatisation_state ignored — safety-critical, under-reported a rest
     period by up to four hours
  2. displacement time never computed and no way to supply it
  3. clause citations wrong

Found while verifying:
  4. Appendix 2 reduction clauses cited as §10.4/§10.5 instead of §10.3/§10.4
  5. the 9-hour reduction offered above the §10.3/§8.3 ten-hour duty ceiling
  6. the 9-hour reduction offered to unknown-state crew (§10.3(b))
  7. the 14-hour reduction offered to unknown-state crew (§10.4(c))
  8. Appendix 4B displacement declared in config but never applied
  9. Appendix 5 adding 1.5x the excess over 12h, which §5.1 does not contain

Every assertion checks the FIGURE and, where the brief asked for it, the CLAUSE.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.engines.off_duty_calculator import calculate_min_off_duty
from app.main import app

PREFIX = "/api/v1/cao481"
pytestmark = pytest.mark.anyio


@pytest.fixture
def transport():
    return ASGITransport(app=app)


# preceding_fdp requires the FDP instants as well as its duration.
_FDP_10H = {
    "duration_hours": 10,
    "location": "away",
    "start_utc": "2026-07-27T21:30:00Z",
    "end_utc": "2026-07-28T07:30:00Z",
}


def _calc(**kwargs):
    """calculate_min_off_duty with a 10-hour Appendix 2 FDP as the default."""
    params = {
        "appendix": "2",
        "preceding_fdp_duration_hours": 10.0,
        "location": "away",
    }
    params.update(kwargs)
    return calculate_min_off_duty(**params)


# ═══════════════════════════════════════════════════════════════════════
# Defect 1 — the unknown-state branch
# ═══════════════════════════════════════════════════════════════════════

class TestUnknownStateBase:
    """
    §10.1(c): 14 hours, no home base / away distinction.
    §10.2(b): 14 hours plus 1.5x the excess over 12.

    Previously the unknown-state rows were byte-identical to the acclimatised
    ones — the parameter was accepted and discarded.
    """

    @pytest.mark.parametrize(
        "state,location,expected_hours,expected_clause",
        [
            # The exact table from §1 of the brief.
            ("acclimatised", "away", 10.0, "§10.1a"),
            ("acclimatised", "home_base", 12.0, "§10.1b"),
            ("unknown", "away", 14.0, "§10.1c"),
            ("unknown", "home_base", 14.0, "§10.1c"),
        ],
    )
    async def test_brief_table_figure_and_clause(
        self, state, location, expected_hours, expected_clause,
    ):
        result = _calc(acclimatisation_state=state, location=location)
        assert result["base_min_odp_hours"] == expected_hours
        assert result["clause"] == expected_clause

    @pytest.mark.parametrize(
        "state,expected_hours,expected_clause",
        [
            # 12.5h duty: excess 0.5h, x1.5 = 0.75h on top of the base.
            ("acclimatised", 12.75, "§10.2a"),
            ("unknown", 14.75, "§10.2b"),
        ],
    )
    async def test_over_threshold_branch(self, state, expected_hours, expected_clause):
        result = _calc(
            preceding_fdp_duration_hours=12.5, acclimatisation_state=state,
        )
        assert result["base_min_odp_hours"] == pytest.approx(expected_hours)
        assert result["clause"] == expected_clause

    async def test_unknown_state_over_threshold_ignores_location(self):
        """§10.2 has no home/away distinction in either branch."""
        away = _calc(
            preceding_fdp_duration_hours=13, acclimatisation_state="unknown",
            location="away",
        )
        home = _calc(
            preceding_fdp_duration_hours=13, acclimatisation_state="unknown",
            location="home_base",
        )
        assert away["base_min_odp_hours"] == home["base_min_odp_hours"] == 15.5

    async def test_unknown_state_note_explains_no_location_distinction(self):
        notes = " ".join(_calc(acclimatisation_state="unknown")["calculation_notes"])
        assert "no home base / away distinction" in notes

    @pytest.mark.parametrize("appendix", ["3", "4"])
    async def test_appendices_without_unknown_branch_are_unaffected(self, appendix):
        """
        Appendix 3 §8 and Appendix 4 §8 have no unknown-state branch, so the
        declared state must not change their answer.
        """
        acclimatised = _calc(appendix=appendix, acclimatisation_state="acclimatised")
        unknown = _calc(appendix=appendix, acclimatisation_state="unknown")
        assert acclimatised["base_min_odp_hours"] == unknown["base_min_odp_hours"]

    async def test_endpoint_returns_14h_for_unknown_state(self, transport):
        """The brief's reproduction request, end to end."""
        payload = {
            "appendix": "2",
            "preceding_fdp": {
                "duration_hours": 10,
                "location": "away",
                "start_utc": "2026-07-27T21:30:00Z",
                "end_utc": "2026-07-28T07:30:00Z",
            },
            "acclimatisation_state": "unknown",
            "following_off_duty_location": "away",
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/calculate/min-off-duty", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["final_min_odp_hours"] == 14.0
        assert body["clause"] == "§10.1c"


# ═══════════════════════════════════════════════════════════════════════
# Defect 2 — displacement time
# ═══════════════════════════════════════════════════════════════════════

class TestDisplacementTime:
    """
    Derived from the two offsets per the §6 definition, so west and east
    cannot be transposed by the caller — transposing them shortens the rest.
    """

    @pytest.mark.parametrize(
        "fdp_offset,odp_offset,expected_magnitude,expected_direction",
        [
            (8.0, 3.0, 5.0, "west"),    # Perth -> a smaller offset = westward
            (8.0, 13.0, 5.0, "east"),   # Perth -> a larger offset = eastward
            (8.0, 9.5, 1.5, "east"),    # half-hour offsets
            (5.75, 8.0, 2.25, "east"),  # quarter-hour offsets
        ],
    )
    async def test_direction_derived_from_offsets(
        self, fdp_offset, odp_offset, expected_magnitude, expected_direction,
    ):
        notes = " ".join(_calc(
            fdp_commencement_utc_offset_hours=fdp_offset,
            following_off_duty_utc_offset_hours=odp_offset,
        )["calculation_notes"])
        assert f"{expected_magnitude}h {expected_direction}" in notes

    async def test_acclimatised_adds_only_the_excess_west(self):
        """§10.1(a)(ii): the amount by which displacement exceeds 3h west."""
        result = _calc(
            acclimatisation_state="acclimatised",
            fdp_commencement_utc_offset_hours=8.0,
            following_off_duty_utc_offset_hours=3.0,   # 5h west
        )
        assert result["base_min_odp_hours"] == 12.0   # 10 + (5 - 3)

    async def test_acclimatised_adds_only_the_excess_east(self):
        """East uses a 2h threshold, not 3h."""
        result = _calc(
            acclimatisation_state="acclimatised",
            fdp_commencement_utc_offset_hours=8.0,
            following_off_duty_utc_offset_hours=10.5,  # 2.5h east
        )
        assert result["base_min_odp_hours"] == pytest.approx(10.5)  # 10 + 0.5

    async def test_below_threshold_adds_nothing(self):
        result = _calc(
            acclimatisation_state="acclimatised",
            fdp_commencement_utc_offset_hours=8.0,
            following_off_duty_utc_offset_hours=6.0,   # 2h west, under the 3h threshold
        )
        assert result["base_min_odp_hours"] == 10.0
        assert any(
            "does not exceed" in note
            for note in result["calculation_notes"]
        )

    async def test_unknown_state_adds_the_full_displacement(self):
        """§10.1(c)(ii): the whole displacement time, not just the excess."""
        result = _calc(
            acclimatisation_state="unknown",
            fdp_commencement_utc_offset_hours=8.0,
            following_off_duty_utc_offset_hours=3.0,   # 5h west
        )
        assert result["base_min_odp_hours"] == 19.0   # 14 + 5
        assert any("in full" in note for note in result["calculation_notes"])

    async def test_note_disappears_once_supplied(self):
        """The brief asked specifically for this."""
        without = " ".join(_calc()["calculation_notes"])
        with_offsets = " ".join(_calc(
            fdp_commencement_utc_offset_hours=8.0,
            following_off_duty_utc_offset_hours=3.0,
        )["calculation_notes"])
        assert "NOT included" in without
        assert "NOT included" not in with_offsets

    async def test_appendix_3_has_no_displacement_note(self):
        """Appendix 3 §8 contains no displacement term at all."""
        notes = " ".join(_calc(appendix="3")["calculation_notes"])
        assert "Displacement" not in notes

    async def test_endpoint_accepts_the_offsets(self, transport):
        payload = {
            "appendix": "2",
            "preceding_fdp": {
                "duration_hours": 10,
                "location": "away",
                "start_utc": "2026-07-27T21:30:00Z",
                "end_utc": "2026-07-28T07:30:00Z",
                "commencement_utc_offset_hours": 8.0,
            },
            "acclimatisation_state": "unknown",
            "following_off_duty_utc_offset_hours": 3.0,
        }
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(f"{PREFIX}/calculate/min-off-duty", json=payload)
        assert resp.status_code == 200
        assert resp.json()["final_min_odp_hours"] == 19.0


# ═══════════════════════════════════════════════════════════════════════
# Defect 3 — clause citations
# ═══════════════════════════════════════════════════════════════════════

class TestClauseCitations:
    """
    The clause is the one part of the response a crew member can take to their
    operator. A citation that points at the wrong subclause is worse than none.
    """

    async def test_home_and_away_no_longer_share_a_citation(self):
        away = _calc(location="away", acclimatisation_state="acclimatised")
        home = _calc(location="home_base", acclimatisation_state="acclimatised")
        assert away["clause"] == "§10.1a"
        assert home["clause"] == "§10.1b"
        assert away["clause"] != home["clause"]

    async def test_over_threshold_cites_10_2_not_10_1(self):
        """The 1.5x rule is §10.2(a). §10.1 is the <=12h case."""
        result = _calc(preceding_fdp_duration_hours=12.5, acclimatisation_state="acclimatised")
        assert result["clause"] == "§10.2a"
        assert "§10.1" not in result["clause"]

    @pytest.mark.parametrize(
        "appendix,location,expected",
        [
            ("3", "away", "§8.1a"),
            ("3", "home_base", "§8.1b"),
            ("4", "away", "§8.1a"),
            ("4", "home_base", "§8.1b"),
        ],
    )
    async def test_appendices_3_and_4_distinguish_a_from_b(
        self, appendix, location, expected,
    ):
        """The brief noted the same shared-formatter bug on Appendix 3."""
        assert _calc(appendix=appendix, location=location)["clause"] == expected

    @pytest.mark.parametrize("appendix", ["3", "4"])
    async def test_appendices_3_and_4_over_threshold_cite_8_2(self, appendix):
        result = _calc(appendix=appendix, preceding_fdp_duration_hours=13)
        assert result["clause"] == "§8.2"

    async def test_notes_carry_the_same_clause_as_the_field(self):
        """A note citing a different subclause from the clause field is worse."""
        for state, location in (
            ("acclimatised", "away"), ("acclimatised", "home_base"),
            ("unknown", "away"),
        ):
            result = _calc(acclimatisation_state=state, location=location)
            assert any(
                result["clause"] in note for note in result["calculation_notes"]
            ), f"{state}/{location}: clause {result['clause']} absent from notes"


# ═══════════════════════════════════════════════════════════════════════
# Defect 4 — reduction clause references
# ═══════════════════════════════════════════════════════════════════════

class TestReductionClauseReferences:
    """
    §10.3 is the 9-hour reduction and §10.4 the 14-hour one. The config cited
    §10.4 and §10.5 — and §10.5 is the 168-hour recovery clause, an entirely
    different rule.
    """

    async def test_9h_reduction_cites_10_3(self):
        result = _calc(
            acclimatisation_state="acclimatised",
            preceding_odp_duration_hours=12,
            preceding_odp_included_night=True,
        )
        assert result["reduction_applicable"]["clause"] == "§10.3"

    async def test_14h_reduction_cites_10_4(self):
        # A long duty pushes the calculated ODP above 14h so §10.4 is in play.
        result = _calc(
            preceding_fdp_duration_hours=15,
            acclimatisation_state="acclimatised",
        )
        assert result["reduction_applicable"]["clause"] == "§10.4"

    @pytest.mark.parametrize("appendix,expected", [("3", "§8.3"), ("4", "§8.3")])
    async def test_appendices_3_and_4_unchanged(self, appendix, expected):
        result = _calc(
            appendix=appendix,
            preceding_odp_duration_hours=12,
            preceding_odp_included_night=True,
        )
        assert result["reduction_applicable"]["clause"] == expected


# ═══════════════════════════════════════════════════════════════════════
# Defects 5, 6 and 7 — reduction gating
# ═══════════════════════════════════════════════════════════════════════

class TestReductionGating:
    """
    Both reductions were being offered where the instrument does not allow
    them. Offering a reduction that is not available is the unsafe direction —
    it says a crew member may be called back earlier than the rules permit.
    """

    def _eligible_9h(self, **kwargs):
        params = {
            "acclimatisation_state": "acclimatised",
            "preceding_odp_duration_hours": 12,
            "preceding_odp_included_night": True,
            "following_includes_local_night": True,
            "location": "away",
        }
        params.update(kwargs)
        return _calc(**params)

    async def test_9h_reduction_available_at_the_ceiling(self):
        result = self._eligible_9h(preceding_fdp_duration_hours=10)
        assert result["final_min_odp_hours"] == 9.0

    async def test_9h_reduction_withheld_above_the_ceiling(self):
        """§10.3 / §8.3 require FDP + other duty not exceeding 10 hours."""
        result = self._eligible_9h(preceding_fdp_duration_hours=10.5)
        assert result["reduction_applicable"] is None
        assert result["final_min_odp_hours"] == 10.0
        assert any("ceiling" in note for note in result["calculation_notes"])

    async def test_9h_ceiling_counts_post_fdp_duty(self):
        result = self._eligible_9h(
            preceding_fdp_duration_hours=9.5, post_fdp_duty_hours=1.0,
        )
        assert result["reduction_applicable"] is None

    async def test_9h_ceiling_uses_the_credited_figure(self):
        """
        §3.2 / §4.2 apply the split-duty credit "in determining the subsequent
        off-duty period ... under clause 8 [or 10]", and the reduction subclause
        sits inside that clause — so the ceiling tests the credited figure.
        """
        result = self._eligible_9h(
            preceding_fdp_duration_hours=11.0,
            split_duty_duration_hours=4.0,
            split_duty_accommodation="sleeping",
        )
        assert result["split_duty_credit_hours"] == 2.0
        assert result["reduction_applicable"] is not None

    async def test_9h_reduction_withheld_in_unknown_state(self):
        """§10.3(b) requires the FCM to be acclimatised at ODP 2 commencement."""
        result = self._eligible_9h(acclimatisation_state="unknown")
        assert result["reduction_applicable"] is None
        assert result["final_min_odp_hours"] == 14.0
        assert any(
            "acclimatised" in note and "§10.3" in note
            for note in result["calculation_notes"]
        )

    async def test_14h_reduction_withheld_in_unknown_state(self):
        """§10.4(c) requires an acclimatised commencement of the second FDP."""
        result = _calc(
            preceding_fdp_duration_hours=15, acclimatisation_state="unknown",
        )
        assert result["reduction_applicable"] is None

    async def test_14h_reduction_available_when_acclimatised(self):
        result = _calc(
            preceding_fdp_duration_hours=15, acclimatisation_state="acclimatised",
        )
        assert result["final_min_odp_hours"] == 14.0

    async def test_appendix_3_9h_reduction_has_no_acclimatisation_condition(self):
        """§8.3 contains no such condition, so the state must not matter."""
        result = _calc(
            appendix="3",
            acclimatisation_state="unknown",
            preceding_odp_duration_hours=12,
            preceding_odp_included_night=True,
        )
        assert result["reduction_applicable"] is not None
        assert result["final_min_odp_hours"] == 9.0

    async def test_conditions_list_names_the_duty_ceiling(self):
        conditions = self._eligible_9h()["reduction_applicable"]["conditions_met"]
        assert any("10" in c and "duty" in c.lower() for c in conditions)


# ═══════════════════════════════════════════════════════════════════════
# Defects 8 and 9 — Appendices 4B and 5
# ═══════════════════════════════════════════════════════════════════════

class TestAppendix4BAndAppendix5:
    async def test_4b_applies_the_full_displacement(self):
        """
        §5.1(b): 10h base + excess over 12h + FULL displacement of the FDP.
        14h FDP with a 4h displacement -> 10 + 2 + 4 = 16.
        """
        result = _calc(
            appendix="4B",
            preceding_fdp_duration_hours=14,
            fdp_commencement_utc_offset_hours=8.0,
            following_off_duty_utc_offset_hours=4.0,
        )
        assert result["base_min_odp_hours"] == 16.0

    async def test_4b_displacement_has_no_west_east_threshold(self):
        """A 1-hour displacement still counts in full under Appendix 4B."""
        result = _calc(
            appendix="4B",
            preceding_fdp_duration_hours=10,
            fdp_commencement_utc_offset_hours=8.0,
            following_off_duty_utc_offset_hours=7.0,
        )
        assert result["base_min_odp_hours"] == 11.0   # 10 + 1

    async def test_4b_warns_when_displacement_absent(self):
        notes = " ".join(
            _calc(appendix="4B", preceding_fdp_duration_hours=14)["calculation_notes"]
        )
        assert "NOT included" in notes

    async def test_appendix_5_is_flat_with_no_excess_term(self):
        """
        §5.1 is a flat 8 or 10 hours plus the §3.2 extension penalty. It has no
        excess-over-12h addend — the engine was adding 1.5x and over-reporting.
        """
        assert _calc(appendix="5", preceding_fdp_duration_hours=14)["base_min_odp_hours"] == 10.0
        assert _calc(appendix="5", preceding_fdp_duration_hours=10)["base_min_odp_hours"] == 10.0

    async def test_appendix_5_still_applies_the_extension_penalty(self):
        """1 hour of ODP per 30 minutes of extension."""
        result = _calc(
            appendix="5", preceding_fdp_duration_hours=10,
            was_extended=True, extension_hours=1.0,
        )
        assert result["base_min_odp_hours"] == 12.0   # 10 + 2

    async def test_appendix_5_has_no_displacement_term(self):
        notes = " ".join(
            _calc(appendix="5", preceding_fdp_duration_hours=14)["calculation_notes"]
        )
        assert "Displacement" not in notes


# ═══════════════════════════════════════════════════════════════════════
# /validate/off-duty consistency
# ═══════════════════════════════════════════════════════════════════════

class TestValidateOffDutyConsistency:
    """The brief asked that the equivalent paths behave consistently."""

    async def _validate(self, transport, payload):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(f"{PREFIX}/validate/off-duty", json=payload)

    async def test_unknown_state_fails_a_10h_rest(self, transport):
        """10 hours passed before the fix; §10.1(c) requires 14."""
        resp = await self._validate(transport, {
            "appendix": "2",
            "preceding_fdp": _FDP_10H,
            "actual_off_duty_hours": 10.0,
            "acclimatisation_state": "unknown",
        })
        body = resp.json()
        assert body["valid"] is False
        failed = next(v for v in body["violations"] if v["check"] == "odp_meets_minimum")
        assert failed["limit"] == 14.0
        assert failed["clause"] == "§10.1c"

    async def test_unknown_state_passes_a_14h_rest(self, transport):
        resp = await self._validate(transport, {
            "appendix": "2",
            "preceding_fdp": _FDP_10H,
            "actual_off_duty_hours": 14.0,
            "acclimatisation_state": "unknown",
        })
        assert resp.json()["valid"] is True

    async def test_displacement_offsets_raise_the_minimum(self, transport):
        resp = await self._validate(transport, {
            "appendix": "2",
            "preceding_fdp": {**_FDP_10H, "commencement_utc_offset_hours": 8.0},
            "actual_off_duty_hours": 11.0,
            "acclimatisation_state": "acclimatised",
            "following_off_duty_utc_offset_hours": 3.0,   # 5h west -> +2h
        })
        body = resp.json()
        assert body["valid"] is False
        failed = next(v for v in body["violations"] if v["check"] == "odp_meets_minimum")
        assert failed["limit"] == 12.0

    async def test_claimed_reduction_rejected_in_unknown_state(self, transport):
        resp = await self._validate(transport, {
            "appendix": "2",
            "preceding_fdp": _FDP_10H,
            "actual_off_duty_hours": 9.0,
            "acclimatisation_state": "unknown",
            "reduction_claimed": True,
            "preceding_off_duty": {
                "duration_hours": 12, "included_local_night": True,
            },
        })
        body = resp.json()
        assert body["valid"] is False
        assert any(
            v["check"] == "reduction_conditions_met" for v in body["violations"]
        )


# ═══════════════════════════════════════════════════════════════════════
# Guide coverage
# ═══════════════════════════════════════════════════════════════════════

class TestGuideDocumentsTheseFields:
    async def test_acclimatisation_state_and_offsets_documented(self, transport):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            guide = (await client.get(f"{PREFIX}/guide")).json()
        entry = next(
            e for e in guide["endpoints"] if e["path"] == "/calculate/min-off-duty"
        )
        names = {p["name"] for p in entry["parameters"]}
        assert "acclimatisation_state" in names
        assert "following_off_duty_utc_offset_hours" in names

        state = next(p for p in entry["parameters"] if p["name"] == "acclimatisation_state")
        assert "14" in state["description"], (
            "the guide must say the unknown-state base differs, not merely that "
            "the parameter exists"
        )

        preceding = next(p for p in entry["parameters"] if p["name"] == "preceding_fdp")
        nested = {f["name"] for f in preceding["fields"]}
        assert "commencement_utc_offset_hours" in nested

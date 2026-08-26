"""
Phase 7 — coverage pass over the areas the spec left untested (§7).

The spec predicted "expect similar findings" here, and there were six. Each
test below asserts the specific wrong output the API produced before the fix.
"""

import pytest
from fastapi.testclient import TestClient

from app.data.fdp_tables import FDP_CONFIGS
from app.main import app

client = TestClient(app)
BASE = "/api/v1/cao481"
APPENDICES = ["1", "2", "3", "4", "4A", "4B", "5", "5A", "6"]


def max_fdp(appendix="3", **overrides):
    body = {
        "appendix": appendix,
        "fdp_start_utc": "2026-03-24T02:00:00Z",   # 1000 local at +8
        "local_time_offset_hours": 8,
        "sectors": 2,
    }
    if appendix == "2":
        body["acclimatisation"] = {
            "state": "acclimatised", "acclimatised_time_offset_hours": 8,
        }
    body.update(overrides)
    response = client.post(f"{BASE}/calculate/max-fdp", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def rest(duration_hours, accommodation="sleeping", overlapping=False, claimed=None):
    """A split-duty rest that genuinely does or does not overlap 2300-0529."""
    start_h = 14 if overlapping else 4      # 2200 or 1200 local at +8
    end_h = start_h + int(duration_hours)
    payload = {
        "rest_start_utc": f"2026-03-24T{start_h:02d}:00:00Z",
        "rest_end_utc": f"2026-03-24T{end_h:02d}:00:00Z",
        "accommodation": accommodation,
        "duration_hours": duration_hours,
    }
    if claimed is not None:
        payload["overlaps_2300_0529"] = claimed
    return payload


# ═══════════════════════════════════════════════════════════════════════
# The night-overlap flag was taken on trust
# ═══════════════════════════════════════════════════════════════════════

class TestNightOverlapIsDerived:
    """
    §3.4(a) became a hard gate in Phase 3, but the flag that triggers it was
    caller-supplied. A rest running 2200-0300 local — which plainly overlaps —
    could be flagged False and collect the full §3.1 increase, walking straight
    past the gate. /validate/sequence already sets the precedent: derive from
    timestamps, never trust the flag.
    """

    def test_a_false_flag_no_longer_bypasses_the_gate(self):
        result = max_fdp(split_duty=rest(5, overlapping=True, claimed=False))
        assert result["final_max_fdp_hours"] == pytest.approx(13.0)  # was 16.0
        assert result["adjustments"][-1]["clause"] == "§3.4(a)"

    def test_a_true_flag_cannot_invent_an_overlap(self):
        result = max_fdp(split_duty=rest(5, overlapping=False, claimed=True))
        assert result["final_max_fdp_hours"] == pytest.approx(16.0)
        assert result["adjustments"][-1]["clause"] == "§3.1"

    def test_omitting_the_flag_works(self):
        overlapping = max_fdp(split_duty=rest(5, overlapping=True))
        clear = max_fdp(split_duty=rest(5, overlapping=False))
        assert overlapping["final_max_fdp_hours"] == pytest.approx(13.0)
        assert clear["final_max_fdp_hours"] == pytest.approx(16.0)

    def test_disagreement_is_reported(self):
        result = max_fdp(split_duty=rest(5, overlapping=True, claimed=False))
        assert any(
            "was supplied as False" in note for note in result["calculation_notes"]
        )

    @pytest.mark.parametrize(
        "start_utc,end_utc,expected_overlap",
        [
            ("2026-03-24T14:59:00Z", "2026-03-24T15:30:00Z", True),   # 2259-2330
            ("2026-03-24T13:00:00Z", "2026-03-24T14:30:00Z", False),  # 2100-2230
            ("2026-03-24T21:00:00Z", "2026-03-24T21:29:00Z", True),   # 0500-0529
            ("2026-03-24T21:30:00Z", "2026-03-24T23:00:00Z", False),  # 0530-0700
        ],
    )
    def test_window_edges(self, start_utc, end_utc, expected_overlap):
        from app.engines.time_windows import overlaps_local_window

        assert overlaps_local_window(
            start_utc, end_utc, 8, 23 * 60, 5 * 60 + 29
        ) is expected_overlap


class TestNightGateAppliesOnlyWhereTheLawImposesIt:
    """
    Phase 3's gate was applied through inherited window values, so appendices
    with no night-overlap clause were gated too. Appendix 4B clause 2 and
    Appendix 5 clause 2 impose no such condition — denying them the increase
    was a false violation that would block a lawful roster.
    """

    GATED = {"2": "§4.4(a)", "3": "§3.4(a)", "4": "§3.4(a)", "4A": "§3.3(a)", "6": "§3.4(a)"}
    UNGATED = ["4B", "5"]

    @pytest.mark.parametrize("appendix", list(GATED))
    def test_gated_appendices_withhold_the_increase(self, appendix):
        result = max_fdp(appendix, split_duty=rest(5, overlapping=True))
        assert result["final_max_fdp_hours"] == pytest.approx(
            result["base_max_fdp_hours"]
        )
        assert result["adjustments"][-1]["clause"] == self.GATED[appendix]

    @pytest.mark.parametrize("appendix", UNGATED)
    def test_ungated_appendices_still_get_their_increase(self, appendix):
        result = max_fdp(appendix, split_duty=rest(5, overlapping=True))
        assert result["final_max_fdp_hours"] > result["base_max_fdp_hours"]

    def test_appendix_4a_gate_grants_no_separate_ceiling(self):
        """
        4A §3.3 has an (a) limb and a credit-exclusion limb, but no
        increase-to-a-ceiling limb like §3.4(b). A compliant night-overlapping
        rest there takes the ordinary §3.1 treatment.
        """
        result = max_fdp("4A", split_duty=rest(7, overlapping=True))
        assert result["adjustments"][-1]["clause"] == "§3.1"

    @pytest.mark.parametrize("appendix", APPENDICES)
    def test_no_split_duty_adjustment_lacks_a_clause(self, appendix):
        for overlapping in (True, False):
            for accommodation in ("sleeping", "resting"):
                result = max_fdp(
                    appendix,
                    split_duty=rest(5, accommodation, overlapping=overlapping),
                )
                for adjustment in result["adjustments"]:
                    assert adjustment["clause"], (
                        f"Appendix {appendix} emitted an adjustment with no clause"
                    )


class TestAppendix1HasNoSplitDuty:
    """
    Appendix 1 contains no split-duty provision — "split" does not appear
    anywhere in the appendix — yet the rule table granted a +1h increase.
    Flagged in Phase 3, disabled here.
    """

    def test_no_increase_is_granted(self):
        for overlapping in (True, False):
            result = max_fdp("1", split_duty=rest(5, overlapping=overlapping))
            assert result["final_max_fdp_hours"] == pytest.approx(
                result["base_max_fdp_hours"]
            )
            assert result["adjustments"] == []

    def test_the_rule_table_records_it(self):
        assert FDP_CONFIGS["1"].split_duty.available is False


class TestAppendix4BPostSplitLimit:
    """
    §2.2: the remaining FDP after the rest must not exceed the Table 1.1 limit
    for an FCM commencing a NEW FDP at the resumption time. That is a lookup,
    and post_split_max_hours was 99.0 — no limit at all, on the appendix
    covering medical transport and emergency service operations.
    """

    def _post_split(self, rest_end_utc):
        result = max_fdp(
            "4B",
            fdp_start_utc="2026-03-23T23:00:00Z",
            split_duty={
                "rest_start_utc": "2026-03-24T02:00:00Z",
                "rest_end_utc": rest_end_utc,
                "accommodation": "sleeping",
                "duration_hours": (
                    int(rest_end_utc[11:13]) - 2
                ) % 24,
            },
        )
        return result["post_split_max_hours"]

    @pytest.mark.parametrize(
        "rest_end_utc,expected",
        [
            ("2026-03-24T04:00:00Z", 13.0),   # 1200 local -> 1200-1459 band
            ("2026-03-24T09:00:00Z", 11.0),   # 1700 local -> 1600-0459 band
            ("2026-03-24T19:00:00Z", 11.0),   # 0300 local -> 1600-0459 band
        ],
    )
    def test_limit_tracks_the_resumption_time(self, rest_end_utc, expected):
        assert self._post_split(rest_end_utc) == pytest.approx(expected)

    def test_it_is_no_longer_unlimited(self):
        assert self._post_split("2026-03-24T04:00:00Z") < 99.0

    def test_other_appendices_keep_their_fixed_limits(self):
        assert max_fdp("3", split_duty=rest(5))["post_split_max_hours"] == pytest.approx(6.0)
        assert max_fdp("4", split_duty=rest(5))["post_split_max_hours"] == pytest.approx(5.0)


# ═══════════════════════════════════════════════════════════════════════
# §8.1 parameter contract — accepted fields must be read
# ═══════════════════════════════════════════════════════════════════════

class TestExtensionConditionFields:
    """
    `pre_planned` and `captains_authority` were accepted by the schema and read
    by nothing. Worse, `captains_authority` defaulted to False, so every caller
    who omitted it was silently asserting that PIC discretion was NOT
    exercised.
    """

    def _extension_check(self, appendix="3", **extension):
        body = {
            "appendix": appendix,
            "fdp_start_utc": "2026-03-23T23:00:00Z",
            "fdp_end_utc": "2026-03-24T09:00:00Z",
            "local_time_offset_hours": 8,
            "sectors": 2,
            "extension": {"type": "unforeseen", "hours_used": 1.0, **extension},
        }
        response = client.post(f"{BASE}/validate/fdp", json=body)
        assert response.status_code == 200, response.text
        return next(
            c for c in response.json()["checks"] if c["check"] == "extension_permitted"
        )

    def test_omitting_them_does_not_fail_the_extension(self):
        assert self._extension_check()["passed"] is True

    def test_pre_planned_defeats_the_unforeseen_provision(self):
        check = self._extension_check(pre_planned=True)
        assert check["passed"] is False
        assert "unforeseen operational circumstances" in check["detail"]

    def test_pre_planned_false_is_fine(self):
        assert self._extension_check(pre_planned=False)["passed"] is True

    def test_denying_captains_authority_defeats_the_extension(self):
        check = self._extension_check(captains_authority=False)
        assert check["passed"] is False
        assert "discretion of the pilot in command" in check["detail"]

    def test_pre_planned_does_not_affect_an_urgent_extension(self):
        """
        4B §3.2 turns on the operations manual and an urgency determination,
        not on foreseeability.
        """
        check = self._extension_check(
            appendix="4B", type="urgent", hours_used=4.0, pre_planned=True,
        )
        assert check["passed"] is True


class TestParameterContract:
    """§8.1: every accepted field is read somewhere, or rejected."""

    def test_no_request_field_is_unreferenced(self):
        import pathlib
        import re

        from pydantic import BaseModel

        from app.models import calculation, validation

        source = "\n".join(p.read_text() for p in pathlib.Path("app").rglob("*.py"))

        unreferenced = []
        for module in (calculation, validation):
            for attr in dir(module):
                model = getattr(module, attr)
                if not (
                    isinstance(model, type)
                    and issubclass(model, BaseModel)
                    and model is not BaseModel
                ):
                    continue
                if not (
                    attr.endswith(("Request", "Input", "Event", "Entry", "Record"))
                ):
                    continue
                for field in model.model_fields:
                    # A field counts as read if it appears anywhere outside the
                    # single line that declares it.
                    if len(re.findall(rf"\b{re.escape(field)}\b", source)) < 2:
                        unreferenced.append(f"{attr}.{field}")

        assert not unreferenced, (
            "accepted but never read: " + ", ".join(sorted(unreferenced))
        )


class TestUnimplementedAreasAreHonestGaps:
    """
    Standby, delayed reporting, reassignment and positioning are unimplemented.
    That is a documented absence, not a silent discard — the request models
    accept no parameters for them, so no caller can supply data the API then
    ignores.
    """

    @pytest.mark.parametrize(
        "keywords",
        [("standby",), ("delay", "report"), ("reassign",), ("position",)],
    )
    def test_no_parameters_are_accepted_for_them(self, keywords):
        from pydantic import BaseModel

        from app.models import calculation, validation

        fields = set()
        for module in (calculation, validation):
            for attr in dir(module):
                obj = getattr(module, attr)
                if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
                    fields |= set(obj.model_fields)

        accepted = [f for f in fields if any(k in f.lower() for k in keywords)]
        assert not accepted, (
            f"fields {accepted} suggest a rule area that is accepted but "
            f"not implemented"
        )


# ═══════════════════════════════════════════════════════════════════════
# Cross-appendix table pins
# ═══════════════════════════════════════════════════════════════════════

class TestAppendixTablePins:
    """Every appendix's table, checked against the served legislative text."""

    @pytest.mark.parametrize(
        "utc,expected",
        [
            ("2026-03-23T22:00:00Z", 10.0),   # 0600 local -> 0600-0759
            ("2026-03-24T00:00:00Z", 11.0),   # 0800 local -> 0800-1059
            ("2026-03-24T03:00:00Z", 10.0),   # 1100 local -> 1100-1359
            ("2026-03-24T06:00:00Z", 9.0),    # 1400 local -> 1400-2259
            ("2026-03-24T15:00:00Z", 8.0),    # 2300 local -> 2300-0459
        ],
    )
    def test_appendix_4_table(self, utc, expected):
        result = max_fdp("4", fdp_start_utc=utc, sectors=1)
        assert result["base_max_fdp_hours"] == pytest.approx(expected)

    def test_appendix_4_0500_band_is_served_and_implemented(self):
        """
        The 0500-0559 value was missing from the corpus — a PDF-to-markdown
        conversion artefact that dropped the cell, not a parser bug. Confirmed
        as 9 hours against the authoritative instrument and restored, so a user
        following a citation to the section text now sees the same figure the
        calculator uses.
        """
        text = client.get(f"{BASE}/sections/APPENDIX 4.2").json()["text"]
        assert "0500 – 0559 9" in text

        result = max_fdp("4", fdp_start_utc="2026-03-23T21:30:00Z", sectors=1)
        assert result["base_max_fdp_hours"] == pytest.approx(9.0)

    def test_every_table_value_traces_to_the_served_text(self):
        """
        Guards the whole class of dropped-cell defect: every number the rule
        tables can return must appear in the legislative text that grants it.
        """
        import re

        sections = {
            "1": ["APPENDIX 1.2"],
            "2": ["APPENDIX 2.2", "APPENDIX 2.3", "APPENDIX 2.5"],
            "3": ["APPENDIX 3.2"], "4": ["APPENDIX 4.2"], "4A": ["APPENDIX 4A.2"],
            "4B": ["APPENDIX 4B.1"], "5": ["APPENDIX 5.1"],
            "5A": ["APPENDIX 5A.2"], "6": ["APPENDIX 6.2"],
        }
        for appendix, ids in sections.items():
            text = "".join(
                client.get(f"{BASE}/sections/{sid}").json().get("text", "")
                for sid in ids
            )
            numbers = set(re.findall(r"\b\d+(?:\.5)?\b", text))
            for table in FDP_CONFIGS[appendix].tables.values():
                for row in table.rows:
                    for key, value in row.sectors.items():
                        assert f"{value:g}" in numbers, (
                            f"Appendix {appendix} {table.table_id} "
                            f"{row.time_band.label}/{key} = {value:g} does not "
                            f"appear in the served legislative text"
                        )

    def test_appendix_4_has_no_blanket_flight_time_limit(self):
        """§2.2 governs flight training in the first 7 hours — a different rule."""
        assert max_fdp("4", sectors=1)["flight_time_limit_hours"] is None

    @pytest.mark.parametrize(
        "single_pilot,utc,expected",
        [
            (False, "2026-03-23T23:00:00Z", 14.0),   # 0700 local, multi 1-2 sectors
            (True, "2026-03-23T23:00:00Z", 12.0),    # 0700 local, single pilot
            (False, "2026-03-24T08:00:00Z", 11.0),   # 1600 local -> 1600-0459
        ],
    )
    def test_appendix_4b_table(self, single_pilot, utc, expected):
        result = max_fdp("4B", fdp_start_utc=utc, sectors=2, single_pilot=single_pilot)
        assert result["base_max_fdp_hours"] == pytest.approx(expected)

    @pytest.mark.parametrize("appendix", APPENDICES)
    def test_every_appendix_calculates(self, appendix):
        result = max_fdp(appendix, sectors=1)
        assert result["final_max_fdp_hours"] > 0
        assert result["violations"] == []

    @pytest.mark.parametrize("appendix", APPENDICES)
    def test_every_appendix_validates(self, appendix):
        body = {
            "appendix": appendix,
            "fdp_start_utc": "2026-03-23T23:00:00Z",   # 0700 local
            "fdp_end_utc": "2026-03-24T03:00:00Z",     # 4h
            "local_time_offset_hours": 8,
            "sectors": 1,
        }
        if appendix == "2":
            body["acclimatisation"] = {
                "state": "acclimatised", "acclimatised_time_offset_hours": 8,
            }
        response = client.post(f"{BASE}/validate/fdp", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["valid"] is True, response.json()["violations"]

    @pytest.mark.parametrize("appendix", APPENDICES)
    def test_every_appendix_calculates_an_odp(self, appendix):
        response = client.post(
            f"{BASE}/calculate/min-off-duty",
            json={
                "appendix": appendix,
                "preceding_fdp": {
                    "start_utc": "2026-03-24T00:00:00Z",
                    "end_utc": "2026-03-24T10:00:00Z",
                    "duration_hours": 10,
                    "location": "away",
                },
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["final_min_odp_hours"] > 0
        assert body["clause"], f"Appendix {appendix} ODP has no clause"

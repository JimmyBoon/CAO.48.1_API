"""
Contract tests for GET /guide (S14).

The spec's motivating failure: "On the CAO 48.1 build the guide documented a
parameter set the API no longer accepted." Parameter lists are now generated
from the running request models, so they cannot drift. These tests hold the
parts that are still hand-written — prose and examples — to the same standard.
"""

import re

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.config import settings
from app.data.guide import build_guide
from app.data.guide_params import parameter_names
from app.main import app
from app.models import calculation, validation

client = TestClient(app)
BASE = "/api/v1/cao481"


@pytest.fixture(scope="module")
def guide():
    response = client.get(f"{BASE}/guide")
    assert response.status_code == 200
    return response.json()


def _all_model_fields() -> set[str]:
    names: set[str] = set()
    for module in (calculation, validation):
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
                names |= set(obj.model_fields)
    return names


# Tokens that look like field names but are not: path parameters, and the
# literal values of discriminated-union tags.
_NOT_PARAMETERS = {"section_id", "off_duty", "rest_day"}

_SNAKE_CASE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b")


class TestParameterContract:
    """Every parameter the guide names must exist; every required field must appear."""

    def test_parameters_are_generated_not_handwritten(self, guide):
        posts = [e for e in guide["endpoints"] if e["method"] == "POST"]
        assert posts
        for endpoint in posts:
            assert endpoint.get("parameters_generated_from"), endpoint["path"]

    @pytest.mark.parametrize(
        "path,model_name",
        [
            ("/calculate/max-fdp", "MaxFdpRequest"),
            ("/calculate/min-off-duty", "MinOffDutyRequest"),
            ("/validate/fdp", "ValidateFdpRequest"),
            ("/validate/off-duty", "ValidateOffDutyRequest"),
            ("/validate/cumulative", "ValidateCumulativeRequest"),
            ("/validate/sequence", "ValidateSequenceRequest"),
            ("/validate/roster", "ValidateRosterRequest"),
        ],
    )
    def test_every_documented_parameter_exists_on_the_model(self, guide, path, model_name):
        endpoint = next(e for e in guide["endpoints"] if e["path"] == path)
        model = getattr(validation, model_name, None) or getattr(calculation, model_name)
        real = parameter_names(model)
        for parameter in endpoint["parameters"]:
            assert parameter["name"] in real, (
                f"{path} documents {parameter['name']!r}, which is not a field "
                f"on {model_name}"
            )

    @pytest.mark.parametrize(
        "path,model_name",
        [
            ("/calculate/max-fdp", "MaxFdpRequest"),
            ("/validate/fdp", "ValidateFdpRequest"),
            ("/validate/roster", "ValidateRosterRequest"),
        ],
    )
    def test_every_required_field_appears_in_the_guide(self, guide, path, model_name):
        endpoint = next(e for e in guide["endpoints"] if e["path"] == path)
        model = getattr(validation, model_name, None) or getattr(calculation, model_name)
        documented = {p["name"] for p in endpoint["parameters"]}
        for name, field in model.model_fields.items():
            if field.is_required():
                assert name in documented, f"{path} omits required field {name!r}"

    def test_prose_names_no_parameter_the_api_does_not_accept(self, guide):
        """
        Catches the original drift: the guide told integrators about
        local_start_time_of_day_hours, preceding_fdp_hours, augmented_crew_size
        and crosses_wocl long after the API stopped accepting them.
        """
        known = _all_model_fields() | _NOT_PARAMETERS
        offenders: list[str] = []

        def scan(where: str, text: str) -> None:
            for token in _SNAKE_CASE.findall(text or ""):
                if token not in known:
                    offenders.append(f"{where}: {token}")

        for endpoint in guide["endpoints"]:
            for key in ("summary", "purpose", "when_to_use", "when_not_to_use"):
                scan(endpoint["path"], endpoint.get(key, ""))
            for mistake in endpoint.get("common_mistakes", []):
                scan(endpoint["path"], mistake)
        for note in guide["important_notes"]:
            scan("important_notes", note)

        assert not offenders, "guide prose names non-existent parameters: " + "; ".join(offenders)

    def test_retired_parameter_names_are_gone(self, guide):
        body = str(guide)
        for retired in (
            "local_start_time_of_day_hours",
            "augmented_crew_size",
            "preceding_fdp_hours",
            "split_duty_rest_hours",
            "not_acclimatised",
        ):
            assert retired not in body, f"guide still mentions {retired!r}"


class TestExamplesExecute:
    """Every worked example must actually work."""

    def test_every_example_request_succeeds(self, guide):
        failures = []
        for endpoint in guide["endpoints"]:
            example = endpoint.get("example_request")
            if not example:
                continue
            if endpoint["method"] == "GET":
                response = client.get(f"{BASE}{example.get('path', endpoint['path'])}")
            else:
                response = client.post(
                    f"{BASE}{endpoint['path']}", json=example.get("body", example)
                )
            if response.status_code != 200:
                failures.append(
                    f"{endpoint['method']} {endpoint['path']} -> "
                    f"{response.status_code}: {response.text[:200]}"
                )
        assert not failures, "\n".join(failures)

    def test_post_examples_come_from_the_models(self, guide):
        for endpoint in guide["endpoints"]:
            if endpoint["method"] != "POST":
                continue
            model_name = endpoint["parameters_generated_from"]
            model = getattr(validation, model_name, None) or getattr(calculation, model_name)
            examples = (model.model_config.get("json_schema_extra") or {}).get("examples")
            assert examples
            assert endpoint["example_request"] == examples[0]


class TestVersionsAndReferenceData:

    def test_all_version_strings_match_the_running_version(self, guide):
        assert guide["version"] == settings.app_version
        stale = re.findall(r'"version": "(\d+\.\d+\.\d+)"', str(guide))
        for version in stale:
            assert version == settings.app_version, (
                f"guide contains stale version string {version!r}"
            )

    def test_section_id_examples_use_the_accepted_format(self, guide):
        """
        The old common_mistakes actively taught the wrong format, telling
        integrators to use 'appendix-3' when 'APPENDIX 3' is correct.
        """
        entry = next(e for e in guide["endpoints"] if e["path"] == "/sections/{section_id}")

        # The lower-cased form may appear only where the guide warns against
        # it, never in an example or a parameter description offered as correct.
        assert "appendix-3" not in str(entry["example_request"])
        assert "appendix-3" not in str(entry.get("example_response_shape", ""))
        for parameter in entry["parameters"]:
            assert "appendix-3" not in parameter["description"]
        for mistake in entry["common_mistakes"]:
            if "appendix-3" in mistake:
                assert "NOT accepted" in mistake, (
                    "the wrong format may only appear as a warning"
                )

        assert client.get(f"{BASE}{entry['example_request']['path']}").status_code == 200

    def test_cumulative_example_uses_real_window_definitions(self, guide):
        """
        Appendix 3 has 28d/365d flight time and 168h/336h duty time — no 90d
        window, and no 28d duty window. The guide advertised
        `flight_time.days_90` and `duty_time.days_28`, neither of which exists.
        """
        entry = next(
            e for e in guide["endpoints"] if e["path"] == "/limits/cumulative/{appendix}"
        )
        shape = entry["example_response_shape"]
        assert "period_90d_hours" not in shape["flight_time"]
        assert set(shape["duty_time"]) == {"period_168h_hours", "period_336h_hours"}
        assert "days_90" not in str(shape) and "days_28" not in str(shape)

        live = client.get(f"{BASE}/limits/cumulative/3").json()
        assert shape["flight_time"]["period_28d_hours"] == (
            live["flight_time"]["period_28d_hours"]
        )

    def test_every_documented_response_key_is_live(self, guide):
        """
        Broad sweep: for every endpoint whose example can be executed, no key
        in example_response_shape may be absent from the real response.
        """
        for endpoint in guide["endpoints"]:
            shape = endpoint.get("example_response_shape")
            example = endpoint.get("example_request")
            if not isinstance(shape, dict):
                continue
            if endpoint["method"] == "GET":
                path = (example or {}).get("path", endpoint["path"])
                if "{" in path:
                    continue
                response = client.get(f"{BASE}{path}")
            else:
                if not example:
                    continue
                response = client.post(
                    f"{BASE}{endpoint['path']}", json=example.get("body", example)
                )
            if response.status_code != 200:
                continue
            extra = set(shape) - set(response.json())
            assert not extra, (
                f"{endpoint['path']} documents {sorted(extra)}, absent from the "
                f"real response"
            )

    def test_response_shapes_are_generated(self, guide):
        """
        Response examples drifted as far as the request ones: max-fdp
        advertised max_fdp_hours, time_band, crosses_wocl and is_early_start,
        none of which the response carries.
        """
        generated = [
            e for e in guide["endpoints"] if e.get("response_generated_from")
        ]
        assert len(generated) >= 9

        # Compare KEYS, not substrings: `base_max_fdp_hours` legitimately
        # contains `max_fdp_hours`.
        retired = {
            "max_fdp_hours", "is_early_start", "min_off_duty_hours",
            # `notes` is NOT retired — FdpTableResponse really has one.
            "time_band", "crosses_wocl", "fdp_duration_hours",
            "actual_duration_hours", "min_required_hours", "limits", "totals",
        }
        for endpoint in generated:
            shape = endpoint["example_response_shape"]
            if not isinstance(shape, dict):
                continue
            offending = retired & set(shape)
            assert not offending, (
                f"{endpoint['path']} still advertises {sorted(offending)}"
            )

    def test_documented_response_keys_all_exist(self, guide):
        """Every documented top-level response key is a real field."""
        import app.models.calculation as calc
        import app.models.validation as val
        import app.models.limits as lim

        for endpoint in guide["endpoints"]:
            name = endpoint.get("response_generated_from")
            if not name:
                continue
            model = (
                getattr(val, name, None) or getattr(calc, name, None)
                or getattr(lim, name, None)
            )
            if model is None:
                continue
            shape = endpoint["example_response_shape"]
            if not isinstance(shape, dict):
                continue
            for key in shape:
                assert key in model.model_fields, (
                    f"{endpoint['path']} documents response key {key!r}, "
                    f"absent from {name}"
                )

    def test_limits_example_matches_the_live_table(self, guide):
        entry = next(
            e for e in guide["endpoints"] if e["path"] == "/limits/fdp-table/{appendix}"
        )
        example_row = entry["example_response_shape"]["rows"][0]
        live = client.get(f"{BASE}/limits/fdp-table/3").json()
        assert example_row["sectors"].keys() == live["rows"][0]["sectors"].keys()

    def test_appendix_flags_match_the_rule_tables(self, guide):
        from app.data.fdp_tables import FDP_CONFIGS

        for entry in guide["appendices"]:
            config = FDP_CONFIGS[entry["id"]]
            assert entry["has_wocl_rules"] == bool(
                config.wocl_early_start and config.early_starts.available
            )
            assert entry["has_augmented_crew"] == (
                "augmented_acclimatised" in config.tables
            )

    def test_appendix_4b_night_limits_are_recorded(self, guide):
        """§8 Limit on late-night operations — previously asserted absent."""
        entry = next(a for a in guide["appendices"] if a["id"] == "4B")
        assert entry["has_night_operation_limits"] is True
        assert entry["night_operation_limits_section"] == "APPENDIX 4B.8"


class TestSectionAddressability:
    """S17 — every clause the API can cite must be fetchable."""

    def test_split_duty_clauses_now_resolve(self):
        for section_id in (
            "APPENDIX 2.4", "APPENDIX 3.3", "APPENDIX 4.3", "APPENDIX 4A.3",
            "APPENDIX 4B.2", "APPENDIX 5.2", "APPENDIX 6.3",
        ):
            response = client.get(f"{BASE}/sections/{section_id}")
            assert response.status_code == 200, f"{section_id} does not resolve"
            assert "split duty" in response.json()["title"].lower()

    def test_appendix_3_split_duty_text_is_served(self):
        body = client.get(f"{BASE}/sections/APPENDIX 3.3").json()
        assert "Subject to subclause 3.4" in body["text"]

    def test_no_gaps_in_section_numbering(self):
        """
        Appendices only. Part 1 of the instrument genuinely has no sections 2
        or 3 — the corpus is faithful there, and a gap in the source is not a
        chunking artefact.
        """
        listing = client.get(f"{BASE}/sections").json()
        for group in listing["groups"]:
            if not group["id"].startswith("APPENDIX"):
                continue
            numbers = []
            for section in group.get("sections", []):
                match = re.match(r"^(\d+)", section["id"].split(".")[-1])
                if match:
                    numbers.append(int(match.group(1)))
            if not numbers:
                continue
            missing = [n for n in range(1, max(numbers) + 1) if n not in numbers]
            assert not missing, f"{group['id']} is missing sections {missing}"

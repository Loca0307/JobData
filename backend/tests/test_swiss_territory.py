import pytest

from app.core.swiss_territory import (
    country_code_from_evidence,
    infer_swiss_country_code,
    normalize_country_code,
)


@pytest.mark.parametrize(
    "location",
    [
        "Zürich",
        "Geneva",
        "Remote - Switzerland",
        "Lausanne, Suisse",
        "Example Street 1, 8000, Zürich, CH",
        "Zurich, London",
    ],
)
def test_swiss_location_evidence_is_recognized(location: str):
    assert infer_swiss_country_code(location) == "CH"


@pytest.mark.parametrize(
    "location",
    [None, "", "London", "Busan", "Shanghai", "Remote", "Remote - Europe"],
)
def test_unknown_or_foreign_location_text_is_not_guessed(location: str | None):
    assert infer_swiss_country_code(location) is None


def test_structured_country_takes_precedence_over_location_text():
    assert country_code_from_evidence("Zürich", structured_country="GB") == "GB"
    assert (
        country_code_from_evidence("Zürich", structured_country="United Kingdom")
        is None
    )


@pytest.mark.parametrize("value", ["CH", "ch", "CHE", "Switzerland", "Schweiz"])
def test_structured_swiss_country_values_are_normalized(value: str):
    assert normalize_country_code(value) == "CH"

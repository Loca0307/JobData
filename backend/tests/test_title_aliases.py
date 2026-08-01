import json

import pytest

from app.analysis.demand_map import build_demand_map, matches_role
from app.analysis.models import IndexedJobLocation
from app.analysis.title_aliases import (
    expand_search_title,
    load_title_alias_groups,
)


def test_catalog_contains_thirty_complete_job_families():
    groups = load_title_alias_groups()

    assert len(groups) == 30
    assert len({group.key for group in groups}) == 30
    assert all(group.english_terms and group.aliases for group in groups)


@pytest.mark.parametrize(
    "title",
    [
        "Plumber",
        "SANITÄRINSTALLATEURIN EFZ (80–100%)",
        "  Installatrice   sanitaire  ",
        "Idraulico / manutentore",
    ],
)
def test_plumber_aliases_expand_to_the_same_english_term(title: str):
    search_title = expand_search_title(title)

    assert matches_role("plumber", search_title)
    assert title in search_title


def test_multilingual_titles_return_the_same_eligible_job_set():
    jobs = [
        IndexedJobLocation(
            title=title,
            search_title=expand_search_title(title),
            location=location,
        )
        for title, location in (
            ("Plumber", "Zürich"),
            ("Sanitärinstallateurin EFZ", "Bern"),
            ("Plombière", "Genève"),
            ("Installatore sanitario", "Lugano"),
        )
    ]

    result = build_demand_map("plumb", jobs)

    assert result.matching_jobs == 4
    assert {point.name for point in result.points} == {
        "Bern",
        "Geneva",
        "Lugano",
        "Zürich",
    }


def test_aliases_match_whole_phrases_not_substrings():
    assert "plumber" not in expand_search_title("Lead Idraulicosystems Engineer")


def test_multi_role_title_receives_terms_from_every_family():
    expanded = expand_search_title("Elektriker und Sanitärinstallateur")

    assert matches_role("electrician", expanded)
    assert matches_role("plumber", expanded)


def test_unknown_title_keeps_literal_search_fallback():
    title = "Chief Happiness Astronaut"

    expanded = expand_search_title(title)

    assert expanded == title
    assert matches_role("happiness", expanded)


def test_catalog_rejects_missing_language(tmp_path):
    catalog = tmp_path / "aliases.json"
    catalog.write_text(
        json.dumps(
            [
                {
                    "key": "example",
                    "english_terms": ["example"],
                    "aliases": {
                        "de": ["Beispiel"],
                        "en": ["example"],
                        "fr": ["exemple"],
                    },
                }
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="exactly de, en, fr, and it"):
        load_title_alias_groups(catalog)


def test_catalog_rejects_alias_shared_by_different_families(tmp_path):
    catalog = tmp_path / "aliases.json"
    aliases = {language: ["shared"] for language in ("de", "en", "fr", "it")}
    catalog.write_text(
        json.dumps(
            [
                {"key": "one", "english_terms": ["one"], "aliases": aliases},
                {"key": "two", "english_terms": ["two"], "aliases": aliases},
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="is shared by one and two"):
        load_title_alias_groups(catalog)

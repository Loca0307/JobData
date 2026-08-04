import json

import pytest

from app.scrapers.ats.targets import (
    GreenhouseTarget,
    LeverTarget,
    load_company_target_catalog,
)


def write_catalog(path, targets: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"targets": targets}), encoding="utf-8")


def greenhouse_target(**updates: object) -> dict[str, object]:
    target: dict[str, object] = {
        "id": "example-greenhouse",
        "company_name": "Example Greenhouse AG",
        "careers_url": "https://example.test/careers",
        "ats": "greenhouse",
        "board_token": "example",
    }
    target.update(updates)
    return target


def lever_target(**updates: object) -> dict[str, object]:
    target: dict[str, object] = {
        "id": "example-lever",
        "company_name": "Example Lever AG",
        "careers_url": "https://example.test/jobs",
        "ats": "lever",
        "site": "example",
        "region": "eu",
    }
    target.update(updates)
    return target


def test_catalog_loads_empty_and_supported_targets(tmp_path):
    empty_path = tmp_path / "empty.json"
    write_catalog(empty_path, [])
    assert load_company_target_catalog(empty_path).targets == []

    path = tmp_path / "targets.json"
    write_catalog(path, [greenhouse_target(), lever_target()])
    catalog = load_company_target_catalog(path)

    assert isinstance(catalog.targets[0], GreenhouseTarget)
    assert isinstance(catalog.targets[1], LeverTarget)
    assert [target.source_name for target in catalog.targets] == [
        "company:example-greenhouse",
        "company:example-lever",
    ]


@pytest.mark.parametrize(
    "targets",
    [
        [greenhouse_target(), greenhouse_target(company_name="Duplicate")],
        [greenhouse_target(id="Bad ID")],
        [greenhouse_target(careers_url="not-a-url")],
        [greenhouse_target(board_token="bad/token")],
        [lever_target(site="bad/site")],
        [lever_target(region="us")],
        [greenhouse_target(ats="workday")],
    ],
)
def test_catalog_rejects_invalid_targets(tmp_path, targets):
    path = tmp_path / "invalid.json"
    write_catalog(path, targets)

    with pytest.raises(ValueError, match="company target|Duplicate"):
        load_company_target_catalog(path)

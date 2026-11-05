"""Parser golden tests against the committed raw snapshot."""

import json

import pytest

from build_dataset import ROOT, SEASONS, build, service_minutes
from promote import validate


@pytest.fixture(scope="module")
def built():
    dataset, errors = build("fall2026")
    return dataset, errors


def test_strict_build_has_no_errors(built):
    _, errors = built
    assert errors == []


def test_service_minutes_carry_past_midnight():
    assert service_minutes(["11:45 PM", "12:05 AM"]) == [1425, 1445]
    assert service_minutes(["12:45 AM", "1:05 AM"]) == [1485, 1505]
    assert service_minutes(["7:00 AM", "7:30 AM"]) == [420, 450]
    assert service_minutes(["7:00 AM", "x"]) is None


def test_dataset_shape(built):
    ds, _ = built
    assert len(ds["lines"]) == 13
    assert sum(len(l["trips"]) for l in ds["lines"]) > 400
    assert ds["meta"]["effective_from"] == SEASONS["fall2026"]["effective_from"]
    for ln in ds["lines"]:
        for t in ln["trips"]:
            mins = [x["min"] for x in t["times"]]
            assert mins == sorted(mins)
            assert all(x["stop"] in ds["stops"] for x in t["times"])
            assert t["days"]


def test_late_nite_is_friday_saturday_service_after_midnight(built):
    ds, _ = built
    ws = next(l for l in ds["lines"] if l["id"] == "ws")
    ln = [t for t in ws["trips"] if t["direction"] == "ln-out"]
    assert ln and all(t["days"] == ["Fri", "Sat"] and t["times"][0]["min"] >= 1440 for t in ln)
    weekday_after_midnight = [t for t in ws["trips"] if t["direction"] == "reg-in" and t["times"][0]["time"] == "12:03 AM"]
    assert {tuple(t["days"]) for t in weekday_after_midnight} == {("Mon", "Tue", "Wed", "Thu", "Fri"), ("Sat",)}


def test_skip_stops_and_aliases(built):
    ds, _ = built
    dcl = next(l for l in ds["lines"] if l["id"] == "dcl")
    assert any(t.get("skip_stops") == ["university_union"] for t in dcl["trips"])
    assert any("hinman_academic_a" in t.get("skip_stops", []) for t in dcl["trips"])
    assert "saint_charles_street" in ds["stops"]
    assert "Campus" in ds["stops"]["hinman_academic_a"]["aliases"]
    assert "univ_union" not in ds["stops"] and "hawley_and_court_streets" not in ds["stops"]


def test_campus_shuttle_frequency_and_express_variants(built):
    ds, _ = built
    cs = next(l for l in ds["lines"] if l["id"] == "cs")
    hours = {f["key"]: (f["start_min"], f["end_min"]) for f in cs["frequency"]}
    assert hours == {"outer-loop": (420, 1260), "inner-loop": (450, 1080)}
    de = next(l for l in ds["lines"] if l["id"] == "de")
    assert len(de["directions"]) == 2
    assert {tuple(t["days"]) for t in de["trips"]} == {("Fri",), ("Sat",)}


def test_candidate_passes_promotion_validation(built):
    ds, _ = built
    calendar = json.loads((ROOT / "data" / "service_calendar.json").read_text())
    assert validate(ds, calendar) == []

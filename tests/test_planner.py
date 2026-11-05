"""Planner behaviour with frozen query times (all America/New_York)."""

from datetime import datetime

import pytest

from planner import TZ, Planner, _pareto

UNION, UDC, HAWLEY = "University Union", "University Downtown Center", "State & Hawley Streets"


@pytest.fixture(scope="module")
def planner() -> Planner:
    return Planner()


def at(y, mo, d, h, mi=0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


def plan(planner, origin, dest, when, **kw):
    o, d = planner.resolve_place(origin), planner.resolve_place(dest)
    assert o and d, (origin, dest)
    return planner.plan(o[0], d[0], when=when, origin_label=origin, destination_label=dest, **kw)


def rides(journey):
    return [l for l in journey["legs"] if l["type"] == "ride"]


def iso_min(stamp):
    dt = datetime.fromisoformat(stamp["iso"])
    return dt.hour * 60 + dt.minute


# -- basics -------------------------------------------------------------------
def test_weekday_direct_campus_to_downtown(planner):
    res = plan(planner, UNION, UDC, at(2026, 11, 4, 8, 0))  # Wednesday
    assert res["service_day"] == {**res["service_day"], "profile": "regular", "status": "confirmed"}
    assert res["journeys"], res["message"]
    first = res["journeys"][0]
    assert first["transfers"] == 0 and len(rides(first)) == 1
    ride = rides(first)[0]
    assert ride["line_id"] in {"udc", "dcl", "ws", "ms"}
    assert iso_min(first["depart"]) >= 8 * 60
    assert first["arrive"]["iso"] > first["depart"]["iso"]
    assert ride["board"]["estimated"] is False  # Union is a published timepoint
    assert not res["warnings"]


def test_journeys_are_pareto_optimal_and_sorted(planner):
    res = plan(planner, UNION, UDC, at(2026, 11, 4, 8, 0))
    js = res["journeys"]
    arrivals = [datetime.fromisoformat(j["arrive"]["iso"]) for j in js]
    assert arrivals == sorted(arrivals)
    for j in js:
        j["depart_min"], j["arrive_min"] = iso_min(j["depart"]), iso_min(j["arrive"])
    assert len(_pareto(js)) == len(js)


# -- Late Nite / service-day semantics ------------------------------------------
def test_friday_night_query_finds_saturday_morning_late_nite(planner):
    res = plan(planner, UNION, HAWLEY, at(2026, 11, 6, 23, 40))  # Friday
    late = [j for j in res["journeys"] if j["late_nite"]]
    assert late, [j["legs"] for j in res["journeys"]]
    ride = rides(late[0])[0]
    assert ride["tier"] == "latenite"
    assert late[0]["depart"]["same_day"] is False and late[0]["depart"]["day"] == "Sat"


def test_saturday_small_hours_still_friday_night_service(planner):
    res = plan(planner, UNION, HAWLEY, at(2026, 11, 7, 0, 30))  # Saturday 00:30
    late = [j for j in res["journeys"] if j["late_nite"]]
    assert late
    assert late[0]["depart"]["same_day"] is True
    assert iso_min(late[0]["depart"]) < 3 * 60


def test_sunday_small_hours_is_saturday_night_service(planner):
    res = plan(planner, UNION, HAWLEY, at(2026, 11, 8, 0, 30))
    assert any(j["late_nite"] for j in res["journeys"])


def test_tuesday_small_hours_has_no_late_nite(planner):
    res = plan(planner, UNION, HAWLEY, at(2026, 11, 10, 0, 30))
    assert not any(j["late_nite"] for j in res["journeys"])
    assert all(iso_min(j["depart"]) >= 6 * 60 for j in res["journeys"])


def test_holiday_friday_removes_saturday_morning_late_nite(planner):
    # Fri Nov 27 2026 is a (provisional) no-service day: the 12:45 AM "Saturday" run belongs to it.
    res = plan(planner, UNION, HAWLEY, at(2026, 11, 27, 23, 50))
    assert res["journeys"] == [] and "No OCCT service" in res["message"]
    res2 = plan(planner, UNION, HAWLEY, at(2026, 11, 28, 0, 30))
    assert res2["journeys"] == []
    assert any(w.startswith("provisional_calendar") for w in res["warnings"])


# -- calendar -------------------------------------------------------------------
def test_thanksgiving_no_service_with_reason(planner):
    res = plan(planner, UNION, UDC, at(2026, 11, 26, 12, 0))
    assert res["journeys"] == []
    assert "Thanksgiving" in res["message"]
    assert res["service_day"]["profile"] == "none"


def test_fall_break_only_ics_runs(planner):
    res = plan(planner, "Mohawk", "Innovative Technologies Complex (ITC)", at(2026, 10, 14, 9, 0))
    assert res["journeys"] and all(r["line_id"] == "ics" for j in res["journeys"] for r in rides(j))
    assert res["service_day"]["status"] == "confirmed"
    res2 = plan(planner, UNION, UDC, at(2026, 10, 14, 9, 0))
    assert res2["journeys"] == []
    assert "ITC" in res2["message"]
    assert res2["untimed_services"] == []


def test_calendar_lookup_precedence(planner):
    cal = planner.calendar
    assert cal.lookup(datetime(2026, 10, 12).date())["profile"] == "interim"
    assert cal.lookup(datetime(2026, 10, 19).date())["profile"] == "regular"
    assert cal.lookup(datetime(2026, 11, 26).date())["status"] == "provisional"
    assert cal.lookup(datetime(2030, 1, 1).date())["status"] == "unknown"


# -- loops, skips, transfers, arrive-by ---------------------------------------------
def test_loop_route_from_terminus_and_back(planner):
    out = plan(planner, UNION, "Wegmans", at(2026, 11, 7, 13, 0))
    assert any(r["line_id"] == "oc" and r["board"]["name"] == UNION for j in out["journeys"] for r in rides(j))
    back = plan(planner, "Wegmans", UNION, at(2026, 11, 7, 13, 0))
    r = next(r for j in back["journeys"] for r in rides(j) if r["line_id"] == "oc")
    assert r["board"]["name"] == "Wegmans" and r["alight"]["name"] == UNION
    assert r["alight"]["min"] > r["board"]["min"]


def test_skips_acad_a_trip_never_serves_hinman(planner):
    ds = planner.datasets[-1]
    pat = next(p for p in ds.patterns if p.line_id == "ws" and p.dir_key == "reg-in")
    hin = pat.stops.index("hinman_academic_a")
    skipping = [t for t in pat.trips if "hinman_academic_a" in t.skip_stops]
    assert skipping
    assert all(t.times[hin] is None for t in skipping)
    res = plan(planner, UDC, "Hinman / Academic A", at(2026, 11, 10, 10, 35))
    for j in res["journeys"]:
        for r in rides(j):
            if r["line_id"] == "ws" and r["board"]["time"] == "10:40 AM":
                assert r["alight"]["name"] != "Hinman / Academic A"


def test_one_transfer_journey_respects_buffer(planner):
    res = plan(planner, "Oakdale Commons", UDC, at(2026, 11, 7, 14, 0))
    with_xfer = [j for j in res["journeys"] if j["transfers"] == 1]
    assert with_xfer, res["message"]
    j = with_xfer[0]
    legs = j["legs"]
    first = next(i for i, l in enumerate(legs) if l["type"] == "ride")
    second = next(i for i, l in enumerate(legs) if l["type"] == "ride" and i > first)
    walk_between = sum(l["minutes"] for l in legs[first + 1:second] if l["type"] == "walk")
    assert legs[second]["board"]["min"] >= legs[first]["alight"]["min"] + (walk_between or 2)


def test_arrive_by_returns_latest_departure_that_makes_it(planner):
    res = plan(planner, UNION, UDC, at(2026, 11, 10, 9, 0), mode="arrive")
    assert res["journeys"]
    assert all(datetime.fromisoformat(j["arrive"]["iso"]) <= at(2026, 11, 10, 9, 0) for j in res["journeys"])
    departs = [datetime.fromisoformat(j["depart"]["iso"]) for j in res["journeys"]]
    assert departs == sorted(departs, reverse=True)
    assert departs[0] >= at(2026, 11, 10, 8, 30)


# -- walking, untimed loops, DST, stale data --------------------------------------------
def test_short_trip_is_walk_only_first(planner):
    res = plan(planner, "Bartle Library", "Lecture Hall", at(2026, 11, 4, 10, 0))
    assert res["journeys"][0]["walk_only"] is True


def test_untimed_campus_shuttle_only_in_hours_on_weekdays(planner):
    wed = plan(planner, "Mountainview", "Bartle Library", at(2026, 11, 4, 14, 0))
    assert any(u["line_id"] == "cs" for u in wed["untimed_services"])
    assert all("ETA" in u["note"] or "timetable" in u["note"] for u in wed["untimed_services"])
    sat = plan(planner, "Mountainview", "Bartle Library", at(2026, 11, 7, 14, 0))
    assert sat["untimed_services"] == []
    late = plan(planner, "Mountainview", "Bartle Library", at(2026, 11, 4, 22, 0))
    assert late["untimed_services"] == []


@pytest.mark.parametrize("when", [at(2026, 11, 1, 1, 30), at(2027, 3, 14, 1, 30), at(2026, 11, 1, 2, 30)])
def test_dst_transition_nights_do_not_crash(planner, when):
    res = plan(planner, UNION, HAWLEY, when)
    assert isinstance(res["journeys"], list)
    for j in res["journeys"]:
        assert datetime.fromisoformat(j["arrive"]["iso"]) >= datetime.fromisoformat(j["depart"]["iso"])


def test_outside_dataset_range_warns(planner):
    before = plan(planner, UNION, UDC, at(2026, 6, 1, 10, 0))
    assert any(w.startswith("stale_data") for w in before["warnings"])
    far = plan(planner, UNION, UDC, at(2028, 1, 10, 10, 0))
    assert any(w.startswith("unknown_calendar") for w in far["warnings"])


def test_estimated_times_are_flagged(planner):
    res = plan(planner, UNION, "Murray Street", at(2026, 11, 4, 10, 0))
    assert res["journeys"]
    flags = [s["estimated"] for j in res["journeys"] for r in rides(j) for s in r["stops"]]
    assert True in flags and False in flags


def test_meta(planner):
    m = planner.meta(at(2026, 11, 5, 12, 0))
    assert m["dataset"]["label"] == "Fall 2026"
    assert m["today"]["profile"] == "regular" and m["today"]["status"] == "confirmed"
    assert m["alerts"] == [] and m["warnings"] == []


def test_meta_nudges_maintainers_before_data_goes_stale(planner):
    late = planner.meta(at(2027, 11, 15, 12, 0))
    kinds = {w.split(":")[0] for w in late["warnings"]}
    assert {"calendar_horizon", "dataset_age"} <= kinds

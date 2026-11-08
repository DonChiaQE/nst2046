"""The Appendix A divergence print.

`on_runway` is what shows the mechanism behind a divergent case, so it has to list the events the engine could
actually have used -- including a reservation held from the other end of the same strip.
"""
from scripts.divergent_cases import on_runway


def _row(events):
    return {"events": events}


def test_on_runway_lists_an_event_on_the_reciprocal_end():
    row = _row([[["LAND", "csa two", "31", None]]])
    assert on_runway(row, "13") == [(0, ["LAND", "csa two", "31", None])]


def test_on_runway_keeps_the_releases_whatever_runway_they_name():
    """A VACATED or HANDOFF releases a reservation, so it explains a disappearance even with no runway of its own."""
    row = _row([[["HANDOFF", "csa two", None, None]], [["LAND", "csa three", "24", None]]])
    assert on_runway(row, "13") == [(0, ["HANDOFF", "csa two", None, None])]

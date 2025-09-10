import pytest

from app.api.utils import route_kind, events_from_form


@pytest.mark.parametrize(
    "desc, raw, expected",
    [
        ("#мастер", "", "master"),
        ("", "текст #оператор", "operator"),
    ],
)
def test_route_kind_positive(desc, raw, expected):
    assert route_kind(desc=desc, raw=raw) == expected


@pytest.mark.parametrize(
    "desc",
    [
        "мастер",  # no hashtag
        "#мастерская",  # word continuation
        "#операторский",  # word continuation
        "a#оператор",  # preceding word char
    ],
)
def test_route_kind_negative(desc):
    assert route_kind(desc=desc) == "ignore"


def test_route_kind_master_priority():
    assert route_kind(desc="#оператор #мастер") == "master"


def test_events_from_form():
    form = {
        "leads[status][0][id]": "1",
        "leads[status][0][status_id]": "10",
        "leads[status][1][id]": "2",
        "leads[status][1][status_id]": "20",
    }
    assert events_from_form(form) == [(1, 10), (2, 20)]

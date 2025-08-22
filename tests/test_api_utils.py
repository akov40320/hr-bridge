import pytest

from app.api.utils import route_kind


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

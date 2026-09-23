from __future__ import annotations

import pytest

from sift.judging import profile as profiles


def test_parses_wants_and_dealbreakers() -> None:
    parsed = profiles.parse(
        {
            "name": "robots",
            "background": "my background",
            "want": [
                {"id": "reproducible", "requirement": "Reproducible experiments", "weight": 2}
            ],
            "dealbreaker": [{"id": "retracted", "requirement": "Retracted paper"}],
        }
    )

    assert [c.id for c in parsed.wants] == ["reproducible"]
    assert [c.id for c in parsed.dealbreakers] == ["retracted"]
    assert parsed.wants[0].weight == 2.0
    assert parsed.background == "my background"
    assert parsed.name == "robots"


def test_name_and_background_are_optional() -> None:
    parsed = profiles.parse({"want": [{"id": "x", "requirement": "r"}]})
    assert (parsed.name, parsed.background) == ("default", "")


@pytest.mark.parametrize("wishlist", [{"name": "  "}, {"name": 3}, {"background": ["a"]}])
def test_bad_name_or_background_is_rejected(wishlist: dict[str, object]) -> None:
    with pytest.raises(profiles.ProfileError):
        profiles.parse({**wishlist, "want": [{"id": "x", "requirement": "r"}]})


def test_settings_override_defaults() -> None:
    parsed = profiles.parse(
        {
            "want": [{"id": "reproducible", "requirement": "Reproducible experiments"}],
            "settings": {
                "merit_weight": 0.8,
                "dealbreaker_threshold": 0.9,
                "screen_threshold": 0.3,
            },
        }
    )

    assert parsed.merit_weight == 0.8
    assert parsed.dealbreaker_threshold == 0.9
    assert parsed.screen_threshold == 0.3


def test_empty_wishlist_is_rejected() -> None:
    with pytest.raises(profiles.ProfileError, match="no \\[\\[want\\]\\]"):
        profiles.parse({})


def test_duplicate_ids_are_rejected() -> None:
    with pytest.raises(profiles.ProfileError, match="duplicate"):
        profiles.parse(
            {
                "want": [{"id": "reproducible", "requirement": "a"}],
                "dealbreaker": [{"id": "reproducible", "requirement": "b"}],
            }
        )


def test_missing_requirement_is_rejected() -> None:
    with pytest.raises(profiles.ProfileError, match="requirement"):
        profiles.parse({"want": [{"id": "reproducible"}]})


def test_a_single_level_is_rejected() -> None:
    with pytest.raises(profiles.ProfileError, match="at least two levels"):
        profiles.parse({"want": [{"id": "x", "requirement": "r", "levels": ["only"]}]})


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "heavy"])
def test_invalid_weights(value: object) -> None:
    with pytest.raises(profiles.ProfileError):
        profiles.parse({"want": [{"id": "x", "requirement": "r", "weight": value}]})


def test_parses_toml_without_files() -> None:
    parsed = profiles.parse_toml(
        'background = "Robotics"\n[[want]]\nid = "robots"\nrequirement = "Robot learning"'
    )
    assert parsed.background == "Robotics"
    assert parsed.wants[0].id == "robots"


@pytest.mark.parametrize(
    "text", ["broken [", '[settings]\nmerit_weight = 2\n[[want]]\nid = "x"\nrequirement = "r"']
)
def test_bad_toml_profile(text: str) -> None:
    with pytest.raises(profiles.ProfileError):
        profiles.parse_toml(text)


def test_categories_say_where_papers_come_from() -> None:
    parsed = profiles.parse(
        {"categories": ["cs.AI", " cs.CL "], "want": [{"id": "x", "requirement": "r"}]}
    )
    assert parsed.categories == ("cs.AI", "cs.CL")


@pytest.mark.parametrize("categories", ["cs.AI", ["cs.AI", ""], ["cs.AI", 3], ["cs.AI", "cs.AI"]])
def test_bad_categories_are_rejected(categories: object) -> None:
    with pytest.raises(profiles.ProfileError):
        profiles.parse({"categories": categories, "want": [{"id": "x", "requirement": "r"}]})

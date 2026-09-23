"""Parse a research wishlist from data or TOML text, without reading files."""

import math
import tomllib
from collections.abc import Mapping

from .judgments import Criterion, Kind, Profile


class ProfileError(ValueError):
    """The wishlist is not usable."""


def _number(value: object, name: str, *, unit: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{name} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (unit and result > 1):
        raise ProfileError(
            f"{name} must be finite and {'between 0 and 1' if unit else 'nonnegative'}"
        )
    return result


def _criteria_of(kind: Kind, raw: object) -> list[Criterion]:
    if not isinstance(raw, (list, tuple)):
        raise ProfileError(f"{kind} must be a list of tables")
    criteria: list[Criterion] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ProfileError(f"{kind} entries must be tables")
        identifier, requirement = entry.get("id"), entry.get("requirement")
        if not isinstance(identifier, str) or not identifier.strip():
            raise ProfileError(f"{kind} needs a non-empty string id")
        if not isinstance(requirement, str) or not requirement.strip():
            raise ProfileError(f"{kind} '{identifier}' needs a non-empty requirement")
        levels = entry.get("levels", ())
        if not isinstance(levels, (list, tuple)):
            raise ProfileError(f"{kind} '{identifier}': levels must be a list")
        if levels and len(levels) < 2:
            raise ProfileError(f"{kind} '{identifier}': give at least two levels")
        if any(not isinstance(level, str) or not level.strip() for level in levels):
            raise ProfileError(f"{kind} '{identifier}': levels must be non-empty strings")
        criteria.append(
            Criterion(
                identifier,
                kind,
                requirement,
                _number(entry.get("weight", 1.0), "weight"),
                tuple(levels),
            )
        )
    return criteria


def _text(wishlist: Mapping[str, object], key: str, default: str) -> str:
    value = wishlist.get(key, default)
    if not isinstance(value, str):
        raise ProfileError(f"{key} must be a string")
    return value.strip()


def _categories(wishlist: Mapping[str, object]) -> tuple[str, ...]:
    raw = wishlist.get("categories", [])
    if not isinstance(raw, list) or not all(isinstance(c, str) and c.strip() for c in raw):
        raise ProfileError("categories must be a list of non-empty strings")
    categories = tuple(c.strip() for c in raw)
    if len(set(categories)) != len(categories):
        raise ProfileError("duplicate categories")
    return categories


def parse(wishlist: Mapping[str, object]) -> Profile:
    """A wishlist: an optional `name`, `background` and `categories`, criteria, and
    optional settings."""
    name = _text(wishlist, "name", "default")
    if not name:
        raise ProfileError("name cannot be empty")
    background = _text(wishlist, "background", "")
    categories = _categories(wishlist)
    criteria = _criteria_of("want", wishlist.get("want", ()))
    criteria += _criteria_of("dealbreaker", wishlist.get("dealbreaker", ()))
    if not criteria:
        raise ProfileError("the wishlist has no [[want]] or [[dealbreaker]] entries")
    ids = [criterion.id for criterion in criteria]
    if len(set(ids)) != len(ids):
        raise ProfileError("duplicate criterion ids")
    settings = wishlist.get("settings", {})
    if not isinstance(settings, dict):
        raise ProfileError("settings must be a table")
    defaults = {
        "merit_weight": 0.4,
        "dealbreaker_threshold": 0.7,
        "review_confidence": 0.5,
        "review_margin": 0.05,
        "screen_threshold": 0.5,
    }
    unknown = settings.keys() - defaults.keys()
    if unknown:
        raise ProfileError(f"unknown settings: {', '.join(sorted(unknown))}")
    values = {
        name: _number(settings.get(name, default), name, unit=True)
        for name, default in defaults.items()
    }
    return Profile(
        background=background,
        criteria=tuple(criteria),
        name=name,
        categories=categories,
        **values,
    )


def parse_toml(text: str) -> Profile:
    try:
        wishlist = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ProfileError(str(error)) from error
    return parse(wishlist)

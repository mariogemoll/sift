"""Reading the wishlist papers are harvested for and ranked against."""

from pathlib import Path

from sift.arxiv.announcements import valid_category
from sift.judging.judgments import Profile
from sift.judging.profile import ProfileError, parse_toml


def load(path: Path) -> Profile:
    """The wishlist at `path`; raises `ProfileError` if it is not usable.

    A service harvests the wishlist's categories, so it must name at least one,
    each in a shape arXiv's listing accepts.
    """
    profile = parse_toml(path.read_text(encoding="utf-8"))
    if not profile.categories:
        raise ProfileError(f"{path} names no categories to harvest")
    unknown = [category for category in profile.categories if not valid_category(category)]
    if unknown:
        raise ProfileError(f"{path}: not arXiv categories: {', '.join(unknown)}")
    return profile

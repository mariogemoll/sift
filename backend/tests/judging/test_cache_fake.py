from dataclasses import replace

import pytest

from sift.core import cache, scoring
from sift.core.judgments import Document, Profile
from sift.core.question_types import Choice, Noul, Score
from sift.judge import Ask, Asker, FakeAsker, ask_for


async def test_batch_contract_and_serialization(profile: Profile) -> None:
    asker: Asker = FakeAsker()
    asks = [ask_for(Document(str(i), f"Paper {i}"), profile) for i in range(4)]
    results = await asker(asks)
    assert len(results) == len(asks)
    assert list(await asker(list(reversed(asks)))) == list(reversed(results))
    assert await asker([]) == []
    for ask, result in zip(asks, results, strict=True):
        assert set(result.nouls) | set(result.scores) == set(ask.asked)
        assert cache.from_json(cache.to_json(result)) == result
        assert all(0 <= s.normalized <= 1 and s.max_level == 3 for s in result.scores.values())


async def test_all_question_types() -> None:
    ask = Ask(
        {"document": "text"},
        {
            "n": Noul("yes?"),
            "s": Score("how much?", ("no", "some", "much")),
            "c": Choice("which?", {"a": "first", "b": "second", "c": "third"}),
        },
    )
    result = (await FakeAsker()([ask]))[0]
    assert 0 <= result.nouls["n"] <= 1
    assert result.scores["s"].max_level == 2
    choice = result.choices["c"]
    assert sum(choice.probabilities.values()) == pytest.approx(1)
    assert choice.probabilities[choice.selected] == max(choice.probabilities.values())
    assert cache.from_json(cache.to_json(result)) == result


async def test_reweighting_reuses_judgments_without_inference(profile: Profile) -> None:
    document = Document("id", "A robotics paper")
    ask = ask_for(document, profile)
    stored = {cache.key_for(ask.state, ask.asked, model="fake"): (await FakeAsker()([ask]))[0]}
    reweighted = replace(
        profile,
        merit_weight=0.95,
        dealbreaker_threshold=0.99,
        criteria=tuple(replace(c, weight=10) for c in profile.criteria),
    )
    next_ask = ask_for(document, reweighted)
    reused = stored[cache.key_for(next_ask.state, next_ask.asked, model="fake")]
    assert (
        scoring.evaluate("id", reused, profile).total
        != scoring.evaluate("id", reused, reweighted).total
    )


def test_cache_covers_all_inputs(profile: Profile) -> None:
    ask = ask_for(Document("a", "text"), profile)
    original = cache.key_for(ask.state, ask.asked, model="m")
    assert original == cache.key_for(
        dict(reversed(list(ask.state.items()))),
        dict(reversed(list(ask.asked.items()))),
        model="m",
    )
    assert original != cache.key_for(ask.state, ask.asked, model="another")
    for changed in [
        ask_for(Document("a", "different"), profile),
        ask_for(Document("a", "text"), replace(profile, background="different")),
        ask_for(Document("a", "text"), replace(profile, criteria=profile.criteria[:1])),
        Ask(ask.state, {**ask.asked, "merit": Score("changed", ("a", "b"))}),
    ]:
        assert cache.key_for(changed.state, changed.asked, model="m") != original
    assert cache.key_for({}, {"q": Noul("same")}, model="m") != cache.key_for(
        {}, {"q": Score("same", ("a", "b"))}, model="m"
    )


def test_cache_covers_question_details() -> None:
    base = cache.key_for({}, {"q": Score("same", ("low", "high"))}, model="m")
    assert base != cache.key_for({}, {"q": Score("same", ("high", "low"))}, model="m")
    assert base != cache.key_for({}, {"renamed": Score("same", ("low", "high"))}, model="m")
    assert cache.key_for(
        {}, {"q": Choice("same", {"a": "A", "b": "B"})}, model="m"
    ) != cache.key_for({}, {"q": Choice("same", {"a": "changed", "b": "B"})}, model="m")


def test_core_and_fake_run_without_third_party_packages() -> None:
    import subprocess
    import sys
    from pathlib import Path

    source = Path(__file__).resolve().parents[2] / "src"
    script = f"""
import sys
sys.path.insert(0, {str(source)!r})
from sift.core import cache, profile, scoring
from sift.core.judgments import Document
from sift.judge import FakeAsker, ask_for
import asyncio
p = profile.parse_toml('[[want]]\\nid = "robots"\\nrequirement = "Robotics"')
ask = ask_for(Document('p', 'A robotics paper'), p)
judgment = asyncio.run(FakeAsker()([ask]))[0]
assert cache.from_json(cache.to_json(judgment)) == judgment
assert scoring.evaluate('p', judgment, p).document_id == 'p'
"""
    subprocess.run([sys.executable, "-S", "-c", script], check=True, capture_output=True)

"""The TypeSafe adapter against a stand-in for the service: no key, no network."""

import json
from collections.abc import Callable, Mapping

import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient, RetryPolicy

from sift.judging import Ask, AskFailed
from sift.judging.question_types import Choice, Noul, Score
from sift.judging.typesafe import TypeSafeAsker
from sift.retry import Retryable, Terminal

ASK = Ask(
    {"document": "A paper about retrieval.", "background": "IR research"},
    {
        "gate": Noul({"question": "Is it retracted?", "condition": "retracted"}),
        "fit": Score("How relevant?", ("not", "somewhat", "very")),
        "kind": Choice("Which kind?", {"theory": "A theory paper", "empirical": "Experiments"}),
    },
)

ANSWERS = {
    "gate": {"type": "noul", "noul": 0.12},
    "fit": {
        "type": "score",
        "score": 1.6,
        "confidence": 0.7,
        "legend": {"0": "not", "1": "somewhat", "2": "very"},
        "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7},
    },
    "kind": {
        "type": "choice",
        "choice": "empirical",
        "confidence": 0.8,
        "probabilities": {"theory": 0.2, "empirical": 0.8},
    },
}


def asker_answering(
    respond: Callable[[httpx2.Request], httpx2.Response],
) -> tuple[TypeSafeAsker, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return respond(request)

    sdk = AsyncTypeSafeClient(
        api_key="test-key",
        retry=RetryPolicy(max_retries=0),
        transport=httpx2.MockTransport(handle),
    )
    return TypeSafeAsker(sdk, "jev-1.13.0"), seen


def ok(answers: Mapping[str, object]) -> Callable[[httpx2.Request], httpx2.Response]:
    return lambda _: httpx2.Response(
        200,
        json={
            "model": "jev-1.13.0",
            "usage": {"input_tokens": 42, "output_tokens": 0},
            "answers": answers,
        },
    )


async def test_questions_go_out_typed_and_answers_come_back_typed() -> None:
    asker, seen = asker_answering(ok(ANSWERS))

    (judgments,) = await asker([ASK])

    body = json.loads(seen[0].content)
    assert body["model"] == "jev-1.13.0"
    assert body["state"] == dict(ASK.state)
    assert body["questions"]["gate"]["type"] == "noul"
    assert body["questions"]["fit"]["criteria"] == ["not", "somewhat", "very"]
    assert body["questions"]["kind"]["criteria"] == {
        "theory": "A theory paper",
        "empirical": "Experiments",
    }
    assert judgments.nouls == {"gate": 0.12}
    assert (judgments.scores["fit"].value, judgments.scores["fit"].max_level) == (1.6, 2)
    assert judgments.scores["fit"].confidence == 0.7
    assert judgments.choices["kind"].selected == "empirical"


async def test_one_request_per_ask_in_order() -> None:
    asker, seen = asker_answering(ok(ANSWERS))
    other = Ask({"document": "other"}, ASK.asked)

    results = await asker([ASK, other])

    assert len(results) == len(seen) == 2
    assert await asker([]) == []


async def test_an_unanswered_question_is_left_out_rather_than_guessed() -> None:
    asker, _ = asker_answering(ok({"gate": ANSWERS["gate"]}))

    (judgments,) = await asker([ASK])

    assert judgments.nouls == {"gate": 0.12}
    assert judgments.scores == {} and judgments.choices == {}


@pytest.mark.parametrize("status", [500, 502, 529, 408])
async def test_server_trouble_is_retryable(status: int) -> None:
    asker, _ = asker_answering(lambda _: httpx2.Response(status, json={"detail": "busy"}))

    with pytest.raises(AskFailed) as failed:
        await asker([ASK])

    assert isinstance(failed.value.failure, Retryable)


async def test_throttling_carries_the_wait_the_service_asked_for() -> None:
    asker, _ = asker_answering(
        lambda _: httpx2.Response(429, headers={"retry-after": "7"}, json={"detail": "slow down"})
    )

    with pytest.raises(AskFailed) as failed:
        await asker([ASK])

    assert failed.value.failure == Retryable(failed.value.failure.reason, retry_after=7.0)


@pytest.mark.parametrize("status", [400, 401, 403, 422])
async def test_a_refused_request_is_terminal(status: int) -> None:
    asker, _ = asker_answering(lambda _: httpx2.Response(status, json={"detail": "no"}))

    with pytest.raises(AskFailed) as failed:
        await asker([ASK])

    assert isinstance(failed.value.failure, Terminal)


async def test_a_broken_connection_is_retryable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    asker, _ = asker_answering(refuse)

    with pytest.raises(AskFailed) as failed:
        await asker([ASK])

    assert isinstance(failed.value.failure, Retryable)

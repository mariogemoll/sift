"""Pure cache keys and judgment serialization; persistence belongs to the caller."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .judgments import ChoiceValue, Judgments, ScoreValue
from .question_types import Question


def key_for(state: Mapping[str, str], questions: Mapping[str, Question]) -> str:
    """Hash all model inputs; weights and thresholds are deliberately absent."""
    payload = json.dumps(
        {
            "version": 1,
            "state": dict(state),
            "questions": {
                qid: {"type": type(question).__name__, **asdict(question)}
                for qid, question in questions.items()
            },
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def to_json(judgments: Judgments) -> dict[str, Any]:
    return {
        "nouls": dict(judgments.nouls),
        "scores": {
            qid: {
                "value": score.value,
                "max_level": score.max_level,
                "confidence": score.confidence,
            }
            for qid, score in judgments.scores.items()
        },
        "choices": {
            qid: {
                "selected": choice.selected,
                "confidence": choice.confidence,
                "probabilities": dict(choice.probabilities),
            }
            for qid, choice in judgments.choices.items()
        },
    }


def from_json(raw: Mapping[str, Any]) -> Judgments:
    return Judgments(
        nouls={qid: float(v) for qid, v in raw.get("nouls", {}).items()},
        scores={
            qid: ScoreValue(
                value=float(s["value"]),
                max_level=int(s["max_level"]),
                confidence=float(s["confidence"]),
            )
            for qid, s in raw.get("scores", {}).items()
        },
        choices={
            qid: ChoiceValue(
                selected=str(c["selected"]),
                confidence=float(c["confidence"]),
                probabilities={k: float(v) for k, v in c["probabilities"].items()},
            )
            for qid, c in raw.get("choices", {}).items()
        },
    )

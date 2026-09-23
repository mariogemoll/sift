"""Model boundary and the deterministic offline adapter."""

from sift.judge.asker import Ask, Asker, ask_for
from sift.judge.fake import FakeAsker

__all__ = ["Ask", "Asker", "FakeAsker", "ask_for"]

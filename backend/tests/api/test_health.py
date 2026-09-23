from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from httpx import AsyncClient

ROOT = Path(__file__).resolve().parent.parent.parent


def head_revision() -> str:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    head = script.get_current_head()
    assert head is not None
    return head


async def test_health_reports_a_reachable_database(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json()["database"] is True


async def test_health_reports_the_revision_the_database_is_on(
    client: AsyncClient,
) -> None:
    body = (await client.get("/health")).json()
    assert body["revision"] == head_revision()
    assert body["ok"] is True

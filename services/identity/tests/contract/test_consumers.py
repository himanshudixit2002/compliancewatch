"""Provider side of the WhatsApp bot's consumer contract with identity.

packages/contracts/consumers/whatsapp-bot/identity.json holds the requests the bot's
``HttpConsentLedger`` sends, in order, and the parts of each response it relies on. They
are replayed against a fresh app: each status must match, and each recorded body must be a
subset of the served one. The app runs with ``CHANNEL_TOKEN``, the service token the file
records; a wrong one is recorded too, answered with 401. The bot's
apps/whatsapp-bot/src/contracts.test.ts checks the same file from the consumer side.
"""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from identity.main import build_app
from identity.testing import CHANNEL_TOKEN, identity_settings

CONTRACT = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "contracts"
    / "consumers"
    / "whatsapp-bot"
    / "identity.json"
)


def assert_subset(expected: Any, served: Any, where: str) -> None:
    """Every key of ``expected`` is in ``served`` with a matching value; lists match in full."""
    if isinstance(expected, dict):
        assert isinstance(served, dict), f"{where}: expected an object, got {served!r}"
        for key, value in expected.items():
            assert key in served, f"{where}: {key!r} missing from {served!r}"
            assert_subset(value, served[key], f"{where}.{key}")
    elif isinstance(expected, list):
        assert isinstance(served, list), f"{where}: expected a list, got {served!r}"
        assert len(served) == len(expected), f"{where}: {len(served)} items, not {len(expected)}"
        for index, (item, got) in enumerate(zip(expected, served, strict=True)):
            assert_subset(item, got, f"{where}[{index}]")
    else:
        assert served == expected, f"{where}: {served!r} != {expected!r}"


def test_the_bot_interactions_replay_in_order() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert (contract["consumer"], contract["provider"]) == ("whatsapp-bot", "identity")
    assert contract["interactions"]
    with TestClient(build_app(identity_settings(identity_channel_token=CHANNEL_TOKEN))) as client:
        for interaction in contract["interactions"]:
            request, expected = interaction["request"], interaction["response"]
            response = client.request(
                request["method"],
                request["path"],
                headers=request.get("headers", {}),
                json=request.get("body"),
            )
            where = interaction["description"]
            assert response.status_code == expected["status"], f"{where}: {response.text}"
            assert_subset(expected.get("body", {}), response.json(), where)

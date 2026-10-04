"""Many questions at once do not starve the calls qa makes to the other services in the process.

qa's ask route is sync: it holds a thread of the pool while it calls the rulebook and the gateway
over the internal listener, and those routes need threads of the same pool. With anyio's 40
threads and no limit, 64 questions at once take every thread and the calls they make wait until
they time out. The app raises the pool and runs at most ``CW_MVP_LOOPBACK_LIMIT`` asks at once,
so every question is answered.
"""

import asyncio
from collections import Counter
from uuid import uuid4

import httpx2

from cw_mvp.app import CombinedApp, in_process_tokens
from cw_mvp.testing import LOCALHOST, running_app

QUESTIONS = 64
QUESTION = {"question": "When is GSTR-3B due for a monthly filer?"}


async def ask(app: CombinedApp, times: int, headers: dict[str, str]) -> Counter[int]:
    base_url = f"http://{LOCALHOST}:{app.settings.mvp_public_port}"
    async with httpx2.AsyncClient(base_url=base_url, timeout=60.0) as client:
        responses = await asyncio.gather(
            *(client.post("/v1/qa/ask", json=QUESTION, headers=headers) for _ in range(times))
        )
    return Counter(response.status_code for response in responses)


async def test_sixty_four_questions_at_once_are_all_answered() -> None:
    with running_app() as app:
        statuses = await ask(app, QUESTIONS, {"x-tenant-id": str(uuid4())})
    assert statuses == {200: QUESTIONS}, statuses


async def test_in_token_mode_the_calls_qa_makes_carry_its_own_token() -> None:
    """The gateway takes a model call only from a caller with llm:call; qa's in-process token
    has it, so the question is answered rather than failing on the gateway's 401."""
    with running_app(auth_mode="token") as app:
        caller = in_process_tokens(app.services["identity"], "")("qa").token()
        headers = {"x-tenant-id": str(uuid4()), "authorization": f"Bearer {caller}"}
        assert await ask(app, 4, headers) == {200: 4}
        assert await ask(app, 1, {"x-tenant-id": str(uuid4())}) == {401: 1}

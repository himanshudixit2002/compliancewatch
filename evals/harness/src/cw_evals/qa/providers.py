"""Where the qa suite's model answers come from, and what the harness sees of every call.

``scripted`` answers each case with its own labels, keyed on the case in flight: the harness
sets ``current_case`` before each question. ``qa.plan`` gets ``scripted.plan``; the planner's
retry (``attempt`` 2 in the call's metadata) gets ``scripted.plan_retry`` when the case has one,
otherwise the same plan. ``qa.answer`` gets ``scripted.answer`` only when every date the case
expects is written in the evidence of the prompt (its clauses and facts, read with the scorer's
``dates_in``); otherwise it declines, as a model could not state a date it was not given, and the
missing dates are noted against the case. A call the case does not script is
``UnscriptedCallError``, and the run stops on it rather than score a question the labels do not
cover. The scripted provider is served through the gateway app
(``build_app(completion_provider=...)``), so the registry check, the masking and the ledger run
as in production. ``fake`` is the same gateway app with its own deterministic provider;
``gateway`` is a running gateway over HTTP, for the nightly run with a real model.

A scripted citation names its clause by document and clause ref; the provider writes the label
the evidence in its prompt gives that clause (``[C2] en.p3 (01/2026-Central Tax)``), as a model
reading the prompt would. The labels follow the order the solver or the search met the
clauses, which is not a property of the case. A clause the evidence does not list gets a label
that names no listed clause, so the answer fails the citation check; a citation given as a
label (``clause: C13``) is written as it is.

``CallLog`` is a response hook on the client qa talks to the gateway with: it records every
completion by the question id and stage its metadata carries, with its tokens, whichever
provider answered.
"""

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Final

import httpx2

from cw_evals.providers import gateway_client
from cw_evals.qa.cases import QaCase, plan_text, scripted_answer
from cw_evals.qa.score import ANSWER, PLAN, ModelCall, dates_in
from domain_kernel.llm import CompletionRequest, CompletionResponse
from domain_kernel.protocols import LLMProvider

QA_PROVIDERS: Final = ("scripted", "fake", "gateway")
COMPLETIONS: Final = "/v1/llm-gateway/completions"
GATEWAY_TIMEOUT_SECONDS: Final = 60.0
DECLINED: Final = json.dumps({"covered": False, "answer": "", "citations": []})
_EVIDENCE: Final = re.compile(r"^Clauses:$", re.MULTILINE)
"""Where the evidence starts in an answer prompt (``render_bundle``)."""
_RETRY: Final = "\n\nYour previous answer failed the check:"
"""Where the answerer's retry note starts; it may quote the previous answer."""


def evidence_of(prompt: str) -> str:
    """The evidence an answer prompt gives: its clauses and facts, not the question."""
    start = _EVIDENCE.search(prompt)
    return "" if start is None else prompt[start.start() :].split(_RETRY, 1)[0]


class UnscriptedCallError(RuntimeError):
    """A model call the case in flight has no scripted answer for."""

    def __init__(self, case_id: str | None, prompt: str) -> None:
        self.case_id = case_id
        self.prompt = prompt
        super().__init__(f"case {case_id or '(none)'} has no scripted answer for {prompt}")


class ScriptedQaProvider:
    """An ``LLMProvider`` answering from the cases' ``scripted`` blocks. Not a model."""

    MODEL = "scripted/qa-golden"

    def __init__(self, cases: Sequence[QaCase], sources: Mapping[str, str]) -> None:
        self._cases = {case.case_id: case for case in cases}
        self._sources = dict(sources)
        self.current_case: str | None = None
        self.aborted: UnscriptedCallError | None = None
        self.notes: list[str] = []
        """What the provider withheld for the case in flight, and why."""

    def complete(self, req: CompletionRequest) -> CompletionResponse:
        text = self._reply(req)
        if text is None:
            self.aborted = UnscriptedCallError(self.current_case, req.prompt_version)
            raise self.aborted
        return CompletionResponse(text=text, model=self.MODEL, input_tokens=0, output_tokens=0)

    def _reply(self, req: CompletionRequest) -> str | None:
        case = self._cases.get(self.current_case or "")
        if case is None:
            return None
        name = req.prompt_version.partition("@")[0]
        scripted = case.scripted
        if name == PLAN and scripted.plan is not None:
            retry = scripted.plan_retry if req.metadata.get("attempt") == "2" else None
            return plan_text(retry or scripted.plan)
        if name == ANSWER and scripted.answer is not None:
            written = dates_in(evidence_of(req.user))
            missing = [
                fact.value
                for fact in case.expected.facts
                if fact.kind == "date" and date.fromisoformat(fact.value) not in written
            ]
            if missing:
                layer = req.metadata.get("layer")
                where = f"the {layer} evidence" if layer else "the evidence"
                self.notes.append(f"scripted answer withheld: {', '.join(missing)} not in {where}")
                return DECLINED
            return json.dumps(scripted_answer(scripted.answer, req.user, self._sources))
        return None


class CallLog:
    """Every completion qa asked the gateway for, in order (a response hook)."""

    def __init__(self) -> None:
        self.calls: list[ModelCall] = []

    def __call__(self, response: httpx2.Response) -> None:
        request = response.request
        if not request.url.path.endswith(COMPLETIONS):
            return
        body = json.loads(request.content or b"{}")
        metadata = body.get("metadata") or {}
        tokens = {"input_tokens": 0, "output_tokens": 0}
        if response.status_code == 200:
            response.read()
            data = response.json()
            tokens = {name: int(data.get(name) or 0) for name in tokens}
        self.calls.append(
            ModelCall(
                question_id=str(metadata.get("question_id", "")),
                prompt=str(body.get("prompt", "")),
                stage=str(metadata.get("stage", "")),
                attempt=int(metadata.get("attempt") or 0),
                status=response.status_code,
                **tokens,
            )
        )

    def of(self, question_id: str) -> list[ModelCall]:
        return [call for call in self.calls if call.question_id == question_id]


@dataclass
class QaModel:
    """The gateway client qa talks to, the call log hooked on it, and the scripted provider
    when there is one (``start`` sets the case in flight)."""

    client: httpx2.Client
    log: CallLog
    scripted: ScriptedQaProvider | None = None

    def start(self, case_id: str) -> None:
        if self.scripted is not None:
            self.scripted.current_case = case_id
            self.scripted.notes = []

    @property
    def notes(self) -> tuple[str, ...]:
        return () if self.scripted is None else tuple(self.scripted.notes)

    @property
    def aborted(self) -> UnscriptedCallError | None:
        return None if self.scripted is None else self.scripted.aborted


@contextmanager
def qa_model(
    name: str, cases: Sequence[QaCase], sources: Mapping[str, str], *, gateway_url: str
) -> Iterator[QaModel]:
    """The gateway for provider ``name``: in process for ``scripted`` and ``fake``, over HTTP
    for ``gateway``."""
    log = CallLog()
    if name == "gateway":
        client = httpx2.Client(base_url=gateway_url, timeout=GATEWAY_TIMEOUT_SECONDS)
        client.event_hooks["response"].append(log)
        try:
            yield QaModel(client, log)
        finally:
            client.close()
        return
    provider: LLMProvider | None = None
    scripted: ScriptedQaProvider | None = None
    if name == "scripted":
        provider = scripted = ScriptedQaProvider(cases, sources)
    elif name != "fake":
        raise ValueError(f"unknown provider {name!r}; known: {', '.join(QA_PROVIDERS)}")
    with gateway_client(provider) as client:
        client.event_hooks["response"].append(log)
        yield QaModel(client, log, scripted)

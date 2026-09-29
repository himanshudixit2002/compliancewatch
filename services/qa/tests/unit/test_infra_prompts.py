"""The prompt loader: header, body, the name and version check, the digest."""

import hashlib
from pathlib import Path

import pytest

from qa.infrastructure.prompts import PROMPTS_DIR, load_prompt, prompt_digest, prompt_path

HEADER = "name: qa.plan\nversion: 1\nowner: ai-platform\neval_cases: evals/golden/qa/kag\n\n"


def test_a_prompt_file_is_read(tmp_path: Path) -> None:
    path = prompt_path("qa.plan", "1", tmp_path)
    path.write_text(HEADER + "Plan the question.\n", encoding="utf-8")
    prompt = load_prompt("qa.plan", "1", tmp_path)
    assert (prompt.ref, prompt.owner, prompt.system) == (
        "qa.plan@1",
        "ai-platform",
        "Plan the question.",
    )
    assert prompt_digest("qa.plan", "1", tmp_path) == hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_file_that_names_another_prompt_is_refused(tmp_path: Path) -> None:
    prompt_path("qa.answer", "1", tmp_path).write_text(HEADER + "text", encoding="utf-8")
    with pytest.raises(ValueError, match="declares"):
        load_prompt("qa.answer", "1", tmp_path)


def test_the_prompts_live_next_to_the_package() -> None:
    assert PROMPTS_DIR.parts[-3:] == ("services", "qa", "prompts")

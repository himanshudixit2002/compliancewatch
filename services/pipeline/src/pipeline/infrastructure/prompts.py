"""Prompt files under ``services/pipeline/prompts``: ``<name>.v<version>.md`` with a header.

The header is the first lines as ``key: value`` (name, version, owner), a blank line, then the
prompt text. The gateway's registry lists the same name and version with the digest of the
whole file, so a changed prompt without a registry change is refused at call time.
"""

import hashlib
from pathlib import Path

from pipeline.domain.prompt import PromptText

PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


def prompt_path(name: str, version: str, directory: Path = PROMPTS_DIR) -> Path:
    return directory / f"{name}.v{version}.md"


def load_prompt(name: str, version: str, directory: Path = PROMPTS_DIR) -> PromptText:
    text = prompt_path(name, version, directory).read_text(encoding="utf-8")
    header, _, body = text.partition("\n\n")
    fields = dict(line.split(":", 1) for line in header.splitlines() if ":" in line)
    fields = {k.strip(): v.strip() for k, v in fields.items()}
    if fields.get("name") != name or fields.get("version") != version:
        raise ValueError(f"prompt file for {name}@{version} declares {fields}")
    return PromptText(name, version, fields.get("owner", ""), body.strip())


def prompt_digest(name: str, version: str, directory: Path = PROMPTS_DIR) -> str:
    return hashlib.sha256(prompt_path(name, version, directory).read_bytes()).hexdigest()

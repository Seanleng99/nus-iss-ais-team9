import json
from hashlib import sha256
from pathlib import Path

from app.core.telemetry import trace_method

CURRENCY_POLICY = (
    "Application currency policy: Personal financial amounts in this Singapore app use SGD. "
    "Default omitted currency, bare amounts and $ amounts to SGD; do not ask users to specify "
    "or confirm currency. Currency is fixed, not a user preference. If a user explicitly supplies "
    "another currency for a personal financial amount, explain that only SGD is supported and "
    "request the amount in SGD; never convert or relabel it. Preserve currency labels in existing "
    "records and educational source material, including explanations of currency risk."
)


PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompts" / "current"
CURRENT_PROMPT_VERSION = json.loads((PROMPT_ROOT / "manifest.json").read_text(encoding="utf-8"))[
    "version"
]


class PromptCatalog:
    """The single packaged prompt contract; version is provenance, not selection."""

    def __init__(self, *, root: Path | None = None) -> None:
        prompt_root = root or PROMPT_ROOT
        path = prompt_root / "prompts.json"
        with path.open(encoding="utf-8") as handle:
            self._prompts: dict[str, str] = json.load(handle)
        self.version = json.loads((prompt_root / "manifest.json").read_text(encoding="utf-8"))[
            "version"
        ]

    @property
    def content_hash(self) -> str:
        # Hash effective instructions, including the shared policy appended by get().
        content = {key: value + "\n\n" + CURRENCY_POLICY for key, value in self._prompts.items()}
        return sha256(
            json.dumps(
                {"version": self.version, "prompts": content}, sort_keys=True, ensure_ascii=True
            ).encode()
        ).hexdigest()

    def identity(self, build_commit: str) -> dict[str, str]:
        return {
            "prompt_set_version": self.version,
            "prompt_content_hash": self.content_hash,
            "build_commit": build_commit,
        }

    @trace_method
    def get(self, prompt_id: str) -> str:
        try:
            return self._prompts[prompt_id] + "\n\n" + CURRENCY_POLICY
        except KeyError as exc:
            raise KeyError(f"Unknown prompt ID in {self.version}: {prompt_id}") from exc

import json
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


class PromptCatalog:
    def __init__(self, version: str = "v8", root: Path | None = None) -> None:
        prompt_root = root or Path(__file__).resolve().parents[2] / "prompts"
        path = prompt_root / version / "prompts.json"
        with path.open(encoding="utf-8") as handle:
            self._prompts: dict[str, str] = json.load(handle)
        self.version = version

    @trace_method
    def get(self, prompt_id: str) -> str:
        try:
            return self._prompts[prompt_id] + "\n\n" + CURRENCY_POLICY
        except KeyError as exc:
            raise KeyError(f"Unknown prompt ID in {self.version}: {prompt_id}") from exc

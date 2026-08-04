import json
from pathlib import Path


class PromptCatalog:
    def __init__(self, version: str = "v1", root: Path | None = None) -> None:
        prompt_root = root or Path(__file__).resolve().parents[2] / "prompts"
        path = prompt_root / version / "prompts.json"
        with path.open(encoding="utf-8") as handle:
            self._prompts: dict[str, str] = json.load(handle)
        self.version = version

    def get(self, prompt_id: str) -> str:
        try:
            return self._prompts[prompt_id]
        except KeyError as exc:
            raise KeyError(f"Unknown prompt ID in {self.version}: {prompt_id}") from exc

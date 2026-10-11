import json
from hashlib import sha256
from pathlib import Path

from app.core.telemetry import log_event, trace_method

CURRENCY_POLICY = (
    "Application currency policy: Personal financial amounts in this Singapore app use SGD. "
    "Default omitted currency, bare amounts and $ amounts to SGD; do not ask users to specify "
    "or confirm currency. Currency is fixed, not a user preference. If a user explicitly supplies "
    "another currency for a personal financial amount, explain that only SGD is supported and "
    "request the amount in SGD; never convert or relabel it. Preserve currency labels in existing "
    "records and educational source material, including explanations of currency risk."
)

FAIRNESS_POLICY = (
    "Application fairness policy: Provide equally respectful, useful and safe financial education "
    "for equivalent financial facts. Never infer income, financial literacy, spending habits, "
    "creditworthiness, financial capability or risk tolerance from names, race, ethnicity, religion, "
    "gender, age, nationality, disability, language or dialect. Never use these cues to change "
    "financial calculations, access to help or safety decisions. Use verified financial facts and "
    "explicit relevant preferences; tailor language and accessibility without stereotyping. "
    "A user's disclosure of disability-related expenses, cultural needs or demographic identity "
    "is not itself unsafe. Discuss their stated financial needs without guessing group traits. "
    "Do not request demographic data for coaching or infer it for fairness monitoring. "
    "For Compliance review, identify unsupported demographic assumptions or stereotypes in the "
    "draft as demographic_assumption. Judge the actual claim in context: a quoted stereotype "
    "being rejected or a relevant self-reported expense is not a violation. An otherwise allowed "
    "request remains allowed; withhold the defective draft and locate the offending claim for "
    "removal. A correction must preserve supported financial facts and pass a fresh full review."
)


PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompts" / "current"
CURRENT_PROMPT_VERSION = json.loads((PROMPT_ROOT / "manifest.json").read_text(encoding="utf-8"))[
    "version"
]


class PromptCatalog:
    """The single packaged prompt contract; version is provenance, not selection."""

    def __init__(self, *, root: Path | None = None) -> None:
        log_event("VV entering ", "app.core.prompts.PromptCatalog", "__init__")
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
        log_event("VV entering ", "app.core.prompts.PromptCatalog", "content_hash")
        content = {key: self._effective_prompt(key) for key in self._prompts}
        return sha256(
            json.dumps(
                {"version": self.version, "prompts": content}, sort_keys=True, ensure_ascii=True
            ).encode()
        ).hexdigest()

    def identity(self, build_commit: str) -> dict[str, str]:
        log_event("VV entering ", "app.core.prompts.PromptCatalog", "identity")
        return {
            "prompt_set_version": self.version,
            "prompt_content_hash": self.content_hash,
            "build_commit": build_commit,
        }

    @trace_method
    def get(self, prompt_id: str) -> str:
        log_event("VV entering ", "app.core.prompts.PromptCatalog", "get")
        try:
            return self._effective_prompt(prompt_id)
        except KeyError as exc:
            raise KeyError(f"Unknown prompt ID in {self.version}: {prompt_id}") from exc

    def _effective_prompt(self, prompt_id: str) -> str:
        log_event("VV entering ", "app.core.prompts.PromptCatalog", "_effective_prompt")
        return self._prompts[prompt_id] + "\n\n" + CURRENCY_POLICY + "\n\n" + FAIRNESS_POLICY

import json
import re
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.models.gateway import ModelGateway, ModelGatewayError

StructuredModel = TypeVar("StructuredModel", bound=BaseModel)


def parse_structured_response(raw: str, response_type: type[StructuredModel]) -> StructuredModel:
    candidate = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, flags=re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            candidate = candidate[start : end + 1]

    try:
        return response_type.model_validate(json.loads(candidate))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ModelGatewayError(
            "The model returned an invalid structured response.",
            code="INVALID_STRUCTURED_RESPONSE",
            component=response_type.__name__,
        ) from exc


def generate_structured_response(
    gateway: ModelGateway,
    *,
    response_type: type[StructuredModel],
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
    validate_response: Callable[[StructuredModel], StructuredModel] | None = None,
) -> StructuredModel:
    """Generate a typed response with one explicit, bounded correction attempt."""
    raw = gateway.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    try:
        parsed = parse_structured_response(raw, response_type)
        return validate_response(parsed) if validate_response else parsed
    except ModelGatewayError as exc:
        if exc.code not in {
            "INVALID_STRUCTURED_RESPONSE", "UNAPPROVED_CITATION", "MISSING_CITATION",
        }:
            raise
        cause = exc.__cause__
        if exc.code in {"UNAPPROVED_CITATION", "MISSING_CITATION"}:
            validation_issues = (
                "Follow the citation contract and use only actual source IDs supplied "
                "in the request. Never copy example or placeholder IDs. If there are "
                "no approved sources, use no citation markers, links or square brackets. "
                "When sources are required, declare only the sources used and cite "
                "the supporting IDs in the summary. Do not generate URLs."
            )
        elif isinstance(cause, ValidationError):
            validation_issues = json.dumps(
                [
                    {
                        "location": ".".join(str(item) for item in issue["loc"]),
                        "message": issue["msg"],
                    }
                    for issue in cause.errors(include_input=False)
                ],
                ensure_ascii=True,
            )
        else:
            validation_issues = "The response was not valid JSON."

    schema = json.dumps(response_type.model_json_schema(), ensure_ascii=True)
    correction_prompt = (
        f"{system_prompt}\n"
        "CORRECTION: The previous response did not satisfy the required contract. "
        "Return exactly one valid JSON object with no Markdown fence, commentary, or "
        f"additional keys. Validation issues: {validation_issues}. "
        f"It must validate against this JSON Schema: {schema}"
    )
    corrected = gateway.generate(
        system_prompt=correction_prompt,
        user_prompt=user_prompt,
        temperature=min(temperature, 0.1),
        max_tokens=max_tokens,
    )
    parsed = parse_structured_response(corrected, response_type)
    return validate_response(parsed) if validate_response else parsed

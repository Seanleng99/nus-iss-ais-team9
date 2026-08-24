import json
import re
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
) -> StructuredModel:
    """Generate a typed response with one explicit, bounded correction attempt."""
    raw = gateway.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    try:
        return parse_structured_response(raw, response_type)
    except ModelGatewayError as exc:
        if exc.code != "INVALID_STRUCTURED_RESPONSE":
            raise

    schema = json.dumps(response_type.model_json_schema(), ensure_ascii=True)
    correction_prompt = (
        f"{system_prompt}\n"
        "CORRECTION: The previous response did not satisfy the required contract. "
        "Return exactly one valid JSON object with no Markdown fence, commentary, or "
        f"additional keys. It must validate against this JSON Schema: {schema}"
    )
    corrected = gateway.generate(
        system_prompt=correction_prompt,
        user_prompt=user_prompt,
        temperature=min(temperature, 0.1),
        max_tokens=max_tokens,
    )
    return parse_structured_response(corrected, response_type)

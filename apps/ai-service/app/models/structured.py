import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.models.gateway import ModelGatewayError

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
        raise ModelGatewayError("The model returned an invalid structured response.") from exc

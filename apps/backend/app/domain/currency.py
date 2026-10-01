"""Fixed currency for application inputs; stored records retain their original labels."""

from typing import Annotated, Literal

from pydantic import BeforeValidator

APPLICATION_CURRENCY = "SGD"


def default_currency(value):
    return APPLICATION_CURRENCY if value is None else value


ApplicationCurrency = Annotated[Literal["SGD"], BeforeValidator(default_currency)]

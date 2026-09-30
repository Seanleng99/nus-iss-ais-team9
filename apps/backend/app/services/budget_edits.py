"""Explicit collection edits resolved against owned saved settings before validation."""

from copy import deepcopy
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class CollectionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection: Literal["schedules", "debts", "goals", "reserves", "protected_categories", "category_floors"]
    action: Literal["add", "update", "remove"]
    key: str | None = Field(default=None, min_length=1, max_length=128)
    values: dict = Field(default_factory=dict, max_length=20)


def apply_edits(operation, previous, supplied):
    supplied = deepcopy(supplied)
    edits = TypeAdapter(list[CollectionEdit]).validate_python(supplied.pop("edits", []))
    if len(edits) > 100:
        raise ValueError("Edit at most 100 items at once")
    allowed = {"cashflow": {"schedules"}, "commitments": {"debts", "goals", "protected_categories", "category_floors"}, "reserves": {"reserves"}}[operation]
    target = {**deepcopy(previous or {}), **supplied}
    touched = set()
    for edit in edits:
        name = edit.collection
        if edit.key is None:
            if edit.action == "add" and name in {"schedules", "reserves"}:
                edit.key = str(uuid4())
            else:
                raise ValueError("Supply the exact item key to edit")
        if name not in allowed or name in supplied:
            raise ValueError("Choose an allowed collection and use either edits or full replacement for that collection")
        if (name, edit.key) in touched:
            raise ValueError("Supply one final edit per item; clarify the intended result")
        touched.add((name, edit.key))
        if edit.action == "remove" and edit.values:
            raise ValueError("Removal must not contain new values")
        if name in {"protected_categories", "category_floors"}:
            key = " ".join(edit.key.split()).lower()
            collection = target.setdefault(name, {} if name == "category_floors" else [])
            exists = key in collection
            if (edit.action == "add" and exists) or (edit.action != "add" and not exists):
                raise ValueError(f"Category {key} {'already exists' if exists else 'was not found'}; clarify the edit")
            if name == "protected_categories":
                if edit.values or edit.action == "update":
                    raise ValueError("Protected categories accept explicit add or remove only")
                collection.append(key) if edit.action == "add" else collection.remove(key)
            elif edit.action == "remove":
                del collection[key]
            else:
                if set(edit.values) != {"amount"}:
                    raise ValueError("Supply the category floor amount")
                collection[key] = edit.values["amount"]
            continue
        identity = {"schedules": "id", "reserves": "id", "goals": "goal_id", "debts": "name"}[name]
        collection = target.setdefault(name, [])
        matches = [i for i, item in enumerate(collection) if str(item.get(identity)) == edit.key]
        if edit.action == "add":
            if matches:
                raise ValueError("That item already exists; choose update or clarify its identity")
            if identity in edit.values and str(edit.values[identity]) != edit.key:
                raise ValueError("The item key and identity must agree")
            collection.append({**edit.values, identity: edit.key})
        else:
            if len(matches) != 1:
                raise ValueError(f"Select exactly one existing {name} item by {identity}; the supplied key is missing or ambiguous")
            if identity in edit.values and str(edit.values[identity]) != edit.key:
                raise ValueError("An edit cannot change an item's identity; explicitly remove and add instead")
            if edit.action == "remove":
                collection.pop(matches[0])
            else:
                if not edit.values:
                    raise ValueError("Supply the fields to change")
                collection[matches[0]].update(edit.values)
    return target

import argparse
import json
from pathlib import Path


def load_container_environment(task_definition: Path, container_name: str) -> dict[str, str]:
    payload = json.loads(task_definition.read_text(encoding="utf-8"))
    containers = payload.get("containerDefinitions", [])
    container = next(
        (item for item in containers if item.get("name") == container_name),
        None,
    )
    if container is None:
        raise ValueError(f"container {container_name!r} is absent from the task definition")
    return {
        str(item["name"]): str(item.get("value", ""))
        for item in container.get("environment", [])
        if item.get("name")
    }


def verify_environment(
    environment: dict[str, str],
    expected: dict[str, str],
    required_nonempty: set[str],
) -> list[str]:
    errors = [
        f"{name} must be {value!r}; received {environment.get(name)!r}"
        for name, value in expected.items()
        if environment.get(name) != value
    ]
    errors.extend(
        f"{name} must be configured with a non-empty value"
        for name in sorted(required_nonempty)
        if not environment.get(name, "").strip()
    )
    return errors


def parse_expected(values: list[str]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for value in values:
        name, separator, expected_value = value.partition("=")
        if not separator or not name:
            raise ValueError(f"expected NAME=VALUE, received {value!r}")
        expected[name] = expected_value
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fail a release when an ECS task definition has unsafe runtime drift"
    )
    parser.add_argument("--task-definition", required=True, type=Path)
    parser.add_argument("--container", required=True)
    parser.add_argument("--expect", action="append", default=[])
    parser.add_argument("--require-nonempty", action="append", default=[])
    args = parser.parse_args()

    environment = load_container_environment(args.task_definition, args.container)
    errors = verify_environment(
        environment,
        parse_expected(args.expect),
        set(args.require_nonempty),
    )
    if errors:
        raise SystemExit("ECS runtime configuration drift detected:\n- " + "\n- ".join(errors))
    print("ECS runtime configuration verified")


if __name__ == "__main__":
    main()

import argparse
import json
from pathlib import Path

FLAGS = (
    "frontend_ci",
    "backend_ci",
    "ai_ci",
    "infrastructure",
    "integration",
    "sast",
    "frontend_deploy",
    "backend_deploy",
    "ai_deploy",
    "migrations",
)


def _select_all(result: dict[str, bool]) -> None:
    for flag in FLAGS:
        if flag != "migrations":
            result[flag] = True


def classify_changes(paths: list[str], force_all: bool = False) -> dict[str, bool]:
    result = {flag: False for flag in FLAGS}
    if force_all:
        _select_all(result)
    else:
        for raw_path in paths:
            path = raw_path.strip().replace("\\", "/")
            path = path.removeprefix("./")
            if not path or path.startswith("docs/"):
                continue

            if path == ".github/workflows/model-comparison.yml":
                result.update(ai_ci=True, infrastructure=True, sast=True)
                continue

            if path.startswith(".github/workflows/") or path in {
                ".dockerignore",
                "docker-compose.yml",
            }:
                _select_all(result)
                continue

            if path.startswith("apps/frontend/"):
                result.update(frontend_ci=True, frontend_deploy=True, sast=True)
                continue

            if path.startswith("apps/backend/"):
                result.update(
                    backend_ci=True,
                    backend_deploy=True,
                    integration=True,
                    sast=True,
                )
                if path.startswith("apps/backend/migrations/") or path == (
                    "apps/backend/alembic.ini"
                ):
                    result["migrations"] = True
                continue

            if path.startswith("apps/ai-service/"):
                result.update(
                    ai_ci=True,
                    ai_deploy=True,
                    backend_ci=True,
                    backend_deploy=True,
                    integration=True,
                    sast=True,
                )
                continue

            dockerfiles = {
                "infra/docker/Dockerfile.frontend": ("frontend_ci", "frontend_deploy"),
                "infra/docker/Dockerfile.backend": ("backend_ci", "backend_deploy"),
                "infra/docker/Dockerfile.ai-service": ("ai_ci", "ai_deploy"),
            }
            if path in dockerfiles:
                for flag in dockerfiles[path]:
                    result[flag] = True
                if path == "infra/docker/Dockerfile.ai-service":
                    result.update(backend_ci=True, backend_deploy=True)
                result["sast"] = True
                if path.endswith(("Dockerfile.backend", "Dockerfile.ai-service")):
                    result["integration"] = True
                continue

            if path.startswith("infra/aws/"):
                result["infrastructure"] = True
                continue

            if path == "infra/llmsecops/ecr-scan-exceptions.json":
                result.update(
                    frontend_ci=True,
                    backend_ci=True,
                    ai_ci=True,
                    frontend_deploy=True,
                    backend_deploy=True,
                    ai_deploy=True,
                    integration=True,
                    sast=True,
                )
                continue

            if path.startswith("infra/llmsecops/"):
                result["ai_ci"] = True
                continue

            if path.startswith("infra/scripts/"):
                result["sast"] = True
                result["infrastructure"] = True
                if path.endswith(("load_smoke.py", "post_deploy_smoke.py")):
                    result["integration"] = True
                continue

            if path in {"README.md", "LICENSE", ".gitignore", ".gitattributes"}:
                continue

            if path == ".github/dependabot.yml":
                continue

            # Unknown executable or configuration changes take the conservative path.
            _select_all(result)

    result["deploy"] = any(
        result[flag]
        for flag in ("frontend_deploy", "backend_deploy", "ai_deploy")
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify repository changes for CI/CD")
    parser.add_argument("--changed-files", type=Path)
    parser.add_argument("--all", action="store_true", dest="force_all")
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    if not args.force_all and args.changed_files is None:
        parser.error("provide --changed-files or --all")

    paths = [] if args.force_all else args.changed_files.read_text().splitlines()
    result = classify_changes(paths, force_all=args.force_all)

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            for key, value in result.items():
                output.write(f"{key}={str(value).lower()}\n")

    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()

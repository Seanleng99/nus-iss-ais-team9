"""Inventory Han characters in all tracked and non-ignored project text files.

Outputs file paths and line numbers only, never source content or secrets.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_CONFIG = ROOT / "apps/shared/coach_i18n/data/scripts.json"
HAN = re.compile(json.loads(SCRIPT_CONFIG.read_text(encoding="utf-8"))["han_inventory"])
ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})|\\U([0-9a-fA-F]{8})")
CODE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".sh", ".ps1"}


def category(path: str) -> str:
    if path.startswith("apps/shared/coach_i18n/"):
        return "language_resources"
    if "/tests/fixtures/" in path:
        return "test_fixtures"
    if "/evals/datasets/" in path or path.startswith("infra/llmsecops/"):
        return "evaluation_datasets"
    if Path(path).suffix in CODE_SUFFIXES:
        return "code"
    if path.startswith("docs/") or path.endswith(".md"):
        return "documentation"
    return "application_or_configuration"


def inventory(revision: str | None = None) -> dict:
    command = (
        ["git", "ls-tree", "-r", "--name-only", "-z", revision]
        if revision
        else ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    )
    paths = sorted(
        set(subprocess.check_output(command, cwd=ROOT).decode("utf-8").split("\0"))
        - {""}
    )
    matches = []
    scanned = 0
    for name in paths:
        try:
            raw = (
                subprocess.check_output(["git", "show", f"{revision}:{name}"], cwd=ROOT)
                if revision
                else (ROOT / name).read_bytes()
            )
            if b"\0" in raw:
                continue
            text = raw.decode("utf-8-sig")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        scanned += 1
        literal_lines, escaped_lines = [], []
        for number, line in enumerate(text.splitlines(), 1):
            if HAN.search(line):
                literal_lines.append(number)
            if any(
                HAN.search(chr(int(match[1] or match[2], 16)))
                for match in ESCAPE.finditer(line)
            ):
                escaped_lines.append(number)
        if literal_lines or escaped_lines:
            matches.append(
                {
                    "path": name,
                    "category": category(name),
                    "literal_lines": literal_lines,
                    "escaped_lines": escaped_lines,
                }
            )
    counts = {}
    for item in matches:
        counts[item["category"]] = counts.get(item["category"], 0) + 1
    return {
        "revision": revision or "working_tree",
        "text_files_scanned": scanned,
        "files_with_han": len(matches),
        "categories": counts,
        "files": matches,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", help="Optional Git revision to inventory")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--markdown", type=Path, help="Optional human-readable inventory"
    )
    parser.add_argument(
        "--check-code",
        action="store_true",
        help="Fail if code contains Han literals or escapes; resource files are allowed",
    )
    args = parser.parse_args()
    result = inventory(args.revision)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if args.markdown:
        lines = [
            "# Chinese-character inventory",
            "",
            (
                f"Scanned {result['text_files_scanned']} tracked and non-ignored UTF-8 text files "
                f"at `{result['revision']}`; {result['files_with_han']} files contain Han "
                "characters or Unicode escapes representing them."
            ),
            "",
            (
                "Literal characters and escaped code points are reported separately. Han script "
                "is also used by Japanese and other languages; this inventory identifies characters, "
                "rather than asserting the language of every string. Ignored environments, generated "
                "artifacts and binary files are excluded. No source contents are copied."
            ),
            "",
            (
                "Developer documentation is English. Chinese display text, input recognition "
                "and safety rules live in shared JSON resources. Test questions and golden "
                "assertions live in independent JSON fixtures and evaluation datasets. "
                f"This scan found {sum(Path(item['path']).suffix in CODE_SUFFIXES for item in result['files'])} "
                "code files with Han literals or escapes."
            ),
            "",
            "| Category | Files |",
            "| --- | ---: |",
            *[
                f"| {key.replace('_', ' ')} | {value} |"
                for key, value in sorted(result["categories"].items())
            ],
            "",
            (
                "See [the JSON inventory](chinese-character-inventory.json) for every matching "
                "line number. Regenerate with `python scripts/scan_chinese.py --output "
                "docs/chinese-character-inventory.json --markdown docs/chinese-character-inventory.md "
                "--check-code`."
            ),
            "",
            "| File | Category | Literal lines | Escaped lines |",
            "| --- | --- | ---: | ---: |",
        ]
        lines.extend(
            f"| [{item['path']}](../{item['path']}) | {item['category'].replace('_', ' ')} "
            f"| {len(item['literal_lines'])} | {len(item['escaped_lines'])} |"
            for item in result["files"]
        )
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "files"}))
    if args.check_code:
        offenders = [
            item["path"]
            for item in result["files"]
            if Path(item["path"]).suffix in CODE_SUFFIXES
        ]
        if offenders:
            raise SystemExit("Han literals or escapes in code: " + ", ".join(offenders))


if __name__ == "__main__":
    main()

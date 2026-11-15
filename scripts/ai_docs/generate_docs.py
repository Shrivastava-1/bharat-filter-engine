import hashlib
import json
import os
import re
import sys
from pathlib import Path

from openai import OpenAI

ROOT = Path(__file__).resolve().parents[2]
COMPARISON_DIR = ROOT / "comparison"
MAX_REPORT_CHARS = 5200
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")


def safe_branch_name(branch: str) -> str:
    return branch.replace("/", "-")


def read_text(path: Path, default: str = "") -> str:
    return path.read_text(encoding="utf-8") if path.exists() else default


def extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError("Groq did not return valid JSON.")
        return json.loads(match.group(0))


def call_groq(branch: str, manifest: str, report: str) -> dict:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing. Add it under GitHub Actions secrets.")

    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    prompt = f"""
You are maintaining documentation for the repository bharat-filter-engine.

Use only the inspection information below. Do not invent features, commands,
APIs, dependencies, or implementation details. If the report does not support
a claim, leave it out.

Return one valid JSON object with exactly these string keys:
- "readme_section": concise Markdown content for a section titled "Recent Changes".
  Do not include the heading itself. Summarize the meaningful user-facing/code
  changes in this branch. Mention important files only when useful.
- "changelog_entry": concise Markdown bullet list for the Unreleased section.
  Each bullet should describe a concrete change. Do not include a heading.

Branch: {branch}

MANIFEST:
{manifest[:900]}

BRANCH INSPECTION REPORT:
{report[:MAX_REPORT_CHARS]}
"""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Return valid JSON only. Be concise and factual."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=1100,
    )
    content = response.choices[0].message.content or ""
    result = extract_json(content)

    for key in ("readme_section", "changelog_entry"):
        if not isinstance(result.get(key), str) or not result[key].strip():
            raise ValueError(f"Groq returned an empty or invalid '{key}'.")
    return result


def update_readme(path: Path, section: str) -> None:
    if path.exists():
        original = read_text(path).rstrip() + "\n"
    else:
        original = "# Bharat Filter Engine\n\nDocumentation for the Bharat Filter Engine project.\n"

    heading = "## Recent Changes"
    replacement = f"{heading}\n\n{section.strip()}\n"
    pattern = re.compile(
        r"(?ms)^## Recent Changes\s*\n.*?(?=^## |\Z)"
    )

    if pattern.search(original):
        updated = pattern.sub(replacement, original, count=1)
    else:
        updated = original.rstrip() + "\n\n" + replacement

    path.write_text(updated.rstrip() + "\n", encoding="utf-8")


def update_changelog(path: Path, entry: str, digest: str) -> None:
    marker = f"<!-- groq-inspection:{digest} -->"
    if path.exists():
        content = read_text(path).rstrip() + "\n"
    else:
        content = "# Changelog\n\nAll notable changes to this project are documented here.\n"

    if marker in content:
        print("This inspection report has already been added to CHANGELOG.md.")
        return

    unreleased = re.search(r"(?m)^## \[?Unreleased\]?\s*$", content)
    addition = f"{marker}\n{entry.strip()}\n"

    if unreleased:
        insert_at = unreleased.end()
        content = content[:insert_at] + "\n\n" + addition + "\n" + content[insert_at:].lstrip("\n")
    else:
        first_h2 = re.search(r"(?m)^## ", content)
        new_section = f"## Unreleased\n\n{addition}\n"
        if first_h2:
            content = content[:first_h2.start()] + new_section + content[first_h2.start():]
        else:
            content = content.rstrip() + "\n\n" + new_section

    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    branch = os.getenv("INSPECTED_BRANCH", "").strip()
    if not branch:
        raise RuntimeError("INSPECTED_BRANCH is missing.")

    report_path = COMPARISON_DIR / f"branch-{safe_branch_name(branch)}.md"
    manifest_path = COMPARISON_DIR / "manifest.md"

    if not report_path.is_file():
        raise FileNotFoundError(f"Inspection report not found: {report_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Inspection manifest not found: {manifest_path}")

    report = read_text(report_path)
    manifest = read_text(manifest_path)
    if not report.strip():
        raise RuntimeError("Inspection report is empty.")

    expected_heading = f"# Branch Comparison: {branch}"
    first_heading = next((line.strip() for line in report.splitlines() if line.startswith("# ")), "")
    if first_heading != expected_heading:
        raise RuntimeError(
            f"Report branch mismatch. Expected '{expected_heading}', got '{first_heading}'."
        )

    print(f"Generating documentation from inspection report for: {branch}")
    result = call_groq(branch, manifest, report)

    digest = hashlib.sha256(report.encode("utf-8")).hexdigest()[:16]
    update_readme(ROOT / "README.md", result["readme_section"])
    update_changelog(ROOT / "CHANGELOG.md", result["changelog_entry"], digest)

    print("README.md and CHANGELOG.md are ready.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Documentation generation failed: {exc}", file=sys.stderr)
        raise

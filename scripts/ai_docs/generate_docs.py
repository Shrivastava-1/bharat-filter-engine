import hashlib
import json
import os
import re
import sys
from pathlib import Path

from openai import OpenAI


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parents[2]
COMPARISON_DIR = ROOT / "comparison"

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Keep the request conservative for Groq's free/on-demand TPM limits.
MAX_REPORT_CHARS = 4200
MAX_MANIFEST_CHARS = 500
MAX_README_HEADINGS_CHARS = 1200
MAX_OUTPUT_TOKENS = 1400


# ============================================================
# FILE AND TEXT HELPERS
# ============================================================

def read_text(path):
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path, content):
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def safe_branch_filename(branch):
    # Match the naming convention used by inspect-changes.yml:
    # ${BRANCH//\//-}
    if not branch or branch in {".", ".."} or "\x00" in branch:
        raise RuntimeError(f"Invalid inspected branch name: {branch!r}")
    return branch.replace("/", "-")


def markdown_headings(text):
    headings = re.findall(r"(?m)^#{1,6}[ \t]+(.+?)\s*$", text)
    return headings


def report_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ============================================================
# INSPECTION ARTIFACT
# ============================================================

def load_inspection_report():
    branch = os.getenv("INSPECTED_BRANCH", "").strip()
    if not branch:
        raise RuntimeError("INSPECTED_BRANCH is missing.")

    safe_name = safe_branch_filename(branch)
    report_path = COMPARISON_DIR / f"branch-{safe_name}.md"
    manifest_path = COMPARISON_DIR / "manifest.md"

    if not report_path.is_file():
        available = sorted(p.name for p in COMPARISON_DIR.glob("branch-*.md"))
        raise RuntimeError(
            f"Inspection report for branch {branch!r} was not found. "
            f"Expected {report_path.name}. Available branch reports: {available}"
        )

    report = read_text(report_path)
    manifest = read_text(manifest_path)

    if not report.strip():
        raise RuntimeError(f"Inspection report is empty: {report_path}")

    # Confirm the report belongs to the branch that triggered this workflow.
    expected_heading = f"# Branch Comparison: {branch}"
    first_heading = next(
        (line.strip() for line in report.splitlines() if line.startswith("#")),
        "",
    )
    if first_heading != expected_heading:
        raise RuntimeError(
            "Inspection report branch mismatch. "
            f"Expected {expected_heading!r}, found {first_heading!r}."
        )

    return branch, manifest, report


# ============================================================
# GROQ CLIENT
# ============================================================

def create_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is missing. Add it in repository "
            "Settings > Secrets and variables > Actions."
        )

    return OpenAI(
        api_key=api_key,
        base_url=GROQ_BASE_URL,
        timeout=120.0,
        max_retries=2,
    )


def ask_groq(client, branch, manifest, report, readme):
    digest = report_digest(report)
    headings = markdown_headings(readme)
    headings_text = "\n".join(f"- {heading}" for heading in headings)
    headings_text = headings_text[:MAX_README_HEADINGS_CHARS]

    report_was_truncated = len(report) > MAX_REPORT_CHARS
    report_context = report[:MAX_REPORT_CHARS]

    system_prompt = """
You are a careful maintainer documenting a Python open-source project.

The branch comparison report is the source of truth. It includes commits,
changed files, statistics and actual Git diffs. Do not treat commit messages
or filenames alone as proof that a feature exists.

Return exactly one valid JSON object with these keys:
{
  "changelog_body": "Markdown bullets grouped under Added, Changed, Fixed, Removed or Security when evidence supports them",
  "readme_recent_changes": "A concise Markdown summary suitable for a README section"
}

Rules:
- Describe only changes supported by the supplied report.
- Do not invent features, APIs, commands, options, examples, installation
  instructions, compatibility claims or project behavior.
- If the report contains no meaningful product/library changes, say so
  briefly rather than inventing content.
- Keep changelog entries concise and specific.
- README summary must be useful to a new user and must not claim more than
  the diff proves.
- Return valid JSON only. No code fences or commentary.
"""

    user_prompt = f"""
INSPECTED BRANCH:
{branch}

INSPECTION REPORT SHA:
{digest}

MANIFEST EXCERPT:
{manifest[:MAX_MANIFEST_CHARS]}

BRANCH COMPARISON REPORT:
{report_context}

REPORT TRUNCATED:
{report_was_truncated}

EXISTING README HEADINGS:
{headings_text}

Return the requested JSON object. Do not reproduce the full README.
"""

    print("Sending branch inspection report to Groq...")
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=MAX_OUTPUT_TOKENS,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Groq returned an empty response.")

    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Groq returned invalid JSON: {exc}. "
            f"Response excerpt: {content[:500]}"
        ) from exc

    if not isinstance(result, dict):
        raise RuntimeError("Groq response must be a JSON object.")

    for key in ("changelog_body", "readme_recent_changes"):
        if not isinstance(result.get(key), str):
            raise RuntimeError(f"Groq response field {key!r} must be text.")

    return result, digest, report_was_truncated


# ============================================================
# CHANGELOG: ADD A TRACEABLE, IDEMPOTENT UNRELEASED BLOCK
# ============================================================

def update_changelog(original, generated_body, digest, branch):
    generated_body = generated_body.strip()
    if not generated_body:
        raise RuntimeError("Groq generated an empty changelog body.")

    marker = f"<!-- groq-inspection:{digest} -->"

    # A rerun for the same report must not duplicate the same entries.
    if marker in original:
        print("This inspection report is already recorded in CHANGELOG.md.")
        return original

    generated_body = re.sub(
        r"(?im)^#{1,6}[ \t]*\[Unreleased\][ \t]*$",
        "",
        generated_body,
    ).strip()

    block = (
        f"{marker}\n"
        f"<!-- inspected-branch: {branch} -->\n"
        f"{generated_body}"
    )

    match = re.search(
        r"(?m)^(#{1,6})[ \t]+\[Unreleased\][ \t]*$",
        original,
    )

    if match:
        heading_level = len(match.group(1))
        next_heading = re.compile(
            rf"(?m)^#{{1,{heading_level}}}[ \t]+"
        ).search(original, match.end())
        section_end = next_heading.start() if next_heading else len(original)

        existing_body = original[match.end():section_end].strip()
        combined = block if not existing_body else existing_body + "\n\n" + block

        return (
            original[:match.end()]
            + "\n\n"
            + combined
            + "\n\n"
            + original[section_end:].lstrip("\n")
        ).rstrip() + "\n"

    title = re.search(r"(?m)^# .+$", original)
    if title:
        pos = title.end()
        return (
            original[:pos]
            + "\n\n## [Unreleased]\n\n"
            + block
            + "\n\n"
            + original[pos:].lstrip("\n")
        ).rstrip() + "\n"

    return "# Changelog\n\n## [Unreleased]\n\n" + block + "\n\n" + original.lstrip()


# ============================================================
# README: UPDATE ONLY A DEDICATED SECTION, PRESERVE EVERYTHING ELSE
# ============================================================

def update_readme(original, generated_summary, digest):
    generated_summary = generated_summary.strip()
    if not generated_summary:
        raise RuntimeError("Groq generated an empty README summary.")

    marker = f"<!-- groq-inspection:{digest} -->"
    section_heading = "## Recent Changes"

    # Do not duplicate the same inspection report on reruns.
    if marker in original:
        print("This inspection report is already recorded in README.md.")
        return original

    block = f"{section_heading}\n\n{marker}\n\n{generated_summary}\n"

    heading_match = re.search(
        r"(?m)^##[ \t]+Recent Changes[ \t]*$",
        original,
    )

    if heading_match:
        # Replace only the dedicated h2 section, stopping at the next h1/h2.
        next_section = re.compile(r"(?m)^#{1,2}[ \t]+").search(
            original, heading_match.end()
        )
        end = next_section.start() if next_section else len(original)

        return (
            original[:heading_match.start()]
            + block
            + "\n"
            + original[end:].lstrip("\n")
        ).rstrip() + "\n"

    # If absent, append a clearly scoped section without altering old content.
    return original.rstrip() + "\n\n" + block + "\n"


# ============================================================
# VALIDATION AND MAIN
# ============================================================

def validate(original_readme, new_readme, new_changelog):
    if not new_readme.strip():
        raise RuntimeError("README.md would be empty.")
    if not new_changelog.strip():
        raise RuntimeError("CHANGELOG.md would be empty.")

    # The README update must preserve all original text except any previous
    # dedicated Recent Changes section, which is intentionally replaced.
    if len(new_readme) < int(len(original_readme) * 0.90):
        raise RuntimeError(
            "README.md would shrink by more than 10%. Refusing to write."
        )

    if not re.search(r"(?m)^## \[Unreleased\]$", new_changelog):
        raise RuntimeError("CHANGELOG.md is missing ## [Unreleased].")


def main():
    print("=" * 65)
    print("Groq documentation generator - inspection artifact mode")
    print(f"Model: {MODEL}")
    print("=" * 65)

    branch, manifest, report = load_inspection_report()
    print(f"Using inspection report for branch: {branch}")
    print(f"Inspection report size: {len(report)} characters")

    readme_path = ROOT / "README.md"
    changelog_path = ROOT / "CHANGELOG.md"

    original_readme = read_text(readme_path)
    original_changelog = read_text(changelog_path)

    if not original_readme.strip():
        original_readme = "# Bharat Filter Engine\n\nDocumentation for the Bharat Filter Engine project.\n"

    client = create_groq_client()
    result, digest, truncated = ask_groq(
        client, branch, manifest, report, original_readme
    )

    if truncated:
        print(
            "WARNING: Inspection report exceeded the prompt limit; "
            "Groq received its beginning only. Review the report before merging."
        )

    new_changelog = update_changelog(
        original_changelog,
        result["changelog_body"],
        digest,
        branch,
    )
    new_readme = update_readme(
        original_readme,
        result["readme_recent_changes"],
        digest,
    )

    validate(original_readme, new_readme, new_changelog)

    # Write both files only after validation succeeds.
    write_text(changelog_path, new_changelog)
    write_text(readme_path, new_readme)

    print("Documentation generation completed.")
    print(f"Inspected branch: {branch}")
    print(f"README: {len(original_readme)} -> {len(new_readme)} characters")
    print(f"CHANGELOG: {len(original_changelog)} -> {len(new_changelog)} characters")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)

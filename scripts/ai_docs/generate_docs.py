import os
import subprocess
import sys
from pathlib import Path

from openai import OpenAI


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Conservative limits for Groq's 8,000 TPM service tier.
# These are character limits, not exact token counts.
MAX_DIFF_CHARS = 5000
MAX_SOURCE_CHARS = 4500
MAX_README_CHARS = 4000
MAX_CHANGELOG_CHARS = 2500
MAX_OUTPUT_TOKENS = 1200

EXCLUDED_DIRS = {
    ".git",
    ".github",
    "__pycache__",
    ".venv",
    "venv",
    "tests",
    "test",
    "build",
    "dist",
    "site-packages",
}


# ============================================================
# FILE AND GIT HELPERS
# ============================================================

def read_file(filename):
    path = ROOT / filename

    if not path.exists():
        return ""

    return path.read_text(encoding="utf-8")


def write_file(filename, content):
    path = ROOT / filename
    path.write_text(content.strip() + "\n", encoding="utf-8")


def run_git(args, check=True):
    result = subprocess.run(
        ["git"] + args,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if check and result.returncode != 0:
        raise RuntimeError(
            f"Git command failed: {' '.join(args)}\n"
            f"{result.stderr}"
        )

    return result.stdout.strip()


def get_latest_tag():
    tags = run_git(
        ["tag", "--list", "--sort=-version:refname"]
    )

    if not tags:
        raise RuntimeError(
            "No Git release tag found. "
            "Create a release tag before generating documentation."
        )

    latest_tag = tags.splitlines()[0]

    print(f"Latest release tag: {latest_tag}")

    return latest_tag


def collect_changes():
    print("Collecting Git changes...")

    latest_tag = get_latest_tag()

    commits = run_git([
        "log",
        f"{latest_tag}..HEAD",
        "--pretty=format:- %s (%h)",
        "-n",
        "30",
    ])

    changed_files = run_git([
        "diff",
        "--name-status",
        f"{latest_tag}..HEAD",
    ])

    diff = run_git([
        "diff",
        "--no-ext-diff",
        "--unified=2",
        f"{latest_tag}..HEAD",
        "--",
        "*.py",
        "*.toml",
        "*.cfg",
        "*.ini",
        "*.yml",
        "*.yaml",
        "*.md",
    ])

    if not commits and not changed_files:
        raise RuntimeError(
            f"No changes found after release tag {latest_tag}."
        )

    # Keep the most recent and relevant part of the diff.
    diff = diff[:MAX_DIFF_CHARS]

    return {
        "tag": latest_tag,
        "commits": commits[:2500],
        "files": changed_files[:2500],
        "diff": diff,
    }


def collect_source_context():
    print("Reading current source code...")

    context_parts = []
    total_chars = 0

    tracked_files = run_git(["ls-files"])

    allowed_extensions = {
        ".py",
        ".toml",
        ".cfg",
        ".ini",
    }

    for filename in tracked_files.splitlines():

        path = Path(filename)

        if path.suffix not in allowed_extensions:
            continue

        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue

        full_path = ROOT / path

        if not full_path.is_file():
            continue

        try:
            content = full_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        remaining = MAX_SOURCE_CHARS - total_chars

        if remaining <= 0:
            break

        content = content[:remaining]

        context_parts.append(
            f"\n--- FILE: {filename} ---\n{content}"
        )

        total_chars += len(content)

    return "\n".join(context_parts)


# ============================================================
# GROQ API
# ============================================================

def create_groq_client():

    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is missing. "
            "Add it to GitHub Actions Secrets."
        )

    return OpenAI(
        api_key=api_key,
        base_url=GROQ_BASE_URL,
        timeout=120.0,
        max_retries=2,
    )


def ask_groq(client, instructions, prompt):

    print("Sending request to Groq...")

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": instructions,
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0.2,
            max_tokens=MAX_OUTPUT_TOKENS,
        )

        content = response.choices[0].message.content

        if not content:
            raise RuntimeError("Groq returned an empty response.")

        return content.strip()

    except Exception as error:
        raise RuntimeError(
            f"Groq API request failed: {error}"
        ) from error


# ============================================================
# CHANGELOG GENERATION
# ============================================================

def generate_changelog(
    client,
    changes,
    existing_changelog,
    source_context,
):

    print("Generating CHANGELOG.md using Groq...")

    instructions = """
You are an expert open-source software documentation engineer.

Generate an accurate Markdown changelog.

Rules:
1. Use only information supported by the supplied Git history,
   changed files, source code, and existing changelog.
2. Never invent features, bug fixes, APIs, or release versions.
3. Add a new [Unreleased] section at the top.
4. Organize changes under suitable headings:
   Added, Changed, Fixed, Removed, Security.
5. Include only headings that have relevant changes.
6. Preserve all existing historical changelog entries.
7. Do not claim a release has been published unless evidence
   explicitly confirms it.
8. Return the complete CHANGELOG.md content.
9. Return Markdown only. Do not use code fences.
"""

    prompt = f"""
Create the updated CHANGELOG.md.

LATEST RELEASE TAG:
{changes["tag"]}

RECENT COMMITS:
{changes["commits"]}

CHANGED FILES:
{changes["files"]}

GIT DIFF:
{changes["diff"]}

SOURCE CODE CONTEXT:
{source_context[:2500]}

EXISTING CHANGELOG:
{existing_changelog}

Generate the complete updated changelog.
"""

    return ask_groq(client, instructions, prompt)


# ============================================================
# README GENERATION
# ============================================================

def generate_readme(
    client,
    changes,
    existing_readme,
    source_context,
):

    print("Generating README.md using Groq...")

    instructions = """
You are an expert technical writer for Python open-source projects.

Update the project's README.md using the supplied evidence.

Rules:
1. Preserve useful existing documentation.
2. Do not remove sections unless they are clearly obsolete.
3. Use the source code and Git changes to understand the project.
4. Document only functionality that actually exists.
5. Never invent installation commands, APIs, arguments,
   configuration options, or examples.
6. Keep examples consistent with the actual source code.
7. Improve clarity, formatting, and organization where useful.
8. Do not invent badges, statistics, or project links.
9. Return the complete README.md content.
10. Return Markdown only. Do not use code fences.
"""

    prompt = f"""
Update the README.md for this project.

LATEST RELEASE TAG:
{changes["tag"]}

RECENT COMMITS:
{changes["commits"]}

CHANGED FILES:
{changes["files"]}

GIT DIFF:
{changes["diff"]}

CURRENT SOURCE CODE:
{source_context}

EXISTING README:
{existing_readme}

Return the complete updated README.md.
"""

    return ask_groq(client, instructions, prompt)


# ============================================================
# VALIDATION
# ============================================================

def validate_document(
    filename,
    content,
    original_content,
):

    if not content or not content.strip():
        raise RuntimeError(
            f"{filename}: Generated document is empty."
        )

    content = content.strip()

    if content.startswith("```"):
        raise RuntimeError(
            f"{filename}: AI returned Markdown inside code fences."
        )

    if len(content) < 100:
        raise RuntimeError(
            f"{filename}: Generated document is too short."
        )

    if (
        original_content
        and len(original_content) > 500
        and len(content) < len(original_content) * 0.5
    ):
        raise RuntimeError(
            f"{filename}: Generated document is unexpectedly "
            "short compared with the existing document. "
            "Original file has been preserved."
        )

    if filename == "CHANGELOG.md":
        if "[Unreleased]" not in content:
            raise RuntimeError(
                "CHANGELOG.md does not contain an [Unreleased] section."
            )

    return content


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("Starting Groq documentation generator...")
    print(f"Model: {MODEL}")
    print("=" * 60)

    changes = collect_changes()

    print("Reading existing documentation...")

    existing_readme = read_file("README.md")[:MAX_README_CHARS]

    existing_changelog = read_file("CHANGELOG.md")[
        :MAX_CHANGELOG_CHARS
    ]

    source_context = collect_source_context()

    client = create_groq_client()

    # Generate both documents before modifying either file.
    new_changelog = generate_changelog(
        client,
        changes,
        existing_changelog,
        source_context,
    )

    new_readme = generate_readme(
        client,
        changes,
        existing_readme,
        source_context,
    )

    print("Validating generated documentation...")

    new_changelog = validate_document(
        "CHANGELOG.md",
        new_changelog,
        read_file("CHANGELOG.md"),
    )

    new_readme = validate_document(
        "README.md",
        new_readme,
        read_file("README.md"),
    )

    print("Validation successful.")

    print("Writing documentation files...")

    write_file("CHANGELOG.md", new_changelog)
    write_file("README.md", new_readme)

    print("=" * 60)
    print("Documentation generation completed successfully.")
    print("Updated files:")
    print("- README.md")
    print("- CHANGELOG.md")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        sys.exit(1)

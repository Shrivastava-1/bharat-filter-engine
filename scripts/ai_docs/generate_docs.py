import os
import re
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

# Conservative input limits for Groq's 8,000 TPM tier.
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
# FILE HELPERS
# ============================================================

def read_file(filename):
    path = ROOT / filename

    if not path.exists():
        return ""

    return path.read_text(
        encoding="utf-8",
        errors="replace",
    )


def write_file(filename, content):
    path = ROOT / filename

    path.write_text(
        content.strip() + "\n",
        encoding="utf-8",
    )


# ============================================================
# GIT HELPERS
# ============================================================

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

    tags = run_git([
        "tag",
        "--list",
        "--sort=-version:refname",
    ])

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

    return {
        "tag": latest_tag,
        "commits": commits[:2500],
        "files": changed_files[:2500],
        "diff": diff[:MAX_DIFF_CHARS],
    }


# ============================================================
# SOURCE CODE COLLECTION
# ============================================================

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

        if any(
            part in EXCLUDED_DIRS
            for part in path.parts
        ):
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
# GROQ CLIENT
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

        if not content or not content.strip():
            raise RuntimeError(
                "Groq returned an empty response."
            )

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

Generate ONLY a new Unreleased section for CHANGELOG.md.

Rules:
1. Start with ## [Unreleased].
2. Use only evidence from the supplied Git history,
   changed files, and source code.
3. Never invent features, bug fixes, or APIs.
4. Organize changes under suitable headings:
   Added, Changed, Fixed, Removed, Security.
5. Include only categories with actual changes.
6. Do not include previous release history.
7. Do not invent release versions or dates.
8. Return Markdown only, without code fences.
"""

    prompt = f"""
Generate the new Unreleased changelog section.

LATEST RELEASE TAG:
{changes["tag"]}

RECENT COMMITS:
{changes["commits"]}

CHANGED FILES:
{changes["files"]}

GIT DIFF:
{changes["diff"]}

SOURCE CODE:
{source_context[:2500]}

EXISTING CHANGELOG CONTEXT:
{existing_changelog[:MAX_CHANGELOG_CHARS]}

Return only the new Unreleased section.
"""

    return ask_groq(
        client,
        instructions,
        prompt,
    )


def merge_changelog(
    new_section,
    original_changelog,
):

    new_section = new_section.strip()

    # Remove accidental Markdown code fences.
    new_section = re.sub(
        r"^\s*```(?:markdown|md)?\s*",
        "",
        new_section,
        flags=re.IGNORECASE,
    )

    new_section = re.sub(
        r"\s*```\s*$",
        "",
        new_section,
    ).strip()

    if not re.search(
        r"(?im)^#{1,6}\s*\[Unreleased\]",
        new_section,
    ):
        raise RuntimeError(
            "Groq did not generate a valid "
            "[Unreleased] changelog heading."
        )

    history = original_changelog.strip()

    if history:

        # Remove the old Unreleased section only.
        # Preserve the title and all previous release sections.
        history = re.sub(
            r"(?ims)^#{1,6}\s*\[Unreleased\]"
            r".*?(?=^#{1,6}\s|\Z)",
            "",
            history,
            count=1,
        ).strip()

        if history:
            return new_section + "\n\n" + history

    return new_section


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
2. Do not remove important existing sections.
3. Use the source code and Git changes to understand the project.
4. Document only functionality that actually exists.
5. Never invent installation commands, APIs, arguments,
   configuration options, or examples.
6. Keep examples consistent with the actual source code.
7. Improve clarity and formatting where useful.
8. Do not invent badges, statistics, or project links.
9. Return the complete README.md content.
10. Return Markdown only, without code fences.
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

    return ask_groq(
        client,
        instructions,
        prompt,
    )


# ============================================================
# VALIDATION
# ============================================================

def validate_document(
    filename,
    content,
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

    if filename == "CHANGELOG.md":

        if not re.search(
            r"(?im)^#{1,6}\s*\[Unreleased\]",
            content,
        ):
            raise RuntimeError(
                "CHANGELOG.md does not contain "
                "a valid [Unreleased] heading."
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

    # Step 1: Collect changes.
    changes = collect_changes()

    # Step 2: Read original documentation.
    print("Reading existing documentation...")

    original_readme = read_file("README.md")
    original_changelog = read_file("CHANGELOG.md")

    existing_readme = original_readme[:MAX_README_CHARS]

    existing_changelog = original_changelog[
        :MAX_CHANGELOG_CHARS
    ]

    # Step 3: Collect source code.
    source_context = collect_source_context()

    # Step 4: Create Groq client.
    client = create_groq_client()

    # Step 5: Generate only the new changelog section.
    generated_section = generate_changelog(
        client,
        changes,
        existing_changelog,
        source_context,
    )

    # Step 6: Merge new section with original history.
    new_changelog = merge_changelog(
        generated_section,
        original_changelog,
    )

    # Step 7: Generate README.
    new_readme = generate_readme(
        client,
        changes,
        existing_readme,
        source_context,
    )

    # Step 8: Validate both documents.
    print("Validating generated documentation...")

    new_changelog = validate_document(
        "CHANGELOG.md",
        new_changelog,
    )

    new_readme = validate_document(
        "README.md",
        new_readme,
    )

    # Step 9: Write only after both documents pass validation.
    print("Validation successful.")

    print("Writing documentation files...")

    write_file(
        "CHANGELOG.md",
        new_changelog,
    )

    write_file(
        "README.md",
        new_readme,
    )

    print("=" * 60)
    print("Documentation generation completed successfully.")
    print("Updated files:")
    print("- README.md")
    print("- CHANGELOG.md")
    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print(
            f"\nERROR: {error}",
            file=sys.stderr,
        )

        sys.exit(1)

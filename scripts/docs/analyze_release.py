
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "release-analysis.json"

TAG_PATTERN = re.compile(
    r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$"
)


def git(*args, input_text=None):
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        input=input_text,
        check=True
    )

    return result.stdout


def get_previous_tag(current):
    tags = git(
        "-c",
        "versionsort.suffix=-",
        "tag",
        "--sort=-version:refname"
    ).splitlines()

    tags = [
        tag for tag in tags
        if TAG_PATTERN.fullmatch(tag)
    ]

    if current not in tags:
        raise ValueError(f"Tag not found: {current}")

    index = tags.index(current)

    return tags[index + 1] if index + 1 < len(tags) else None


def get_revision(previous, current):
    if previous:
        return f"{previous}..{current}"

    # First release: compare against an empty Git tree.
    empty_tree = git(
        "hash-object",
        "-t",
        "tree",
        "--stdin",
        input_text=""
    ).strip()

    return f"{empty_tree}..{current}"


def get_changed_files(revision, path):
    output = git(
        "diff",
        "--find-renames",
        "--name-status",
        revision,
        "--",
        path
    )

    files = []

    for line in output.splitlines():
        parts = line.split("\t")

        if len(parts) >= 2:
            files.append({
                "status": parts[0],
                "file": parts[-1]
            })

    return files


def get_diff(revision, path, limit):
    return git(
        "diff",
        "--no-ext-diff",
        "--unified=5",
        revision,
        "--",
        path
    )[:limit]


def get_version(tag):
    content = git(
        "show",
        f"{tag}:lib/bharat_filter_engine/version.rb"
    )

    match = re.search(
        r"""VERSION\s*=\s*['"]([^'"]+)['"]""",
        content
    )

    if not match:
        raise ValueError(
            f"Version not found in version.rb for {tag}"
        )

    return match.group(1)


def main():
    current = (
        os.environ.get("RELEASE_TAG")
        or git(
            "describe",
            "--tags",
            "--exact-match"
        ).strip()
    )

    if not TAG_PATTERN.fullmatch(current):
        raise ValueError(
            f"Invalid release tag: {current}"
        )

    # Verify that the release tag exists.
    git(
        "rev-parse",
        "--verify",
        f"refs/tags/{current}^{{commit}}"
    )

    previous = get_previous_tag(current)
    version = get_version(current)

    if current != f"v{version}":
        raise ValueError(
            f"Tag/version mismatch: {current} != v{version}"
        )

    revision = get_revision(previous, current)

    # Analyze source and test changes.
    lib_files = get_changed_files(
        revision,
        "lib/"
    )

    spec_files = get_changed_files(
        revision,
        "spec/"
    )

    # Analyze other relevant project files.
    project_paths = [
        "Gemfile",
        "Gemfile.lock",
        "*.gemspec",
        ".github/",
        "scripts/",
        "README.md",
        "CHANGELOG.md"
    ]

    project_files = []

    for path in project_paths:
        project_files.extend(
            get_changed_files(revision, path)
        )

    has_relevant_changes = bool(
        lib_files or spec_files or project_files
    )

    analysis = {
        "version": version,
        "tag": current,
        "previous_tag": previous,
        "first_release": previous is None,

        "has_lib_changes": bool(lib_files),
        "has_spec_changes": bool(spec_files),
        "has_project_changes": bool(project_files),
        "has_relevant_changes": has_relevant_changes,

        "lib_files": lib_files,
        "lib_diff": get_diff(
            revision,
            "lib/",
            80000
        ),

        "spec_files": spec_files,
        "spec_diff": get_diff(
            revision,
            "spec/",
            30000
        ),

        "project_files": project_files
    }

    OUTPUT.write_text(
        json.dumps(
            analysis,
            indent=2
        ),
        encoding="utf-8"
    )

    print(f"Release: {current}")
    print(f"Previous: {previous or 'Initial release'}")
    print(f"First release: {previous is None}")
    print(f"Changed lib files: {len(lib_files)}")
    print(f"Changed spec files: {len(spec_files)}")
    print(f"Changed project files: {len(project_files)}")
    print(f"Relevant changes: {has_relevant_changes}")
    print(f"Analysis saved to: {OUTPUT}")


if __name__ == "__main__":
    main()


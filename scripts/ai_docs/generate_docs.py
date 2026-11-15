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

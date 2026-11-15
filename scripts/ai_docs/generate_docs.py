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

MAX_REPORT_CHARS = 6000
MAX_README_CONTEXT_CHARS = 2200
MAX_OUTPUT_TOKENS = 1800


# ============================================================
# FILE HELPERS
# ============================================================

def read_text(path):
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path, content):
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def readme_sections(readme):
    """Return Markdown headings and short excerpts for model context."""
    matches = list(re.finditer(r"(?m)^(#{1,6})[ \t]+(.+?)\s*$", readme))
    sections = []
    used = 0

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(readme)
        heading = match.group(2).strip()
        body = readme[start:end].strip()
        excerpt_budget = min(500, MAX_README_CONTEXT_CHARS - used)

        if excerpt_budget <= 0:
            break

        excerpt = body[:excerpt_budget]
        sections.append({
            "heading": heading,
            "level": len(match.group(1)),
            "excerpt": excerpt,
        })
        used += len(excerpt)

    return sections


# ============================================================
# INSPECTION ARTIFACT INPUT
# ============================================================

def get_inspected_branch():
    branch = os.getenv("INSPECTED_BRANCH", "").strip()

    if not branch:
        raise RuntimeError(
            "INSPECTED_BRANCH is missing. "
            "This script must run after the Inspect Git Changes workflow."
        )

    return branch


def load_inspection_report():
    branch = get_inspected_branch()
    safe_branch = branch.replace("/", "-")
    report_path = COMPARISON_DIR / f"branch-{safe_branch}.md"

    if not report_path.exists():
        available = sorted(
            path.name for path in COMPARISON_DIR.glob("*.md")
        )

        raise RuntimeError(
            f"No branch comparison report was found for '{branch}'. "
            f"Expected: {report_path.name}. "
            f"Available reports: {available}. "
            "Run Inspect Git Changes - V2 on a non-default branch "

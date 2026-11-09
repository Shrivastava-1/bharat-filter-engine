import json
import os
import urllib.error
import urllib.request


MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
API_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{MODEL}:generateContent"
)


def generate(analysis):
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured")

    prompt = f"""
Analyze this Ruby gem release.

Use lib_diff as the primary source of truth.
Use spec_diff only as supporting evidence.

Rules:
- Document actual user-facing functionality.
- Focus on public APIs, filters, associations, search behavior and fixes.
- Ignore CI, GitHub workflows, linting and repository maintenance.
- Never invent functionality.
- Do not describe internal file changes as user-facing features.
- Return concise, meaningful release notes.
- Return valid JSON only.

Expected JSON:
{{
  "highlights": [],
  "changelog": {{
    "Added": [],
    "Changed": [],
    "Fixed": [],
    "Removed": []
  }}
}}

Release analysis:
{json.dumps(analysis, ensure_ascii=False)}
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "temperature": 0.2
        }
    }

    request = urllib.request.Request(
        f"{API_URL}?key={api_key}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode("utf-8"))

        content = result["candidates"][0]["content"]["parts"][0]["text"]
        documentation = json.loads(content)

        if not isinstance(documentation.get("highlights"), list):
            raise ValueError("Invalid highlights format")

        changelog = documentation.get("changelog")

        if not isinstance(changelog, dict):
            raise ValueError("Invalid changelog format")

        for category in ("Added", "Changed", "Fixed", "Removed"):
            if not isinstance(changelog.get(category, []), list):
                raise ValueError(f"Invalid {category} format")

        return documentation

    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Gemini API HTTP {error.code}: {details}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Gemini API connection failed: {error.reason}"
        ) from error

    except TimeoutError as error:
        raise RuntimeError(
            f"Gemini API timed out after 90 seconds: {error}"
        ) from error

    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"Invalid Gemini API response: {error}"
        ) from error

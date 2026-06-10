"""
Smart Sourcing service for RAAF.

Generates optimized Indeed Smart Sourcing boolean search queries using Claude AI
for a given job description and title. Also builds the Indeed Smart Sourcing
search URL so the recruiter can launch searches in their browser.

No Indeed API is called — this is a URL-launcher + AI-query-generator workflow.
"""

import json
import os
import urllib.parse
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# US state abbreviations used for country detection
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
}


def _is_us_location(location: str) -> bool:
    """Return True if the location string looks like a US location."""
    if not location:
        return False
    loc = location.strip().upper()
    # Check for explicit country markers
    if loc.endswith(", US") or loc.endswith(", USA") or "UNITED STATES" in loc:
        return True
    # Check for a state abbreviation at end of string
    parts = [p.strip(" ,").upper() for p in loc.replace(",", " ").split()]
    return any(p in _US_STATES for p in parts)


def _get_api_key() -> str:
    """Resolve the Anthropic API key from env or credentials file."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        config_path = Path(__file__).parent.parent.parent / "config" / "claude_credentials.yaml"
        if config_path.exists():
            with open(config_path, "r") as f:
                creds = yaml.safe_load(f)
            api_key = creds.get("api", {}).get("api_key", "")
            if not api_key or api_key.startswith("YOUR_"):
                api_key = None
    if not api_key:
        raise ValueError(
            "Anthropic API key not found. Set ANTHROPIC_API_KEY environment variable "
            "or configure config/claude_credentials.yaml."
        )
    return api_key


# ---------------------------------------------------------------------------
# Default fallback queries
# ---------------------------------------------------------------------------

def _default_queries(job_title: str, location: str) -> list[dict]:
    """Return a minimal fallback list when Claude parsing fails."""
    return [
        {
            "name": "Primary title search",
            "query": f'"{job_title}"',
            "location": location,
            "rationale": "Exact job title match (fallback — Claude response could not be parsed).",
        }
    ]


# ---------------------------------------------------------------------------
# SmartSourcingService
# ---------------------------------------------------------------------------

class SmartSourcingService:
    """Generates Indeed Smart Sourcing queries using Claude and builds search URLs."""

    # Model — haiku is sufficient for lightweight query generation
    MODEL = "claude-haiku-4-5"

    _PROMPT_TEMPLATE = """You are an expert technical recruiter with deep knowledge of Indeed Smart Sourcing boolean search syntax.

## Task
Generate 5 optimized boolean search queries for Indeed Smart Sourcing to proactively find candidates for the following role.

## Job Title
{job_title}

## Location
{location}

## Job Description
{jd_text}

{framework_section}

## Indeed Smart Sourcing Boolean Syntax Rules
- Use AND, OR, NOT in uppercase
- Use double quotes for exact phrases: "customer success manager"
- Use parentheses to group OR alternatives: (CSM OR "customer success")
- NOT excludes terms: NOT intern NOT junior
- Keep each query under 500 characters for reliability

## Instructions
Create 5 distinct queries that approach the role from different angles:
1. One using exact job title variants and seniority signals
2. One focused on required technical skills or tools
3. One using industry-specific terminology and domain experience
4. One targeting adjacent roles that transition naturally to this position
5. One using key certifications, credentials, or achievement language

For each query return:
- name: short descriptive label (3-6 words)
- query: the boolean search string
- location: the location to search (use the location provided above)
- rationale: 1-2 sentences explaining what this query finds and why

## Output Format
Return ONLY a valid JSON array. No prose, no markdown, no code blocks — just the raw JSON array.

[
  {{
    "name": "Title + Seniority",
    "query": "...",
    "location": "{location}",
    "rationale": "..."
  }},
  ...
]"""

    async def generate_queries(
        self,
        jd_text: str,
        job_title: str,
        location: str,
        framework_text: str = "",
    ) -> list[dict]:
        """
        Generate 5 optimized Indeed Smart Sourcing search queries using Claude.

        Args:
            jd_text: Extracted text from the job description.
            job_title: The job title for the role.
            location: The job location string.
            framework_text: Optional assessment framework text for additional context.

        Returns:
            List of dicts with keys: name, query, location, rationale.
        """
        try:
            from anthropic import AsyncAnthropic
        except ImportError:
            raise ImportError("anthropic library is required. Run: pip install anthropic")

        framework_section = ""
        if framework_text and framework_text.strip():
            snippet = framework_text.strip()[:1200]
            framework_section = f"## Assessment Framework Context (excerpt)\n{snippet}\n"

        # Truncate very long JDs to keep the request fast
        jd_snippet = jd_text.strip()[:3000] if jd_text else "(no job description provided)"

        prompt = self._PROMPT_TEMPLATE.format(
            job_title=job_title,
            location=location or "Canada",
            jd_text=jd_snippet,
            framework_section=framework_section,
        )

        try:
            client = AsyncAnthropic(api_key=_get_api_key())
            message = await client.messages.create(
                model=self.MODEL,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text.strip()

            # Strip markdown code fences if Claude wrapped in them
            if raw.startswith("```"):
                lines = raw.splitlines()
                lines = [line for line in lines if not line.startswith("```")]
                raw = "\n".join(lines).strip()

            queries = json.loads(raw)

            # Validate and normalise structure
            validated = []
            for q in queries:
                if isinstance(q, dict) and "query" in q:
                    validated.append({
                        "name": str(q.get("name", "Query")),
                        "query": str(q.get("query", "")),
                        "location": str(q.get("location", location or "")),
                        "rationale": str(q.get("rationale", "")),
                    })
            if validated:
                return validated

        except Exception:
            # Fall through to default on any failure (parse error, API error, etc.)
            pass

        return _default_queries(job_title, location or "Canada")

    def build_search_url(
        self,
        query: str,
        location: str,
        country: Optional[str] = None,
    ) -> str:
        """
        Build an Indeed Smart Sourcing search URL.

        Args:
            query: The boolean search query string.
            location: The location to search.
            country: 'ca' (default) or 'us'. Auto-detected from location if None.

        Returns:
            Fully-encoded Indeed Smart Sourcing URL.
        """
        if country is None:
            country = "us" if _is_us_location(location) else "ca"

        params = urllib.parse.urlencode({"q": query, "l": location})

        if country == "us":
            base = "https://www.indeed.com/employers/smart-sourcing/search"
        else:
            base = "https://ca.indeed.com/employers/smart-sourcing/search"

        return f"{base}?{params}"

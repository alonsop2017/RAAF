#!/usr/bin/env python3
"""
Candidate repository search utility.
Searches across all assessed candidates to find matches for job descriptions.
Uses Claude API for intelligent matching.
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Handle imports whether run directly or as module
try:
    from scripts.utils.client_utils import list_clients, list_requisitions, get_assessments_path, get_requisition_config
    from scripts.utils.claude_client import ClaudeClient, ClaudeClientError
except ImportError:
    try:
        from utils.client_utils import list_clients, list_requisitions, get_assessments_path, get_requisition_config
        from utils.claude_client import ClaudeClient, ClaudeClientError
    except ImportError:
        from client_utils import list_clients, list_requisitions, get_assessments_path, get_requisition_config
        from claude_client import ClaudeClient, ClaudeClientError


# Candidate matching prompt
CANDIDATE_MATCHING_PROMPT = """You are an expert recruiter matching candidates to a job description.

## Job Description
{job_description}

## Candidates
Below are summaries of assessed candidates. For each candidate, analyze their fit for this role.

{candidate_summaries}

## Instructions
For each candidate, evaluate their match to the job description and provide:
1. A match score from 0-100 based on how well they fit the requirements
2. Key reasons why they match (2-4 points)
3. Potential gaps or concerns (1-3 points)
4. An overall recommendation category

Return a JSON array with this structure:
[
  {{
    "candidate_id": "<name_normalized from input>",
    "match_score": <0-100>,
    "recommendation": "<strong_match|good_match|partial_match|weak_match>",
    "match_reasons": ["reason 1", "reason 2"],
    "gaps": ["gap 1", "gap 2"],
    "summary": "<one sentence summary of fit>"
  }},
  ...
]

Sort by match_score descending. Return ONLY the JSON array, no other text."""


def load_candidate_repository(
    client_filter: str = None,
    req_filter: str = None,
    min_score: int = 0
) -> list[dict]:
    """
    Load all assessments from all clients/requisitions.

    Args:
        client_filter: Optional client code to filter by
        req_filter: Optional requisition ID to filter by
        min_score: Minimum assessment score to include (default 0)

    Returns:
        List of assessment dictionaries with source metadata
    """
    candidates = []

    clients = list_clients()
    if client_filter:
        clients = [c for c in clients if c == client_filter]

    for client_code in clients:
        try:
            requisitions = list_requisitions(client_code)
            if req_filter:
                requisitions = [r for r in requisitions if r == req_filter]

            for req_id in requisitions:
                try:
                    assessments_path = get_assessments_path(client_code, req_id, "individual")
                    if not assessments_path.exists():
                        continue

                    req_config = get_requisition_config(client_code, req_id)
                    req_title = req_config.get("job", {}).get("title", req_id)

                    for assessment_file in assessments_path.glob("*_assessment.json"):
                        try:
                            with open(assessment_file, "r", encoding="utf-8") as f:
                                assessment = json.load(f)

                            # Skip pending/incomplete assessments
                            if assessment.get("recommendation") == "PENDING":
                                continue

                            # Apply score filter
                            if assessment.get("percentage", 0) < min_score:
                                continue

                            # Add source metadata
                            assessment["_source"] = {
                                "client_code": client_code,
                                "req_id": req_id,
                                "req_title": req_title,
                                "file": assessment_file.name
                            }

                            candidates.append(assessment)

                        except (json.JSONDecodeError, IOError) as e:
                            continue

                except Exception as e:
                    continue

        except Exception as e:
            continue

    return candidates


def format_candidate_summary(assessment: dict) -> str:
    """Format an assessment into a concise summary for matching."""
    candidate = assessment.get("candidate", {})
    name = candidate.get("name", candidate.get("name_normalized", "Unknown"))
    name_normalized = candidate.get("name_normalized", "unknown")

    source = assessment.get("_source", {})
    original_req = source.get("req_title", source.get("req_id", "Unknown"))

    # Core metrics
    score = assessment.get("percentage", 0)
    recommendation = assessment.get("recommendation", "Unknown")

    # Key data points
    summary = assessment.get("summary", "")
    strengths = assessment.get("key_strengths", [])
    concerns = assessment.get("areas_of_concern", [])

    # Job stability
    stability = assessment.get("scores", {}).get("job_stability", {})
    stability_risk = stability.get("tenure_analysis", {}).get("risk_level", "Unknown")

    # Build summary
    text = f"""
### Candidate: {name} (ID: {name_normalized})
- Previous Assessment: {original_req} - Score: {score}% ({recommendation})
- Job Stability: {stability_risk} risk
- Summary: {summary}
- Key Strengths: {', '.join(strengths[:3]) if strengths else 'N/A'}
- Areas of Concern: {', '.join(concerns[:2]) if concerns else 'None noted'}
"""
    return text


def search_candidates(
    job_description: str,
    candidates: list[dict] = None,
    top_n: int = 20,
    model: str = None
) -> list[dict]:
    """
    Search candidates against a job description using AI matching.

    Args:
        job_description: The job description text to match against
        candidates: List of candidate assessments (loads all if None)
        top_n: Maximum number of results to return
        model: Optional model override

    Returns:
        List of match results sorted by score descending
    """
    # Load candidates if not provided
    if candidates is None:
        candidates = load_candidate_repository()

    if not candidates:
        return []

    # Format candidate summaries for the prompt
    candidate_summaries = []
    candidate_lookup = {}

    for assessment in candidates:
        name_normalized = assessment.get("candidate", {}).get("name_normalized", "")
        if not name_normalized:
            continue

        summary = format_candidate_summary(assessment)
        candidate_summaries.append(summary)
        candidate_lookup[name_normalized] = assessment

        # Limit input size for API
        if len(candidate_summaries) >= 50:
            break

    if not candidate_summaries:
        return []

    # Build prompt
    prompt = CANDIDATE_MATCHING_PROMPT.format(
        job_description=job_description[:5000],  # Limit JD length
        candidate_summaries="\n".join(candidate_summaries)
    )

    # Call Claude API
    client = ClaudeClient()
    anthropic_client = client._get_client()

    message = anthropic_client.messages.create(
        model=model or client.model,
        max_tokens=4000,
        temperature=0.3,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

    # Parse response
    response_text = message.content[0].text.strip()

    # Extract JSON array
    json_match = re.search(r'\[[\s\S]*\]', response_text)
    if not json_match:
        raise ValueError("Could not parse matching results")

    matches = json.loads(json_match.group())

    # Enrich results with full candidate data
    enriched_results = []
    for match in matches[:top_n]:
        candidate_id = match.get("candidate_id", "")
        if candidate_id in candidate_lookup:
            assessment = candidate_lookup[candidate_id]
            source = assessment.get("_source", {})

            enriched_results.append({
                "candidate_id": candidate_id,
                "name": assessment.get("candidate", {}).get("name", candidate_id),
                "match_score": match.get("match_score", 0),
                "recommendation": match.get("recommendation", "unknown"),
                "match_reasons": match.get("match_reasons", []),
                "gaps": match.get("gaps", []),
                "summary": match.get("summary", ""),
                "original_assessment": {
                    "client_code": source.get("client_code"),
                    "req_id": source.get("req_id"),
                    "req_title": source.get("req_title"),
                    "score": assessment.get("percentage", 0),
                    "recommendation": assessment.get("recommendation")
                }
            })

    return enriched_results


def search_candidates_simple(
    job_description: str,
    candidates: list[dict] = None,
    keywords: list[str] = None
) -> list[dict]:
    """
    Simple keyword-based candidate search (no AI required).
    Useful as a fallback or for quick filtering.

    Args:
        job_description: Job description text
        candidates: List of candidate assessments
        keywords: Optional list of keywords to search for

    Returns:
        List of candidates with match scores
    """
    if candidates is None:
        candidates = load_candidate_repository()

    if not candidates:
        return []

    # Extract keywords from JD if not provided
    if not keywords:
        # Simple keyword extraction
        jd_lower = job_description.lower()
        # Common skill/requirement patterns
        keywords = []
        for word in jd_lower.split():
            word = re.sub(r'[^a-z]', '', word)
            if len(word) > 3 and word not in ['with', 'that', 'this', 'from', 'have', 'will', 'your', 'they', 'been']:
                keywords.append(word)
        keywords = list(set(keywords))[:30]

    results = []
    for assessment in candidates:
        # Get searchable text from assessment
        search_text = ""
        search_text += assessment.get("summary", "") + " "
        search_text += " ".join(assessment.get("key_strengths", [])) + " "

        # Include resume preview if available
        resume_preview = assessment.get("resume_text_preview", "")
        search_text += resume_preview + " "

        search_text = search_text.lower()

        # Count keyword matches
        matches = 0
        matched_keywords = []
        for keyword in keywords:
            if keyword in search_text:
                matches += 1
                matched_keywords.append(keyword)

        if matches > 0:
            source = assessment.get("_source", {})
            results.append({
                "candidate_id": assessment.get("candidate", {}).get("name_normalized", ""),
                "name": assessment.get("candidate", {}).get("name", "Unknown"),
                "match_score": min(100, int((matches / len(keywords)) * 100)),
                "matched_keywords": matched_keywords[:10],
                "recommendation": "partial_match" if matches < len(keywords) / 2 else "good_match",
                "original_assessment": {
                    "client_code": source.get("client_code"),
                    "req_id": source.get("req_id"),
                    "req_title": source.get("req_title"),
                    "score": assessment.get("percentage", 0),
                    "recommendation": assessment.get("recommendation")
                }
            })

    # Sort by match score
    results.sort(key=lambda x: x["match_score"], reverse=True)

    return results


def search_by_name(
    query: str,
    candidates: list[dict] = None
) -> list[dict]:
    """
    Search candidates by name (partial match, case-insensitive).

    Args:
        query: Name search query (partial match)
        candidates: List of candidate assessments (loads all if None)

    Returns:
        List of matching candidates with source metadata
    """
    if candidates is None:
        candidates = load_candidate_repository()

    if not candidates or not query:
        return []

    query_lower = query.lower().strip()
    results = []

    for assessment in candidates:
        candidate_info = assessment.get("candidate", {})
        name = candidate_info.get("name", "")
        name_normalized = candidate_info.get("name_normalized", "")

        # Check both name and normalized name
        if query_lower in name.lower() or query_lower in name_normalized.lower():
            source = assessment.get("_source", {})
            results.append({
                "candidate_id": name_normalized,
                "name": name or name_normalized.replace("_", " ").title(),
                "match_type": "name",
                "original_assessment": {
                    "client_code": source.get("client_code"),
                    "req_id": source.get("req_id"),
                    "req_title": source.get("req_title"),
                    "score": assessment.get("percentage", 0),
                    "recommendation": assessment.get("recommendation")
                },
                "summary": assessment.get("summary", ""),
                "key_strengths": assessment.get("key_strengths", [])[:3]
            })

    # Sort by name for consistent results
    results.sort(key=lambda x: x["name"].lower())

    return results


def search_by_text(
    query: str,
    candidates: list[dict] = None,
    search_fields: list[str] = None
) -> list[dict]:
    """
    Search candidates by text in name, skills, summary, or resume content.
    Scores results by number of keyword matches.

    Args:
        query: Search query (keywords, skills, experience terms)
        candidates: List of candidate assessments (loads all if None)
        search_fields: Optional list of fields to search. Defaults to all fields.
                      Options: 'name', 'summary', 'strengths', 'resume'

    Returns:
        List of candidates sorted by match score (number of keyword hits)
    """
    if candidates is None:
        candidates = load_candidate_repository()

    if not candidates or not query:
        return []

    if search_fields is None:
        search_fields = ['name', 'summary', 'strengths', 'resume']

    # Extract search keywords (words 3+ chars, skip common words)
    stop_words = {'the', 'and', 'for', 'with', 'that', 'this', 'from', 'have',
                  'will', 'your', 'they', 'been', 'are', 'was', 'were', 'can'}
    keywords = []
    for word in query.lower().split():
        word = re.sub(r'[^a-z0-9]', '', word)
        if len(word) >= 2 and word not in stop_words:
            keywords.append(word)

    if not keywords:
        return []

    results = []

    for assessment in candidates:
        candidate_info = assessment.get("candidate", {})
        name = candidate_info.get("name", "")
        name_normalized = candidate_info.get("name_normalized", "")

        # Build searchable text based on requested fields
        search_text_parts = []

        if 'name' in search_fields:
            search_text_parts.append(name)
            search_text_parts.append(name_normalized.replace("_", " "))

        if 'summary' in search_fields:
            search_text_parts.append(assessment.get("summary", ""))

        if 'strengths' in search_fields:
            search_text_parts.extend(assessment.get("key_strengths", []))
            search_text_parts.extend(assessment.get("areas_of_concern", []))

        if 'resume' in search_fields:
            search_text_parts.append(assessment.get("resume_text_preview", ""))

        search_text = " ".join(search_text_parts).lower()

        # Count keyword matches
        matched_keywords = []
        for keyword in keywords:
            if keyword in search_text:
                matched_keywords.append(keyword)

        if matched_keywords:
            source = assessment.get("_source", {})
            match_score = int((len(matched_keywords) / len(keywords)) * 100)

            results.append({
                "candidate_id": name_normalized,
                "name": name or name_normalized.replace("_", " ").title(),
                "match_score": match_score,
                "matched_keywords": matched_keywords,
                "match_type": "text",
                "recommendation": "strong_match" if match_score >= 75 else "good_match" if match_score >= 50 else "partial_match",
                "original_assessment": {
                    "client_code": source.get("client_code"),
                    "req_id": source.get("req_id"),
                    "req_title": source.get("req_title"),
                    "score": assessment.get("percentage", 0),
                    "recommendation": assessment.get("recommendation")
                },
                "summary": assessment.get("summary", ""),
                "key_strengths": assessment.get("key_strengths", [])[:3]
            })

    # Sort by match score descending
    results.sort(key=lambda x: x["match_score"], reverse=True)

    return results


def get_repository_stats() -> dict:
    """Get statistics about the candidate repository."""
    candidates = load_candidate_repository()

    stats = {
        "total_candidates": len(candidates),
        "by_recommendation": {},
        "by_client": {},
        "by_requisition": {},
        "avg_score": 0
    }

    if not candidates:
        return stats

    total_score = 0
    for c in candidates:
        # By recommendation
        rec = c.get("recommendation", "Unknown")
        stats["by_recommendation"][rec] = stats["by_recommendation"].get(rec, 0) + 1

        # By client
        source = c.get("_source", {})
        client = source.get("client_code", "Unknown")
        stats["by_client"][client] = stats["by_client"].get(client, 0) + 1

        # By requisition
        req = f"{client}/{source.get('req_id', 'Unknown')}"
        stats["by_requisition"][req] = stats["by_requisition"].get(req, 0) + 1

        # Total score
        total_score += c.get("percentage", 0)

    stats["avg_score"] = round(total_score / len(candidates), 1)

    return stats


def test_search():
    """Test the search functionality."""
    print("Loading candidate repository...")
    candidates = load_candidate_repository()
    print(f"Found {len(candidates)} assessed candidates")

    if candidates:
        print("\nRepository stats:")
        stats = get_repository_stats()
        print(f"  Total: {stats['total_candidates']}")
        print(f"  Average score: {stats['avg_score']}%")
        print(f"  By recommendation: {stats['by_recommendation']}")

        # Test simple search
        print("\nTesting simple search...")
        results = search_candidates_simple(
            "Looking for a customer success manager with SaaS experience",
            candidates
        )
        print(f"Found {len(results)} matches")
        for r in results[:3]:
            print(f"  - {r['name']}: {r['match_score']}% match")


if __name__ == "__main__":
    test_search()

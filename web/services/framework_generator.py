"""
AI-powered assessment framework generator.
Uses Claude to create a role-specific assessment framework from a job description.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

import yaml


FRAMEWORK_GENERATION_PROMPT = """You are an expert recruitment assessment specialist. Your task is to create a detailed, structured assessment framework for evaluating candidate resumes against a specific job description.

## Job Description
{jd_text}

## Additional Context
- Job Title: {job_title}
- Department: {department}
- Location: {location}
- Minimum Experience: {experience_years_min} years
- Education Requirement: {education}

## Instructions

Create a comprehensive assessment framework in markdown format that follows the structure below. The framework must:

1. Be specifically tailored to the job description provided
2. Include 6 scoring categories totaling 100 points
3. Have detailed scoring criteria with specific, measurable benchmarks drawn from the JD
4. Include role-specific interview questions

The 6 categories MUST be:
- Core Experience & Qualifications (25 points)
- Technical & Analytical Competencies (20 points)
- Relationship & Communication Skills (20 points)
- Strategic & Business Acumen (15 points)
- Job Stability Assessment (10 points)
- Cultural Fit & Soft Skills (10 points)

For each category, create 3-4 sub-criteria with point allocations that sum to the category total.
Make the scoring guides specific to this role - reference actual skills, tools, industry terms, and experience levels from the job description.

## Required Output Format

Return the framework in this exact markdown structure:

# Assessment Framework
# [Job Title]

## Framework Metadata

```yaml
framework_id: [role_id]
version: "1.0"
created_date: {today_date}
role_type: [Job Title]
total_points: 100
generated: true
```

## Framework Overview

[2-3 sentence overview of the framework and what it evaluates]

---

## Score Distribution Summary

| Assessment Category | Points | Weight |
|---------------------|--------|--------|
| Core Experience & Qualifications | 25 | 25% |
| Technical & Analytical Competencies | 20 | 20% |
| Relationship & Communication Skills | 20 | 20% |
| Strategic & Business Acumen | 15 | 15% |
| Job Stability Assessment | 10 | 10% |
| Cultural Fit & Soft Skills | 10 | 10% |
| **TOTAL** | **100** | **100%** |

---

## Scoring Categories

### 1. Core Experience & Qualifications (25 points)

[Description of what this category evaluates for this specific role]

#### 1.1 [Criterion Name] (X points)

| [Level Description] | Points | Score |
|---|---|---|
| [Excellent level - specific to role] | X | |
| [Good level] | X | |
| [Adequate level] | X | |
| [Below threshold] | X | |

[Continue with 1.2, 1.3, 1.4 sub-criteria...]

**Category Total: 25 points**

---

[Continue with categories 2-6 following the same pattern...]

### 5. Job Stability Assessment (10 points)

[Always use the standard tenure-based scoring:]

| Average Tenure (Last 3 Roles) | Points | Risk Level |
|-------------------------------|--------|------------|
| 4+ years average | 10 | Low Risk |
| 3 to 3.9 years average | 8 | Low-Medium Risk |
| 2 to 2.9 years average | 6 | Medium Risk |
| 1.5 to 1.9 years average | 4 | Medium-High Risk |
| 1 to 1.4 years average | 2 | High Risk |
| Less than 1 year average | 0 | Very High Risk |

**Category Total: 10 points**

---

[Category 6...]

## Recommendation Thresholds

| Score Range | Classification | Recommendation |
|-------------|----------------|----------------|
| 85-100 | Exceptional Candidate | Strong hire recommendation; proceed to final interviews |
| 70-84 | Strong Candidate | Recommend advancing; address gaps in subsequent interviews |
| 55-69 | Qualified Candidate | Consider if talent pool is limited; development required |
| 40-54 | Below Threshold | Not recommended unless exceptional circumstances |
| Below 40 | Does Not Meet Requirements | Do not advance |

---

## Appendix: Interview Questions by Category

[6-12 role-specific behavioral interview questions organized by category]

---

## Usage Instructions

1. Read the candidate's resume thoroughly
2. Score each criterion based on evidence found in the resume
3. Document specific evidence for each score assigned
4. Calculate category subtotals and overall total
5. Apply recommendation threshold based on total score
6. Note key strengths, concerns, and interview focus areas

---

Return ONLY the markdown framework. Do not include any other text or commentary."""


def _get_claude_client():
    """Get an Anthropic client instance."""
    try:
        import anthropic
    except ImportError:
        raise ImportError("anthropic library is required. Run: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Try credentials file
        config_path = Path(__file__).parent.parent.parent / "config" / "claude_credentials.yaml"
        if config_path.exists():
            with open(config_path, "r") as f:
                creds = yaml.safe_load(f)
            api_key = creds.get("api", {}).get("api_key", "")
            if not api_key or api_key.startswith("YOUR_"):
                api_key = None

    if not api_key:
        raise ValueError(
            "Claude API key not found. Set ANTHROPIC_API_KEY environment variable "
            "or configure config/claude_credentials.yaml"
        )

    return anthropic.Anthropic(api_key=api_key)


async def generate_framework(
    jd_text: str,
    job_title: str,
    department: str = "",
    location: str = "",
    experience_years_min: int = 0,
    education: str = "",
    model: str = "claude-sonnet-4-20250514",
) -> str:
    """
    Generate an assessment framework from a job description using Claude.

    Args:
        jd_text: Extracted text from the job description document.
        job_title: The job title for the role.
        department: Department name.
        location: Job location.
        experience_years_min: Minimum years of experience required.
        education: Education requirements.
        model: Claude model to use.

    Returns:
        Generated assessment framework as markdown text.
    """
    from datetime import date

    client = _get_claude_client()

    prompt = FRAMEWORK_GENERATION_PROMPT.format(
        jd_text=jd_text,
        job_title=job_title,
        department=department or "Not specified",
        location=location or "Not specified",
        experience_years_min=experience_years_min,
        education=education or "Not specified",
        today_date=date.today().isoformat(),
    )

    message = client.messages.create(
        model=model,
        max_tokens=8192,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )

    framework_text = message.content[0].text.strip()

    # Remove any markdown code block wrappers if present
    if framework_text.startswith("```"):
        lines = framework_text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        framework_text = "\n".join(lines)

    return framework_text

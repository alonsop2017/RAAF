#!/usr/bin/env python3
"""
Claude API client wrapper for automated candidate assessments.
Handles API calls, prompt construction, and response parsing.
"""

import json
import os
import re
from pathlib import Path
from typing import Optional

import yaml

# Handle imports whether run directly or as module
try:
    from client_utils import get_config_path, get_settings
except ImportError:
    from utils.client_utils import get_config_path, get_settings


class ClaudeClientError(Exception):
    """Base exception for Claude client errors."""
    pass


class ClaudeAPIError(ClaudeClientError):
    """API call failed."""
    def __init__(self, message: str, status_code: int = None, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ClaudeResponseError(ClaudeClientError):
    """Failed to parse API response."""
    pass


# Assessment prompt template
ASSESSMENT_PROMPT = """You are an expert recruitment assessment specialist. Your task is to evaluate a candidate's resume against a specific job assessment framework and provide a detailed, evidence-based scoring.

## Assessment Framework
{framework_text}

## Candidate Resume
{resume_text}

## Instructions
1. Carefully read the assessment framework to understand the scoring criteria
2. Analyze the resume thoroughly for evidence supporting each criterion
3. Provide specific evidence from the resume for each score
4. Calculate accurate totals and percentages
5. Be objective and evidence-based in your assessments

## Required Output Format
Return a valid JSON object with the following structure. Include ONLY the JSON, no other text:

{{
  "scores": {{
    "core_experience": {{
      "score": <number>,
      "max": 25,
      "breakdown": {{
        "years_experience": {{"score": <number>, "max": 10, "evidence": "<quote or reference from resume>"}},
        "industry_alignment": {{"score": <number>, "max": 8, "evidence": "<quote or reference>"}},
        "education": {{"score": <number>, "max": 4, "evidence": "<quote or reference>"}},
        "certifications": {{"score": <number>, "max": 3, "evidence": "<quote or reference>"}}
      }},
      "notes": "<summary of core experience assessment>"
    }},
    "technical_competencies": {{
      "score": <number>,
      "max": 20,
      "breakdown": {{
        "core_technical": {{"score": <number>, "max": 8, "evidence": "<quote or reference>"}},
        "tools_systems": {{"score": <number>, "max": 7, "evidence": "<quote or reference>"}},
        "analytical_skills": {{"score": <number>, "max": 5, "evidence": "<quote or reference>"}}
      }},
      "notes": "<summary>"
    }},
    "communication_skills": {{
      "score": <number>,
      "max": 20,
      "breakdown": {{
        "executive_engagement": {{"score": <number>, "max": 8, "evidence": "<quote or reference>"}},
        "presentation_skills": {{"score": <number>, "max": 7, "evidence": "<quote or reference>"}},
        "collaboration": {{"score": <number>, "max": 5, "evidence": "<quote or reference>"}}
      }},
      "notes": "<summary>"
    }},
    "strategic_acumen": {{
      "score": <number>,
      "max": 15,
      "breakdown": {{
        "strategic_planning": {{"score": <number>, "max": 6, "evidence": "<quote or reference>"}},
        "business_impact": {{"score": <number>, "max": 5, "evidence": "<quote or reference>"}},
        "problem_solving": {{"score": <number>, "max": 4, "evidence": "<quote or reference>"}}
      }},
      "notes": "<summary>"
    }},
    "job_stability": {{
      "score": <number>,
      "max": 10,
      "tenure_analysis": {{
        "positions": [
          {{"company": "<company name>", "months": <number>, "role": "<job title>"}},
          ...
        ],
        "average_months": <number>,
        "risk_level": "<Low|Low-Medium|Medium|Medium-High|High|Very High>"
      }},
      "notes": "<stability assessment>"
    }},
    "cultural_fit": {{
      "score": <number>,
      "max": 10,
      "breakdown": {{
        "customer_centricity": {{"score": <number>, "max": 4, "evidence": "<quote or reference>"}},
        "adaptability": {{"score": <number>, "max": 3, "evidence": "<quote or reference>"}},
        "initiative": {{"score": <number>, "max": 3, "evidence": "<quote or reference>"}}
      }},
      "notes": "<summary>"
    }}
  }},
  "total_score": <sum of all category scores>,
  "max_score": 100,
  "percentage": <total_score as percentage>,
  "recommendation": "<STRONG RECOMMEND|RECOMMEND|CONDITIONAL|DO NOT RECOMMEND>",
  "recommendation_tier": <1-4>,
  "summary": "<2-3 sentence overall assessment>",
  "key_strengths": ["<strength 1>", "<strength 2>", "<strength 3>"],
  "areas_of_concern": ["<concern 1>", "<concern 2>"],
  "interview_focus_areas": ["<area 1>", "<area 2>", "<area 3>"]
}}

## Scoring Guidelines
- STRONG RECOMMEND (Tier 1): 85%+ - Exceptional match
- RECOMMEND (Tier 2): 70-84% - Strong candidate
- CONDITIONAL (Tier 3): 55-69% - Has potential but gaps exist
- DO NOT RECOMMEND (Tier 4): Below 55% - Does not meet requirements

## Job Stability Scoring
- 4+ years average tenure: 10/10 (Low Risk)
- 3-4 years: 8/10 (Low-Medium Risk)
- 2-3 years: 6/10 (Medium Risk)
- 1.5-2 years: 4/10 (Medium-High Risk)
- 1-1.5 years: 2/10 (High Risk)
- <1 year: 0/10 (Very High Risk)

Return ONLY the JSON object. Do not include any other text, markdown formatting, or code blocks."""


class ClaudeClient:
    """
    Claude API client for candidate assessments.

    Usage:
        client = ClaudeClient()
        result = client.assess_candidate(resume_text, framework_text)
    """

    def __init__(self, credentials_path: Optional[Path] = None):
        """
        Initialize the Claude client.

        Args:
            credentials_path: Path to credentials YAML file.
                            Defaults to config/claude_credentials.yaml
        """
        self.credentials_path = credentials_path or (get_config_path() / "claude_credentials.yaml")
        self.credentials = self._load_credentials()
        self.settings = get_settings().get("claude", {})

        # Get configuration
        api_config = self.credentials.get("api", {})
        settings_config = self.credentials.get("settings", {})

        self.api_key = api_config.get("api_key")
        self.model = api_config.get("model") or self.settings.get("default_model", "claude-sonnet-4-20250514")
        self.max_tokens = settings_config.get("max_tokens") or self.settings.get("max_tokens", 4096)
        self.temperature = settings_config.get("temperature") or self.settings.get("temperature", 0.3)
        self.timeout = settings_config.get("timeout_seconds") or self.settings.get("timeout_seconds", 120)

        # Lazy import anthropic
        self._client = None

    def _load_credentials(self) -> dict:
        """Load credentials from YAML file or environment variable."""
        # Check environment variable first
        env_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_key:
            return {
                "api": {"api_key": env_key},
                "settings": {}
            }

        # Fall back to credentials file
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"Claude credentials not found: {self.credentials_path}\n"
                "Copy claude_credentials_template.yaml to claude_credentials.yaml and add your API key,\n"
                "or set the ANTHROPIC_API_KEY environment variable."
            )

        with open(self.credentials_path, "r") as f:
            creds = yaml.safe_load(f)

        # Validate API key
        api_key = creds.get("api", {}).get("api_key", "")
        if not api_key or api_key.startswith("YOUR_"):
            raise ValueError(
                "Invalid API key in credentials file.\n"
                "Get your API key at: https://console.anthropic.com/"
            )

        return creds

    def _get_client(self):
        """Get or create the Anthropic client."""
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise ImportError(
                    "anthropic library is required. Run: pip install anthropic"
                )
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def assess_candidate(
        self,
        resume_text: str,
        framework_text: str,
        model: Optional[str] = None,
        max_retries: int = 2
    ) -> dict:
        """
        Assess a candidate's resume against an assessment framework.

        Args:
            resume_text: The candidate's resume text
            framework_text: The assessment framework markdown/text
            model: Override model to use (optional)
            max_retries: Number of retries on parsing failures

        Returns:
            Assessment dictionary with scores and recommendations
        """
        client = self._get_client()
        model = model or self.model

        # Build the prompt
        prompt = ASSESSMENT_PROMPT.format(
            framework_text=framework_text,
            resume_text=resume_text
        )

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                # Make API call
                message = client.messages.create(
                    model=model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )

                # Extract response text
                response_text = message.content[0].text

                # Parse JSON response
                assessment = self._parse_response(response_text)

                # Validate assessment structure
                self._validate_assessment(assessment)

                return assessment

            except json.JSONDecodeError as e:
                last_error = ClaudeResponseError(f"Failed to parse JSON response: {e}")
                if attempt < max_retries:
                    # Add retry prompt
                    prompt += "\n\nYour previous response was not valid JSON. Please return ONLY a valid JSON object."
            except Exception as e:
                if "anthropic" in str(type(e).__module__):
                    # Anthropic library exception
                    raise ClaudeAPIError(f"API error: {e}")
                raise

        raise last_error

    def _parse_response(self, response_text: str) -> dict:
        """Parse the JSON response from Claude."""
        # Try to extract JSON from response
        text = response_text.strip()

        # Remove markdown code blocks if present
        if text.startswith("```"):
            # Find the end of the code block
            lines = text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]  # Remove opening ```json or ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]  # Remove closing ```
            text = "\n".join(lines)

        # Try to find JSON object in response
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            text = json_match.group()

        return json.loads(text)

    def _validate_assessment(self, assessment: dict) -> None:
        """Validate the assessment structure."""
        required_keys = ["scores", "total_score", "recommendation", "summary"]
        for key in required_keys:
            if key not in assessment:
                raise ClaudeResponseError(f"Missing required key: {key}")

        # Validate scores structure
        required_categories = [
            "core_experience", "technical_competencies", "communication_skills",
            "strategic_acumen", "job_stability", "cultural_fit"
        ]
        scores = assessment.get("scores", {})
        for category in required_categories:
            if category not in scores:
                raise ClaudeResponseError(f"Missing score category: {category}")
            if "score" not in scores[category]:
                raise ClaudeResponseError(f"Missing score in category: {category}")

        # Validate recommendation
        valid_recommendations = ["STRONG RECOMMEND", "RECOMMEND", "CONDITIONAL", "DO NOT RECOMMEND"]
        if assessment["recommendation"] not in valid_recommendations:
            raise ClaudeResponseError(f"Invalid recommendation: {assessment['recommendation']}")

    def test_connection(self) -> bool:
        """Test connection to Claude API."""
        try:
            client = self._get_client()
            message = client.messages.create(
                model=self.model,
                max_tokens=100,
                messages=[
                    {"role": "user", "content": "Respond with only the word 'connected' to confirm the connection."}
                ]
            )
            return "connected" in message.content[0].text.lower()
        except Exception as e:
            print(f"Connection test failed: {e}")
            return False


def test_connection() -> bool:
    """Test Claude API connection and authentication."""
    try:
        client = ClaudeClient()
        print(f"Model: {client.model}")
        print(f"Max tokens: {client.max_tokens}")
        print(f"Temperature: {client.temperature}")
        print("Testing connection...")

        if client.test_connection():
            print("Successfully connected to Claude API")
            return True
        else:
            print("Connection test failed")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    test_connection()

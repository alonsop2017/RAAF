#!/usr/bin/env python3
"""
Candidate assessment script.
Scores candidates against the requisition's assessment framework.

Note: This script provides the structure for assessment. The actual scoring
logic would typically be performed by an AI model (like Claude) or human reviewer.
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    get_requisition_config,
    save_requisition_config,
    get_resumes_path,
    get_batch_path,
    get_assessments_path,
    get_framework_path,
    normalize_candidate_name,
    get_settings
)


def load_framework(client_code: str, req_id: str) -> dict:
    """Load the assessment framework for a requisition."""
    framework_path = get_framework_path(client_code, req_id)

    # Look for framework config
    framework_yaml = framework_path / "framework_config.yaml"
    if framework_yaml.exists():
        with open(framework_yaml, "r") as f:
            return yaml.safe_load(f)

    # Fall back to requisition config
    req_config = get_requisition_config(client_code, req_id)
    return req_config.get("assessment", {})


def extract_candidate_info(resume_text: str, filename: str) -> dict:
    """Extract basic candidate information from resume text."""
    info = {
        "name": "",
        "name_normalized": "",
        "email": "",
        "phone": "",
        "source_file": filename
    }

    # Try to extract name from filename
    # Expected format: lastname_firstname_resume.txt
    base_name = Path(filename).stem.replace("_resume", "")
    parts = base_name.split("_")
    if len(parts) >= 2:
        info["name"] = f"{parts[1].title()} {parts[0].title()}"
        info["name_normalized"] = base_name

    # Try to extract email
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', resume_text)
    if email_match:
        info["email"] = email_match.group()

    # Try to extract phone
    phone_match = re.search(r'[\+]?[(]?[0-9]{3}[)]?[-\s\.]?[0-9]{3}[-\s\.]?[0-9]{4}', resume_text)
    if phone_match:
        info["phone"] = phone_match.group()

    return info


def calculate_stability_score(resume_text: str) -> dict:
    """
    Analyze job stability from resume.

    Returns dict with score, tenure analysis, and risk level.
    """
    # This is a simplified implementation
    # A more sophisticated version would parse dates and calculate actual tenures

    stability = {
        "score": 6,  # Default medium
        "max": 10,
        "tenure_analysis": {
            "positions": [],
            "average_months": 0,
            "risk_level": "Medium"
        },
        "notes": "Manual tenure verification recommended"
    }

    # Look for tenure indicators
    text_lower = resume_text.lower()

    # Positive stability indicators
    if any(phrase in text_lower for phrase in ["10+ years", "over 10 years", "decade"]):
        stability["score"] = 10
        stability["tenure_analysis"]["risk_level"] = "Low"
    elif any(phrase in text_lower for phrase in ["8 years", "7 years", "6 years", "5+ years"]):
        stability["score"] = 8
        stability["tenure_analysis"]["risk_level"] = "Low-Medium"
    elif any(phrase in text_lower for phrase in ["4 years", "3 years"]):
        stability["score"] = 6
        stability["tenure_analysis"]["risk_level"] = "Medium"

    # Negative indicators
    job_count = len(re.findall(r'\b(20[0-2][0-9])\s*[-–]\s*(20[0-2][0-9]|present|current)\b',
                               text_lower, re.IGNORECASE))
    if job_count >= 6:
        stability["score"] = max(2, stability["score"] - 4)
        stability["tenure_analysis"]["risk_level"] = "High"
        stability["notes"] = f"Multiple positions detected ({job_count}+). Verify tenure details."

    return stability


def create_assessment_template(
    client_code: str,
    req_id: str,
    candidate_info: dict,
    resume_text: str,
    batch_name: str = None
) -> dict:
    """
    Create an assessment template for a candidate.

    This creates the structure that would be filled in during assessment.
    """
    req_config = get_requisition_config(client_code, req_id)
    framework = load_framework(client_code, req_id)
    settings = get_settings()

    thresholds = framework.get("thresholds", settings["assessment"]["default_thresholds"])
    max_score = framework.get("max_score", 100)

    # Calculate stability score
    stability = calculate_stability_score(resume_text)

    assessment = {
        "metadata": {
            "client_code": client_code,
            "requisition_id": req_id,
            "framework_version": framework.get("framework_version", "1.0"),
            "assessed_at": datetime.now().isoformat(),
            "assessor": "Pending/Manual"
        },
        "candidate": {
            **candidate_info,
            "batch": batch_name or "",
            "source_platform": "Indeed"  # Default, can be updated
        },
        "scores": {
            "core_experience": {
                "score": 0,
                "max": 25,
                "breakdown": {
                    "years_experience": {"score": 0, "max": 10, "evidence": ""},
                    "industry_alignment": {"score": 0, "max": 8, "evidence": ""},
                    "education": {"score": 0, "max": 4, "evidence": ""},
                    "certifications": {"score": 0, "max": 3, "evidence": ""}
                },
                "notes": ""
            },
            "technical_competencies": {
                "score": 0,
                "max": 20,
                "breakdown": {
                    "core_technical": {"score": 0, "max": 8, "evidence": ""},
                    "tools_systems": {"score": 0, "max": 7, "evidence": ""},
                    "analytical_skills": {"score": 0, "max": 5, "evidence": ""}
                },
                "notes": ""
            },
            "communication_skills": {
                "score": 0,
                "max": 20,
                "breakdown": {
                    "executive_engagement": {"score": 0, "max": 8, "evidence": ""},
                    "presentation_skills": {"score": 0, "max": 7, "evidence": ""},
                    "collaboration": {"score": 0, "max": 5, "evidence": ""}
                },
                "notes": ""
            },
            "strategic_acumen": {
                "score": 0,
                "max": 15,
                "breakdown": {
                    "strategic_planning": {"score": 0, "max": 6, "evidence": ""},
                    "business_impact": {"score": 0, "max": 5, "evidence": ""},
                    "problem_solving": {"score": 0, "max": 4, "evidence": ""}
                },
                "notes": ""
            },
            "job_stability": stability,
            "cultural_fit": {
                "score": 0,
                "max": 10,
                "breakdown": {
                    "customer_centricity": {"score": 0, "max": 4, "evidence": ""},
                    "adaptability": {"score": 0, "max": 3, "evidence": ""},
                    "initiative": {"score": 0, "max": 3, "evidence": ""}
                },
                "notes": ""
            }
        },
        "total_score": stability["score"],  # Only stability is auto-scored
        "max_score": max_score,
        "percentage": round((stability["score"] / max_score) * 100, 1),
        "recommendation": "PENDING",
        "recommendation_tier": 0,
        "summary": "",
        "key_strengths": [],
        "areas_of_concern": [],
        "interview_focus_areas": [],
        "resume_text_preview": resume_text[:2000] + "..." if len(resume_text) > 2000 else resume_text
    }

    return assessment


def calculate_recommendation(assessment: dict) -> str:
    """Calculate recommendation based on total score."""
    percentage = assessment.get("percentage", 0)

    # Get thresholds (using defaults if not specified)
    thresholds = {
        "strong_recommend": 85,
        "recommend": 70,
        "conditional": 55
    }

    if percentage >= thresholds["strong_recommend"]:
        return "STRONG RECOMMEND"
    elif percentage >= thresholds["recommend"]:
        return "RECOMMEND"
    elif percentage >= thresholds["conditional"]:
        return "CONDITIONAL"
    else:
        return "DO NOT RECOMMEND"


def assess_candidate(
    client_code: str,
    req_id: str,
    resume_file: str | Path,
    batch_name: str = None,
    output_dir: Path = None
) -> dict:
    """
    Create assessment for a single candidate.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        resume_file: Path to extracted resume text file
        batch_name: Batch name (for tracking)
        output_dir: Output directory for assessment

    Returns:
        Assessment dictionary
    """
    resume_file = Path(resume_file)

    if not resume_file.exists():
        raise FileNotFoundError(f"Resume not found: {resume_file}")

    # Read resume text
    with open(resume_file, "r", encoding="utf-8") as f:
        resume_text = f.read()

    # Extract candidate info
    candidate_info = extract_candidate_info(resume_text, resume_file.name)

    print(f"Assessing: {candidate_info['name'] or resume_file.stem}")

    # Create assessment template
    assessment = create_assessment_template(
        client_code=client_code,
        req_id=req_id,
        candidate_info=candidate_info,
        resume_text=resume_text,
        batch_name=batch_name
    )

    # Determine output path
    if output_dir is None:
        output_dir = get_assessments_path(client_code, req_id, "individual")

    output_dir.mkdir(parents=True, exist_ok=True)

    # Save assessment
    name_normalized = candidate_info.get("name_normalized") or resume_file.stem.replace("_resume", "")
    output_file = output_dir / f"{name_normalized}_assessment.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(assessment, f, indent=2)

    print(f"  Created: {output_file.name}")
    print(f"  Status: {assessment['recommendation']} (pending full assessment)")

    return assessment


def assess_batch(
    client_code: str,
    req_id: str,
    batch_name: str
) -> dict:
    """
    Create assessments for all candidates in a batch.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        batch_name: Batch to assess

    Returns:
        Batch assessment statistics
    """
    batch_path = get_batch_path(client_code, req_id, batch_name)

    if not batch_path.exists():
        raise FileNotFoundError(f"Batch not found: {batch_name}")

    # Find resume files
    resume_files = list(batch_path.glob("*.txt"))

    print(f"Assessing batch: {batch_name}")
    print(f"  Candidates: {len(resume_files)}")
    print("-" * 40)

    stats = {
        "batch": batch_name,
        "total": len(resume_files),
        "assessed": 0,
        "errors": 0
    }

    for resume_file in resume_files:
        try:
            assess_candidate(
                client_code=client_code,
                req_id=req_id,
                resume_file=resume_file,
                batch_name=batch_name
            )
            stats["assessed"] += 1
        except Exception as e:
            print(f"  Error processing {resume_file.name}: {e}")
            stats["errors"] += 1

    # Update batch manifest
    manifest_path = batch_path / "batch_manifest.yaml"
    if manifest_path.exists():
        with open(manifest_path, "r") as f:
            manifest = yaml.safe_load(f)
        manifest["status"] = "assessed"
        manifest["assessed_count"] = stats["assessed"]
        manifest["assessed_at"] = datetime.now().isoformat()
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False)

    print("-" * 40)
    print(f"Batch assessment complete: {stats['assessed']}/{stats['total']}")

    return stats


def assess_all_pending(client_code: str, req_id: str) -> dict:
    """Assess all unprocessed resumes in processed folder."""
    processed_path = get_resumes_path(client_code, req_id, "processed")
    assessments_path = get_assessments_path(client_code, req_id, "individual")

    # Find already assessed
    existing = {f.stem.replace("_assessment", "") for f in assessments_path.glob("*_assessment.json")}

    # Find pending
    resume_files = [
        f for f in processed_path.glob("*.txt")
        if f.stem.replace("_resume", "") not in existing
    ]

    print(f"Pending assessments: {len(resume_files)}")

    stats = {"total": len(resume_files), "assessed": 0, "errors": 0}

    for resume_file in resume_files:
        try:
            assess_candidate(client_code, req_id, resume_file)
            stats["assessed"] += 1
        except Exception as e:
            print(f"Error: {e}")
            stats["errors"] += 1

    return stats


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Assess candidate resumes")
    parser.add_argument("--client", "-c", required=True, help="Client code")
    parser.add_argument("--req", "-r", required=True, help="Requisition ID")
    parser.add_argument("--resume", help="Single resume file to assess")
    parser.add_argument("--batch", "-b", help="Batch to assess")
    parser.add_argument("--all-pending", action="store_true",
                       help="Assess all pending resumes")
    parser.add_argument("--use-context", action="store_true",
                       help="Use saved context for client/req")
    args = parser.parse_args()

    try:
        if args.resume:
            assess_candidate(
                client_code=args.client,
                req_id=args.req,
                resume_file=args.resume
            )
        elif args.batch:
            assess_batch(
                client_code=args.client,
                req_id=args.req,
                batch_name=args.batch
            )
        elif args.all_pending:
            assess_all_pending(args.client, args.req)
        else:
            print("Specify --resume, --batch, or --all-pending")
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

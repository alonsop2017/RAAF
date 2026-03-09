#!/usr/bin/env python3
"""
Candidate assessment script.
Scores candidates against the requisition's assessment framework.

Supports two modes:
- Template mode (default): Creates assessment structure for manual scoring
- AI mode (--use-ai): Uses Claude API for automated assessment
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
    get_settings,
    list_all_extracted_resumes,
)

# Lazy import for Claude client
_claude_client = None


def get_claude_client():
    """Get or create the Claude client (lazy loading)."""
    global _claude_client
    if _claude_client is None:
        from utils.claude_client import ClaudeClient
        _claude_client = ClaudeClient()
    return _claude_client


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


def load_framework_text(client_code: str, req_id: str) -> str:
    """
    Load the assessment framework as text for Claude AI assessment.

    Looks for framework files in this order:
    1. framework/assessment_framework.md
    2. framework/assessment_framework.txt
    3. framework/framework_config.yaml (converted to text)
    4. requisition.yaml assessment section
    """
    framework_path = get_framework_path(client_code, req_id)

    # Check for markdown framework
    md_file = framework_path / "assessment_framework.md"
    if md_file.exists():
        with open(md_file, "r", encoding="utf-8") as f:
            return f.read()

    # Check for text framework
    txt_file = framework_path / "assessment_framework.txt"
    if txt_file.exists():
        with open(txt_file, "r", encoding="utf-8") as f:
            return f.read()

    # Check for YAML framework and convert to text
    yaml_file = framework_path / "framework_config.yaml"
    if yaml_file.exists():
        with open(yaml_file, "r") as f:
            framework = yaml.safe_load(f)
        return yaml.dump(framework, default_flow_style=False)

    # Fall back to requisition config
    req_config = get_requisition_config(client_code, req_id)
    assessment = req_config.get("assessment", {})
    job = req_config.get("job", {})

    # Build framework text from requisition config
    framework_text = f"""# Assessment Framework
## Position: {job.get('title', 'Unknown')}
## Location: {job.get('location', 'Unknown')}

### Requirements
- Minimum Experience: {req_config.get('requirements', {}).get('experience_years_min', 'N/A')} years
- Education: {req_config.get('requirements', {}).get('education', 'N/A')}
- Industry: {req_config.get('requirements', {}).get('industry_preference', 'N/A')}

### Special Requirements
"""
    for req in req_config.get("requirements", {}).get("special_requirements", []):
        framework_text += f"- {req}\n"

    framework_text += f"""
### Scoring Thresholds
- Strong Recommend: {assessment.get('thresholds', {}).get('strong_recommend', 85)}%+
- Recommend: {assessment.get('thresholds', {}).get('recommend', 70)}%+
- Conditional: {assessment.get('thresholds', {}).get('conditional', 55)}%+
- Do Not Recommend: Below {assessment.get('thresholds', {}).get('conditional', 55)}%

### Notes
{req_config.get('notes', 'No additional notes')}
"""
    return framework_text


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
    base_name = Path(filename).stem.replace("_resume", "")

    # Handle "Information for {NAME}" format (from Indeed extraction)
    if base_name.lower().startswith("information for "):
        candidate_name = base_name[16:].strip()  # Remove "Information for " prefix
        info["name"] = candidate_name.title()
        info["name_normalized"] = normalize_candidate_name(candidate_name)
    # Handle lastname_firstname format
    elif "_" in base_name:
        parts = base_name.split("_")
        if len(parts) >= 2:
            info["name"] = f"{parts[1].title()} {parts[0].title()}"
            info["name_normalized"] = base_name
    else:
        # Use filename as-is for name
        info["name"] = base_name.title()
        info["name_normalized"] = normalize_candidate_name(base_name)

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
    output_dir: Path = None,
    use_ai: bool = False,
    ai_model: str = None
) -> dict:
    """
    Create assessment for a single candidate.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        resume_file: Path to extracted resume text file
        batch_name: Batch name (for tracking)
        output_dir: Output directory for assessment
        use_ai: Use Claude AI for assessment (default: False)
        ai_model: Override AI model (optional)

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

    if use_ai:
        # Use Claude AI for assessment
        print("  Mode: AI Assessment (Claude)")
        assessment = assess_with_claude(
            client_code=client_code,
            req_id=req_id,
            candidate_info=candidate_info,
            resume_text=resume_text,
            batch_name=batch_name,
            model=ai_model
        )
    else:
        # Create assessment template for manual scoring
        print("  Mode: Template (manual scoring required)")
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

    _save_to_db(assessment, name_normalized, resume_file, use_ai=use_ai)

    print(f"  Created: {output_file.name}")
    if use_ai:
        print(f"  Score: {assessment['total_score']}/{assessment['max_score']} ({assessment['percentage']}%)")
        print(f"  Recommendation: {assessment['recommendation']}")
    else:
        print(f"  Status: {assessment['recommendation']} (pending full assessment)")

    return assessment


def cap_scores(scores: dict) -> dict:
    """Cap all scores at their max values to correct AI over-scoring."""
    for category, data in scores.items():
        max_val = data.get("max", 0)
        if data.get("score", 0) > max_val:
            data["score"] = max_val
        if "breakdown" in data:
            for sub_key, sub_data in data["breakdown"].items():
                sub_max = sub_data.get("max", 0)
                if sub_data.get("score", 0) > sub_max:
                    sub_data["score"] = sub_max
    return scores


def assess_with_claude(
    client_code: str,
    req_id: str,
    candidate_info: dict,
    resume_text: str,
    batch_name: str = None,
    model: str = None
) -> dict:
    """
    Assess a candidate using Claude AI.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        candidate_info: Extracted candidate information
        resume_text: Resume text content
        batch_name: Batch name for tracking
        model: Override AI model

    Returns:
        Complete assessment dictionary
    """
    # Load framework text
    framework_text = load_framework_text(client_code, req_id)
    framework_config = load_framework(client_code, req_id)

    # Get Claude client
    claude = get_claude_client()

    print("  Sending to Claude API...")

    # Register with activity monitor if no worker_id already set on this thread
    try:
        from utils.activity_writer import worker_stage, _thread_local
        if not getattr(_thread_local, "worker_id", ""):
            from utils.activity_writer import worker_start, make_worker_id
            wid = make_worker_id()
            _thread_local.worker_id = wid
            worker_start(wid, candidate_info.get("name", ""), req_id, client_code)
        worker_stage(_thread_local.worker_id, "assessing")
    except Exception:
        pass

    # Get AI assessment
    ai_result = claude.assess_candidate(
        resume_text=resume_text,
        framework_text=framework_text,
        model=model
    )

    print("  Received AI assessment")

    # Cap scores at max values (AI sometimes over-scores)
    scores = cap_scores(ai_result.get("scores", {}))
    total_score = sum(cat.get("score", 0) for cat in scores.values())
    max_score = ai_result.get("max_score", 100)
    percentage = round((total_score / max_score) * 100, 1) if max_score > 0 else 0
    recommendation = calculate_recommendation({"percentage": percentage})

    # Build complete assessment with metadata
    assessment = {
        "metadata": {
            "client_code": client_code,
            "requisition_id": req_id,
            "framework_version": framework_config.get("framework_version", "1.0"),
            "assessed_at": datetime.now().isoformat(),
            "assessor": f"Claude/{model or claude.model}"
        },
        "candidate": {
            **candidate_info,
            "batch": batch_name or "",
            "source_platform": "Indeed"
        },
        # Merge AI scores (capped at max)
        "scores": scores,
        "total_score": total_score,
        "max_score": max_score,
        "percentage": percentage,
        "recommendation": recommendation,
        "recommendation_tier": ai_result.get("recommendation_tier", 0),
        "summary": ai_result.get("summary", ""),
        "key_strengths": ai_result.get("key_strengths", []),
        "areas_of_concern": ai_result.get("areas_of_concern", []),
        "interview_focus_areas": ai_result.get("interview_focus_areas", []),
        "resume_text_preview": resume_text[:2000] + "..." if len(resume_text) > 2000 else resume_text
    }

    return assessment


def screen_with_claude(
    client_code: str,
    req_id: str,
    candidate_info: dict,
    resume_text: str,
    batch_name: str = None,
    screening_model: str = "claude-haiku-4-5-20251001",
) -> dict:
    """
    Run the lightweight Haiku screening pass for a candidate.

    Saves a minimal assessment JSON with assessment_mode='screened'.
    Returns the assessment dict.
    """
    framework_text = load_framework_text(client_code, req_id)
    framework_config = load_framework(client_code, req_id)
    claude = get_claude_client()

    screening = claude.screen_candidate(
        resume_text=resume_text,
        framework_text=framework_text,
        screening_model=screening_model,
    )

    # Build a minimal assessment with placeholder scores
    assessment = {
        "metadata": {
            "client_code": client_code,
            "requisition_id": req_id,
            "framework_version": framework_config.get("framework_version", "1.0"),
            "assessed_at": datetime.now().isoformat(),
            "assessor": f"Claude/{screening_model}",
        },
        "candidate": {
            **candidate_info,
            "batch": batch_name or "",
            "source_platform": "Indeed",
        },
        "scores": {},
        "total_score": round(screening["percentage"]),
        "max_score": 100,
        "percentage": screening["percentage"],
        "recommendation": screening["recommendation"],
        "recommendation_tier": screening["recommendation_tier"],
        "summary": screening["summary"],
        "key_strengths": [],
        "areas_of_concern": [],
        "interview_focus_areas": [],
        "assessment_mode": "screened",
        "screening": screening,
    }

    return assessment


def two_pass_assess_all(
    client_code: str,
    req_id: str,
    screen_threshold: float = 50.0,
    full_model: str = None,
    screening_model: str = "claude-haiku-4-5-20251001",
    workers: int = 4,
) -> dict:
    """
    Two-pass assessment strategy:
      Pass 1 (Haiku)  — screen ALL pending candidates cheaply.
      Pass 2 (Sonnet) — full assessment on candidates above screen_threshold.

    Candidates below the threshold are saved as assessment_mode='screened' (DNR).
    Candidates above the threshold get a full assessment_mode='full' JSON.

    Args:
        screen_threshold: Minimum % to advance from screening to full assessment (default 50).
        full_model: Model for the full pass (defaults to settings default_model).
        screening_model: Model for the screening pass (default Haiku 4.5).
        workers: Parallel workers for both passes.
    """
    assessments_path = get_assessments_path(client_code, req_id, "individual")
    existing = {f.stem.replace("_assessment", "") for f in assessments_path.glob("*_assessment.json")}

    resume_files = [
        f for f in list_all_extracted_resumes(client_code, req_id)
        if f.stem.replace("_resume", "") not in existing
    ]
    legacy_path = get_resumes_path(client_code, req_id, "processed")
    if legacy_path.exists():
        for f in legacy_path.glob("*.txt"):
            if f.stem.replace("_resume", "") not in existing:
                resume_files.append(f)

    total = len(resume_files)
    print(f"Two-pass assessment: {total} pending candidates")
    print(f"  Pass 1 model : {screening_model} (screening)")
    print(f"  Pass 2 model : {full_model or 'default (Sonnet)'} (full)")
    print(f"  Screen threshold: {screen_threshold}%")
    print("-" * 40)

    if not resume_files:
        return {"total": 0, "screened": 0, "advanced": 0, "full_assessed": 0, "errors": 0}

    assessments_path.mkdir(parents=True, exist_ok=True)

    # ── Pass 1: screen all candidates with Haiku ──────────────────────────────
    print(f"\nPass 1 — Screening {total} candidates with Haiku...")
    screened: list[tuple[Path, dict]] = []  # (resume_file, screening_assessment)
    screen_errors = 0

    def _screen_one(resume_file: Path):
        from utils.activity_writer import worker_start, worker_stage, worker_complete, make_worker_id, _thread_local
        with open(resume_file, "r", encoding="utf-8") as f:
            resume_text = f.read()
        candidate_info = extract_candidate_info(resume_text, resume_file.name)
        name = candidate_info['name'] or resume_file.stem
        print(f"  Screening: {name}")
        wid = make_worker_id()
        _thread_local.worker_id = wid
        worker_start(wid, name, req_id, client_code)
        worker_stage(wid, "screening")
        try:
            result = screen_with_claude(
                client_code, req_id, candidate_info, resume_text,
                screening_model=screening_model,
            )
            worker_complete(wid, score=result.get("percentage"), recommendation=result.get("recommendation", ""), candidate=name)
            return result, resume_file, candidate_info
        except Exception as e:
            worker_complete(wid, error=str(e), candidate=name)
            raise

    if workers <= 1:
        for rf in resume_files:
            try:
                assessment, rf, _ = _screen_one(rf)
                screened.append((rf, assessment))
            except Exception as e:
                print(f"  Screen error ({rf.stem}): {e}")
                screen_errors += 1
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_screen_one, rf): rf for rf in resume_files}
            for future in as_completed(futures):
                try:
                    assessment, rf, _ = future.result()
                    screened.append((rf, assessment))
                except Exception as e:
                    print(f"  Screen error: {e}")
                    screen_errors += 1

    # Save DNR screening results and collect candidates to advance
    to_advance: list[tuple[Path, dict]] = []
    for rf, assessment in screened:
        if assessment["percentage"] < screen_threshold:
            # Save as screened-only (DNR, no full pass needed)
            name_norm = assessment["candidate"].get("name_normalized") or rf.stem.replace("_resume", "")
            out_file = assessments_path / f"{name_norm}_assessment.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(assessment, f, indent=2)
            _save_to_db(assessment, name_norm, rf, use_ai=True)
        else:
            to_advance.append((rf, assessment))

    screened_out = len(screened) - len(to_advance)
    print(f"\nPass 1 complete: {len(screened)} screened, "
          f"{screened_out} filtered out (<{screen_threshold}%), "
          f"{len(to_advance)} advancing to full assessment")

    # ── Pass 2: full Sonnet assessment on advanced candidates ─────────────────
    print(f"\nPass 2 — Full assessment on {len(to_advance)} candidates with Sonnet...")
    full_errors = 0
    full_done = 0

    def _full_one(rf: Path, screening_assessment: dict):
        from utils.activity_writer import worker_start, worker_stage, worker_complete, make_worker_id, _thread_local
        with open(rf, "r", encoding="utf-8") as f:
            resume_text = f.read()
        candidate_info = screening_assessment["candidate"]
        name = candidate_info.get('name') or rf.stem
        print(f"  Full assess: {name}")
        wid = make_worker_id()
        _thread_local.worker_id = wid
        worker_start(wid, name, req_id, client_code)
        worker_stage(wid, "assessing")
        try:
            full = assess_with_claude(
                client_code, req_id, candidate_info, resume_text,
                model=full_model,
            )
            full["screening"] = screening_assessment.get("screening", {})
            full["assessment_mode"] = "full"
            worker_complete(wid, score=full.get("percentage"), recommendation=full.get("recommendation", ""), candidate=name)
            return full, rf
        except Exception as e:
            worker_complete(wid, error=str(e), candidate=name)
            raise

    if workers <= 1:
        for rf, screen_a in to_advance:
            try:
                full_a, rf = _full_one(rf, screen_a)
                name_norm = full_a["candidate"].get("name_normalized") or rf.stem.replace("_resume", "")
                out_file = assessments_path / f"{name_norm}_assessment.json"
                with open(out_file, "w", encoding="utf-8") as f:
                    json.dump(full_a, f, indent=2)
                _save_to_db(full_a, name_norm, rf, use_ai=True)
                full_done += 1
            except Exception as e:
                print(f"  Full assess error ({rf.stem}): {e}")
                full_errors += 1
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_full_one, rf, sa): (rf, sa) for rf, sa in to_advance}
            for future in as_completed(futures):
                try:
                    full_a, rf = future.result()
                    name_norm = full_a["candidate"].get("name_normalized") or rf.stem.replace("_resume", "")
                    out_file = assessments_path / f"{name_norm}_assessment.json"
                    with open(out_file, "w", encoding="utf-8") as f:
                        json.dump(full_a, f, indent=2)
                    _save_to_db(full_a, name_norm, rf, use_ai=True)
                    full_done += 1
                except Exception as e:
                    print(f"  Full assess error: {e}")
                    full_errors += 1

    print("-" * 40)
    print(f"Two-pass complete: {total} total | "
          f"{screened_out} screened out | "
          f"{full_done} fully assessed | "
          f"{screen_errors + full_errors} errors")

    return {
        "total": total,
        "screened": len(screened),
        "advanced": len(to_advance),
        "full_assessed": full_done,
        "errors": screen_errors + full_errors,
    }


def _save_to_db(assessment: dict, name_norm: str, resume_file: Path, use_ai: bool):
    """Save assessment to DB if enabled. Silent on failure."""
    try:
        from scripts.utils.database import get_db, _use_database
        if _use_database():
            candidate_info = assessment.get("candidate", {})
            get_db().save_assessment({
                "req_id": assessment.get("metadata", {}).get("requisition_id", ""),
                "name_normalized": name_norm,
                "name": candidate_info.get("name", name_norm.replace("_", " ").title()),
                "batch": candidate_info.get("batch"),
                "source_platform": candidate_info.get("source_platform", "Unknown"),
                "resume_extracted_path": str(resume_file),
                "total_score": assessment.get("total_score"),
                "percentage": assessment.get("percentage"),
                "recommendation": assessment.get("recommendation"),
                "assessment_mode": assessment.get("assessment_mode", "ai" if use_ai else "pending"),
                "ai_model": assessment.get("metadata", {}).get("assessor"),
                "scores": assessment.get("scores"),
                "summary": assessment.get("summary"),
                "key_strengths": assessment.get("key_strengths"),
                "areas_of_concern": assessment.get("areas_of_concern"),
                "interview_focus_areas": assessment.get("interview_focus_areas"),
                "assessed_at": assessment.get("metadata", {}).get("assessed_at"),
            })
    except Exception:
        pass


def assess_batch(
    client_code: str,
    req_id: str,
    batch_name: str,
    use_ai: bool = False,
    ai_model: str = None
) -> dict:
    """
    Create assessments for all candidates in a batch.

    Args:
        client_code: Client identifier
        req_id: Requisition ID
        batch_name: Batch to assess
        use_ai: Use Claude AI for assessment
        ai_model: Override AI model

    Returns:
        Batch assessment statistics
    """
    batch_path = get_batch_path(client_code, req_id, batch_name)

    if not batch_path.exists():
        raise FileNotFoundError(f"Batch not found: {batch_name}")

    # Find resume files in extracted/ subfolder (new structure) or directly (legacy)
    extracted_dir = batch_path / "extracted"
    if extracted_dir.exists():
        resume_files = list(extracted_dir.glob("*.txt"))
    else:
        resume_files = list(batch_path.glob("*.txt"))

    print(f"Assessing batch: {batch_name}")
    print(f"  Candidates: {len(resume_files)}")
    print(f"  Mode: {'AI Assessment' if use_ai else 'Template'}")
    print("-" * 40)

    stats = {
        "batch": batch_name,
        "total": len(resume_files),
        "assessed": 0,
        "errors": 0,
        "mode": "ai" if use_ai else "template"
    }

    for resume_file in resume_files:
        try:
            assess_candidate(
                client_code=client_code,
                req_id=req_id,
                resume_file=resume_file,
                batch_name=batch_name,
                use_ai=use_ai,
                ai_model=ai_model
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
        manifest["assessment_mode"] = stats["mode"]
        with open(manifest_path, "w") as f:
            yaml.dump(manifest, f, default_flow_style=False)

    print("-" * 40)
    print(f"Batch assessment complete: {stats['assessed']}/{stats['total']}")

    return stats


def assess_all_pending(
    client_code: str,
    req_id: str,
    use_ai: bool = False,
    ai_model: str = None,
    workers: int = 1
) -> dict:
    """Assess all unprocessed resumes across all batch folders and legacy processed/.

    Args:
        workers: Number of parallel assessment workers (default 1 = sequential).
                 Each worker makes independent Claude API calls.
    """
    assessments_path = get_assessments_path(client_code, req_id, "individual")

    # Find already assessed
    existing = {f.stem.replace("_assessment", "") for f in assessments_path.glob("*_assessment.json")}

    # Collect pending resumes from batch extracted/ folders
    resume_files = [
        f for f in list_all_extracted_resumes(client_code, req_id)
        if f.stem.replace("_resume", "") not in existing
    ]

    # Also check legacy processed/ folder
    legacy_path = get_resumes_path(client_code, req_id, "processed")
    if legacy_path.exists():
        for f in legacy_path.glob("*.txt"):
            if f.stem.replace("_resume", "") not in existing:
                resume_files.append(f)

    print(f"Pending assessments: {len(resume_files)}")
    print(f"Mode: {'AI Assessment' if use_ai else 'Template'}")
    if workers > 1:
        print(f"Workers: {workers} (parallel)")

    stats = {"total": len(resume_files), "assessed": 0, "errors": 0, "mode": "ai" if use_ai else "template"}

    if not resume_files:
        return stats

    def _assess_one(resume_file):
        """Assess a single candidate. Returns (success, resume_file, error)."""
        try:
            assess_candidate(
                client_code, req_id, resume_file,
                use_ai=use_ai, ai_model=ai_model
            )
            return True, resume_file, None
        except Exception as e:
            return False, resume_file, str(e)

    if workers <= 1:
        # Sequential (original behavior)
        for resume_file in resume_files:
            ok, _, err = _assess_one(resume_file)
            if ok:
                stats["assessed"] += 1
            else:
                print(f"Error: {err}")
                stats["errors"] += 1
    else:
        # Parallel execution
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_assess_one, rf): rf for rf in resume_files}
            for future in as_completed(futures):
                ok, rf, err = future.result()
                if ok:
                    stats["assessed"] += 1
                else:
                    print(f"Error ({rf.stem}): {err}")
                    stats["errors"] += 1
                done = stats["assessed"] + stats["errors"]
                if done % 5 == 0 or done == stats["total"]:
                    print(f"  Progress: {done}/{stats['total']} "
                          f"({stats['assessed']} assessed, {stats['errors']} errors)")

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
    parser.add_argument("--use-ai", action="store_true",
                       help="Use Claude AI for assessment (requires API key)")
    parser.add_argument("--ai-model", help="Override AI model (e.g., claude-sonnet-4-6)")
    parser.add_argument("--two-pass", action="store_true",
                       help="Two-pass mode: Haiku screening then Sonnet full assessment on survivors")
    parser.add_argument("--screen-threshold", type=float, default=50.0,
                       help="Minimum %% score to advance from screening to full assessment (default: 50)")
    parser.add_argument("--workers", "-w", type=int, default=4,
                       help="Number of parallel assessment workers (default: 4)")
    args = parser.parse_args()

    try:
        if args.resume:
            resume_path = Path(args.resume)
            # If the path doesn't exist, search in batch extracted/ folders and legacy processed/
            if not resume_path.exists():
                from utils.client_utils import find_resume_in_batches
                name_norm = resume_path.stem.replace("_resume", "")
                found = find_resume_in_batches(args.client, args.req, name_norm, "extracted")
                if not found:
                    # Try legacy processed/
                    legacy = get_resumes_path(args.client, args.req, "processed") / args.resume
                    if legacy.exists():
                        found = legacy
                if found:
                    resume_path = found
                else:
                    print(f"Error: Resume not found: {args.resume}", file=sys.stderr)
                    sys.exit(1)
            assess_candidate(
                client_code=args.client,
                req_id=args.req,
                resume_file=resume_path,
                use_ai=args.use_ai,
                ai_model=args.ai_model
            )
        elif args.batch:
            assess_batch(
                client_code=args.client,
                req_id=args.req,
                batch_name=args.batch,
                use_ai=args.use_ai,
                ai_model=args.ai_model
            )
        elif args.two_pass:
            two_pass_assess_all(
                args.client,
                args.req,
                screen_threshold=args.screen_threshold,
                full_model=args.ai_model,
                workers=args.workers,
            )
        elif args.all_pending:
            assess_all_pending(
                args.client,
                args.req,
                use_ai=args.use_ai,
                ai_model=args.ai_model,
                workers=args.workers
            )
        else:
            print("Specify --resume, --batch, or --all-pending")
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

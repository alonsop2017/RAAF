#!/usr/bin/env python3
"""
Generate interview invitation email drafts for qualified candidates.

Creates personalized, copy-paste-ready email drafts for selected candidates,
inviting them to a preliminary screening interview on behalf of the client.
Drafts are saved as text files in the requisition's correspondence/ folder.
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from utils.client_utils import (
    get_requisition_config,
    get_client_info,
    get_assessments_path,
    get_correspondence_path,
    get_settings,
    load_context,
)

# Recommendation tier ordering (lower number = stronger recommendation)
TIER_NAMES = {
    1: "STRONG RECOMMEND",
    2: "RECOMMEND",
    3: "CONDITIONAL",
    4: "DO NOT RECOMMEND",
}

TIER_BY_NAME = {v: k for k, v in TIER_NAMES.items()}


def load_assessments(client_code: str, req_id: str) -> list[dict]:
    """Load all individual assessment JSON files for a requisition."""
    assessments_dir = get_assessments_path(client_code, req_id, "individual")
    if not assessments_dir.exists():
        return []

    assessments = []
    for json_file in sorted(assessments_dir.glob("*.json")):
        if json_file.stem.endswith("_lifecycle"):
            continue
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            assessments.append(data)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Warning: Could not load {json_file.name}: {e}", file=sys.stderr)

    return assessments


def filter_assessments(
    assessments: list[dict],
    min_tier: int = 2,
    candidate_names: Optional[list[str]] = None,
) -> list[dict]:
    """Filter assessments by recommendation tier and/or specific candidate names.

    Args:
        assessments: List of loaded assessment dicts.
        min_tier: Include candidates at this tier or stronger (lower number).
                  1=STRONG RECOMMEND only, 2=RECOMMEND+, 3=CONDITIONAL+.
        candidate_names: If provided, only include these candidates (ignores tier filter).

    Returns:
        Filtered and score-sorted list of assessments.
    """
    filtered = []
    for a in assessments:
        # Resolve tier from recommendation string or recommendation_tier field
        rec = a.get("recommendation", "")
        tier = TIER_BY_NAME.get(rec)
        if tier is None:
            tier = a.get("recommendation_tier", 99)

        # If specific candidates requested, match by normalized or full name
        if candidate_names:
            name_norm = a.get("candidate", {}).get("name_normalized", "")
            name_full = a.get("candidate", {}).get("name", "").lower()
            if not any(
                cn.lower() in name_norm or cn.lower() in name_full
                for cn in candidate_names
            ):
                continue
        else:
            # Apply tier filter
            if tier > min_tier:
                continue

        filtered.append(a)

    # Sort by score descending
    filtered.sort(key=lambda x: x.get("percentage", 0), reverse=True)
    return filtered


def get_first_name(full_name: str) -> str:
    """Extract first name from a full name."""
    parts = full_name.strip().split()
    return parts[0] if parts else full_name


def format_salary(salary_range: dict) -> str:
    """Format salary range as a human-readable string."""
    currency = salary_range.get("currency", "CAD")
    min_sal = salary_range.get("min")
    max_sal = salary_range.get("max")
    if min_sal and max_sal:
        return f"${min_sal:,}–${max_sal:,} {currency}"
    elif max_sal:
        return f"Up to ${max_sal:,} {currency}"
    elif min_sal:
        return f"From ${min_sal:,} {currency}"
    return "Competitive"


def get_default_template() -> dict:
    """Return the built-in default template strings."""
    return {
        "subject": "Opportunity: {job_title} at {company_name} - Are You Available for a Brief Call?",
        "opening": "I hope this message finds you well.",
        "call_to_action": (
            "If this sounds like something you would be open to exploring, please reply "
            "to this email with a few times that work for you this week or next, and we "
            "will arrange a convenient time to connect."
        ),
        "not_interested": (
            "If the timing or opportunity isn't the right fit at this stage, please feel "
            "free to let us know - we appreciate your transparency and would welcome the "
            "chance to stay in touch for future opportunities."
        ),
        "closing": "We look forward to hearing from you.",
    }


def generate_email_draft(
    assessment: dict,
    req_config: dict,
    client_info: dict,
    recruiter: dict,
    template: Optional[dict] = None,
) -> str:
    """Generate a personalized interview invitation email draft for one candidate.

    Args:
        assessment: Loaded candidate assessment dict.
        req_config: Requisition config (requisition.yaml).
        client_info: Client info (client_info.yaml).
        recruiter: Recruiter details dict (name, email, phone, agency, title).
        template: Optional dict of template text overrides (subject, opening,
                  call_to_action, not_interested, closing).

    Returns:
        Formatted email draft as a plain-text string.
    """
    candidate = assessment.get("candidate", {})
    candidate_name = candidate.get("name", "Candidate")
    first_name = get_first_name(candidate_name)
    candidate_email = candidate.get("email", "[email not available]")

    company_name = "<Confidential Client>"
    industry = client_info.get("industry", "")

    job = req_config.get("job", {})
    job_title = job.get("title", "the position")
    location = job.get("location", "")
    salary_range = job.get("salary_range", {})
    salary_str = format_salary(salary_range) if salary_range else ""

    key_strengths = assessment.get("key_strengths", [])
    interview_focus = assessment.get("interview_focus_areas", [])
    summary = assessment.get("summary", "")
    recommendation = assessment.get("recommendation", "")
    percentage = assessment.get("percentage", 0)

    recruiter_name = recruiter.get("name", "[Recruiter Name]")
    recruiter_title = recruiter.get("title", "Senior Recruitment Consultant")
    recruiter_email = recruiter.get("email", "[recruiter@archtektconsultinginc.com]")
    recruiter_phone = recruiter.get("phone", "")
    agency_name = recruiter.get("agency", "Archtekt Consulting Inc.")
    agency_display = agency_name.rstrip(".")

    # --- Personalization paragraph ---
    if key_strengths:
        s1 = key_strengths[0].rstrip(".")
        if len(key_strengths) >= 2:
            s2 = key_strengths[1].lower().rstrip(".")
            personalization = (
                f"Your profile stood out to us — particularly your {s1.lower()}, "
                f"and {s2}. We believe your background aligns well with what "
                f"{company_name} is looking for."
            )
        else:
            personalization = (
                f"Your profile stood out to us — particularly your {s1.lower()}. "
                f"We believe your background aligns well with what {company_name} "
                f"is looking for."
            )
    elif summary:
        sentences = re.split(r"(?<=[.!?])\s+", summary.strip())
        personalization = " ".join(sentences[:2])
    else:
        personalization = (
            f"After reviewing your professional background, we believe your "
            f"experience could be an excellent fit for this opportunity."
        )

    # --- Discussion points from interview focus areas ---
    if interview_focus:
        focus_lines = "\n".join(f"  • {item}" for item in interview_focus[:3])
        discussion_section = (
            f"To make the most of our time together, we would like to explore:\n"
            f"{focus_lines}"
        )
    else:
        discussion_section = (
            "During our conversation, we would like to learn more about your "
            "relevant experience, career goals, and availability."
        )

    # --- Merge template with defaults ---
    tmpl = dict(get_default_template())
    if template:
        for key, val in template.items():
            if val and str(val).strip():
                tmpl[key] = str(val).strip()

    # --- Render subject (supports {job_title}, {company_name} placeholders) ---
    subject = tmpl["subject"].format(
        job_title=job_title,
        company_name=company_name,
        recruiter_name=recruiter_name,
        agency_name=agency_display,
    )

    # --- Optional fields ---
    location_line = f"\n  • Location:       {location}" if location else ""
    salary_line = f"\n  • Compensation:   {salary_str}" if salary_str else ""
    phone_line = f"\n  {recruiter_phone}" if recruiter_phone else ""
    industry_suffix = f" — {industry}" if industry else ""

    today = datetime.now().strftime("%B %d, %Y")
    divider = "=" * 80

    email_draft = f"""{divider}
INTERVIEW INVITATION DRAFT
Candidate:  {candidate_name}
Email:      {candidate_email}
Role:       {job_title} | {company_name}
Assessment: {recommendation} ({percentage:.0f}%)
Generated:  {today}
{divider}

SUBJECT: {subject}

---

Dear {first_name},

{tmpl["opening"]} My name is {recruiter_name}, and I am a recruitment consultant with {agency_display}. I am reaching out on behalf of {company_name}{industry_suffix} regarding an exciting opportunity that may be a strong match for your background and career goals.

{personalization}

About the Opportunity:
  • Role:            {job_title}
  • Company:         {company_name}{industry_suffix}{location_line}{salary_line}

We would like to invite you to a brief preliminary conversation (approximately 20–30 minutes) to:
  • Share more about the role and what {company_name} is looking for
  • Learn about your experience and current career interests
  • Discuss your availability and any questions you may have

{discussion_section}

{tmpl["call_to_action"]}

{tmpl["not_interested"]}

{tmpl["closing"]}

Warm regards,

{recruiter_name}
{recruiter_title}
{agency_display}
  {recruiter_email}{phone_line}

(This invitation is sent on behalf of {company_name}. Recruitment services are provided by {agency_display}.)

{divider}
"""
    return email_draft


def save_invitations(
    drafts: list[tuple[dict, str]],
    correspondence_path: Path,
    combined: bool = True,
    individual: bool = True,
    req_id: str = "",
) -> list[Path]:
    """Save email drafts as text files to the correspondence/interview_invitations/ folder.

    Args:
        drafts: List of (assessment, email_text) tuples.
        correspondence_path: Root correspondence directory for this requisition.
        combined: Whether to save a single combined file with all drafts.
        individual: Whether to save individual per-candidate files.
        req_id: Requisition ID (used in combined filename).

    Returns:
        List of saved file paths.
    """
    invitations_dir = correspondence_path / "interview_invitations"
    invitations_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    saved_files = []

    if individual:
        for assessment, email_text in drafts:
            name_norm = assessment.get("candidate", {}).get("name_normalized", "unknown")
            filename = f"{name_norm}_invitation_{today}.txt"
            file_path = invitations_dir / filename
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(email_text)
            saved_files.append(file_path)

    if combined and drafts:
        combined_filename = f"{req_id}_interview_invitations_{today}.txt"
        combined_path = invitations_dir / combined_filename
        separator = "\n\n"
        combined_text = separator.join(text for _, text in drafts)
        with open(combined_path, "w", encoding="utf-8") as f:
            f.write(combined_text)
        saved_files.append(combined_path)

    return saved_files


def get_recruiter_config(settings: dict, args) -> dict:
    """Build recruiter config by merging settings defaults with CLI arg overrides."""
    recruiter = dict(settings.get("recruiter", {}))

    if getattr(args, "recruiter_name", None):
        recruiter["name"] = args.recruiter_name
    if getattr(args, "recruiter_email", None):
        recruiter["email"] = args.recruiter_email
    if getattr(args, "recruiter_phone", None):
        recruiter["phone"] = args.recruiter_phone

    return recruiter


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Generate personalized interview invitation email drafts for qualified candidates. "
            "Output is saved as copy-paste-ready .txt files in the requisition's correspondence folder."
        )
    )
    parser.add_argument("--client", "-c", help="Client code (e.g., cataldi_2026)")
    parser.add_argument("--req", "-r", help="Requisition ID (e.g., REQ_2026_001_DIRFIN)")
    parser.add_argument(
        "--min-tier",
        type=int,
        default=2,
        choices=[1, 2, 3],
        help=(
            "Minimum recommendation tier to include: "
            "1=STRONG RECOMMEND only, 2=RECOMMEND+ (default), 3=CONDITIONAL+"
        ),
    )
    parser.add_argument(
        "--candidates",
        nargs="+",
        metavar="NAME",
        help=(
            "Specific candidate name(s) or normalized name(s) to include. "
            "Overrides the --min-tier filter. Example: --candidates 'John Smith' kerbel_shael"
        ),
    )
    parser.add_argument(
        "--format",
        choices=["individual", "combined", "both"],
        default="both",
        help=(
            "Output format: 'individual' saves one file per candidate, "
            "'combined' saves one file with all drafts, 'both' (default) saves both."
        ),
    )
    parser.add_argument(
        "--recruiter-name",
        help="Recruiter full name (overrides settings.yaml recruiter.name)",
    )
    parser.add_argument(
        "--recruiter-email",
        help="Recruiter email address (overrides settings.yaml recruiter.email)",
    )
    parser.add_argument(
        "--recruiter-phone",
        help="Recruiter phone number (overrides settings.yaml recruiter.phone)",
    )
    parser.add_argument(
        "--use-context",
        action="store_true",
        help="Use saved working context (from scripts/context.py) to fill in --client/--req",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print drafts to stdout instead of saving files",
    )

    args = parser.parse_args()

    # Resolve client and req (CLI args > saved context)
    client_code = args.client
    req_id = args.req

    if args.use_context or not (client_code and req_id):
        context = load_context()
        if not client_code:
            client_code = context.get("client")
        if not req_id:
            req_id = context.get("requisition")

    if not client_code or not req_id:
        parser.error(
            "--client and --req are required (or set a working context with scripts/context.py --set)"
        )

    # Load configs
    try:
        req_config = get_requisition_config(client_code, req_id)
        client_info = get_client_info(client_code)
        settings = get_settings()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Load assessments
    print(f"Loading assessments for {client_code} / {req_id}...", flush=True)
    all_assessments = load_assessments(client_code, req_id)

    if not all_assessments:
        print(
            "No assessments found. Run assess_candidate.py first.", file=sys.stderr
        )
        sys.exit(1)

    print(f"  Found {len(all_assessments)} total assessments", flush=True)

    # Filter candidates
    selected = filter_assessments(
        all_assessments,
        min_tier=args.min_tier,
        candidate_names=args.candidates,
    )

    if not selected:
        tier_label = TIER_NAMES.get(args.min_tier, str(args.min_tier))
        print(
            f"No candidates found at {tier_label} level or above. "
            f"Try --min-tier 3 to include CONDITIONAL candidates."
        )
        sys.exit(0)

    tier_label = TIER_NAMES.get(args.min_tier, str(args.min_tier))
    print(f"  Selected {len(selected)} candidate(s) at tier {args.min_tier} ({tier_label}) or above:", flush=True)
    for a in selected:
        name = a.get("candidate", {}).get("name", "Unknown")
        rec = a.get("recommendation", "?")
        pct = a.get("percentage", 0)
        email_addr = a.get("candidate", {}).get("email", "no email")
        print(f"    - {name} ({rec}, {pct:.0f}%) - {email_addr}", flush=True)

    # Build recruiter config
    recruiter = get_recruiter_config(settings, args)

    # Generate drafts
    print(f"\nGenerating {len(selected)} email draft(s)...")
    template = settings.get("invitation_template", {})
    drafts = []
    for assessment in selected:
        email_text = generate_email_draft(assessment, req_config, client_info, recruiter, template)
        drafts.append((assessment, email_text))

    if args.dry_run:
        # Use sys.stdout.buffer with UTF-8 to handle Unicode characters on any terminal
        stdout_bytes = sys.stdout.buffer if hasattr(sys.stdout, "buffer") else None
        for _, email_text in drafts:
            if stdout_bytes:
                stdout_bytes.write((email_text + "\n").encode("utf-8"))
            else:
                print(email_text)
        msg = f"\n[Dry run] {len(drafts)} draft(s) generated. No files saved.\n"
        if stdout_bytes:
            stdout_bytes.write(msg.encode("utf-8"))
        else:
            print(msg)
        return

    # Save to correspondence folder
    correspondence_path = get_correspondence_path(client_code, req_id)
    individual = args.format in ("individual", "both")
    combined = args.format in ("combined", "both")

    saved = save_invitations(
        drafts,
        correspondence_path,
        combined=combined,
        individual=individual,
        req_id=req_id,
    )

    print(f"\nSaved {len(saved)} file(s):")
    for path in saved:
        print(f"  {path}")

    print(f"\nDone. {len(drafts)} interview invitation draft(s) ready for review.")


if __name__ == "__main__":
    main()

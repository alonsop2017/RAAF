#!/usr/bin/env python3
"""
Check overlap between existing assessments and the current candidates manifest.
No API calls — runs entirely from local files.

Usage:
    python scripts/check_assessment_overlap.py --client cataldi_2026 --req REQ-2026-007-PC
"""

import json
import sys
import argparse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).parent))

# Inline normalize_candidate_name to avoid importing client_utils (needs yaml)
import unicodedata
import re

def normalize_candidate_name(name: str) -> str:
    """Normalize a candidate name to lastname_firstname format."""
    _TRANSLIT = {"ü": "ue", "ö": "oe", "ä": "ae", "ß": "ss", "é": "e", "è": "e",
                 "ê": "e", "à": "a", "â": "a", "î": "i", "ô": "o", "û": "u",
                 "ç": "c", "ñ": "n", "ó": "o", "á": "a", "í": "i", "ú": "u"}
    name = name.lower().strip()
    for ch, rep in _TRANSLIT.items():
        name = name.replace(ch, rep)
    name = unicodedata.normalize("NFD", name)
    name = re.sub(r"[^a-z\s]", "", name)
    parts = name.split()
    if len(parts) >= 2:
        return f"{parts[-1]}_{' '.join(parts[:-1])}".replace(" ", "_")
    return name.replace(" ", "_")


def check_overlap(client_code: str, req_id: str) -> None:
    req_root = Path("clients") / client_code / "requisitions" / req_id
    manifest_file = req_root / "resumes" / "incoming" / "candidates_manifest.json"
    assessments_dir = req_root / "assessments" / "individual"

    if not manifest_file.exists():
        print(f"ERROR: Manifest not found: {manifest_file}")
        print("Run sync_candidates.py first.")
        sys.exit(1)

    if not assessments_dir.exists():
        print(f"ERROR: Assessments directory not found: {assessments_dir}")
        sys.exit(1)

    # Load manifest
    with open(manifest_file, encoding="utf-8") as f:
        manifest = json.load(f)

    pipeline_candidates = manifest.get("candidates", [])
    synced_at = manifest.get("synced_at", "unknown")
    position_ids = manifest.get("position_ids", [])

    print(f"Manifest synced: {synced_at}")
    print(f"Position IDs:    {', '.join(position_ids)}")
    print(f"Pipeline total:  {len(pipeline_candidates)} candidates")
    print()

    # Build normalised name set from manifest
    pipeline_by_norm: dict[str, dict] = {}
    for c in pipeline_candidates:
        name = f"{c.get('FirstName', '')} {c.get('LastName', '')}".strip()
        norm = normalize_candidate_name(name)
        pipeline_by_norm[norm] = c

    # Load existing assessments
    assessment_files = sorted(assessments_dir.glob("*_assessment.json"))
    assessed_norms: set[str] = set()
    for af in assessment_files:
        # filename is lastname_firstname_assessment.json
        stem = af.stem.replace("_assessment", "")
        assessed_norms.add(stem)

    print(f"Assessments on disk: {len(assessment_files)}")
    print()

    # Overlap: assessed AND in pipeline
    in_pipeline_and_assessed = [n for n in assessed_norms if n in pipeline_by_norm]
    # Assessed but NOT in pipeline (wasted credits)
    assessed_not_in_pipeline = [n for n in assessed_norms if n not in pipeline_by_norm]
    # In pipeline but NOT yet assessed (still needed)
    pipeline_not_assessed = [n for n in pipeline_by_norm if n not in assessed_norms]

    print(f"Already assessed (valid, in pipeline): {len(in_pipeline_and_assessed)}")
    print(f"Assessed but NOT in pipeline (wasted): {len(assessed_not_in_pipeline)}")
    print(f"Still need assessment:                 {len(pipeline_not_assessed)}")
    print()

    if pipeline_not_assessed:
        print("--- Candidates still needing assessment ---")
        for norm in sorted(pipeline_not_assessed):
            c = pipeline_by_norm[norm]
            name = f"{c.get('FirstName', '')} {c.get('LastName', '')}".strip()
            status = c.get("PipelineStatus", "")
            print(f"  {name:<35} [{status}]")
        print()

    if assessed_not_in_pipeline:
        print("--- Assessed but not in pipeline (wrong candidates) ---")
        for norm in sorted(assessed_not_in_pipeline):
            print(f"  {norm}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Check assessment vs pipeline overlap")
    parser.add_argument("--client", "-c", required=True)
    parser.add_argument("--req", "-r", required=True)
    args = parser.parse_args()
    check_overlap(args.client, args.req)


if __name__ == "__main__":
    main()

"""
Migration: Backfill existing file-based data into the SQLite database.

Reads all client_info.yaml, requisition.yaml, and *_assessment.json files
from the existing directory structure and inserts them into the DB.
Candidates without assessments (resume files in batches) are inserted as
pending rows.

Flags:
    --dry-run        Print what would be inserted without writing anything.
    --verify-only    Compare DB row counts against file counts and report gaps.
    --db PATH        Override default database path (data/raaf.db).
    --data-root PATH Override where client data lives (default: project root).
                     Use this when running from a worktree against live data:
                     --data-root /home/alonsop/RAAF

Usage:
    python scripts/migrate/backfill_data.py
    python scripts/migrate/backfill_data.py --dry-run
    python scripts/migrate/backfill_data.py --verify-only
    python scripts/migrate/backfill_data.py --data-root /home/alonsop/RAAF
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.utils.database import DatabaseManager, reset_db_instance
import scripts.utils.client_utils as _cu

# Patched at startup via --data-root; see _patch_data_root().
from scripts.utils.client_utils import (
    get_project_root,
    list_clients,
    list_requisitions,
    get_client_info,
    get_requisition_config,
    get_requisition_root,
)


def _patch_data_root(root: Path) -> None:
    """Redirect client_utils path helpers to an explicit data root.

    When running from a worktree the implicit project root points at the
    worktree directory which has no client data (clients/ is gitignored).
    Calling this before any other import makes all helpers work against the
    live production directory instead.
    """
    import scripts.utils.client_utils as cu
    cu.get_project_root = lambda: root  # type: ignore[attr-defined]
    # Refresh module-level symbols in this file too
    global get_project_root, list_clients, list_requisitions
    global get_client_info, get_requisition_config, get_requisition_root
    get_project_root      = cu.get_project_root
    list_clients          = cu.list_clients
    list_requisitions     = cu.list_requisitions
    get_client_info       = cu.get_client_info
    get_requisition_config = cu.get_requisition_config
    get_requisition_root  = cu.get_requisition_root

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_name(name: str) -> str:
    """'Smith John' or 'john_smith' -> 'smith_john'."""
    parts = name.strip().replace(" ", "_").lower().split("_")
    if len(parts) >= 2:
        return f"{parts[-1]}_{parts[0]}"
    return name.lower().replace(" ", "_")


def _detect_batch_type(batch_dir: Path) -> str:
    """Return 'nested' if the batch has originals/ + extracted/ subdirs, else 'flat'."""
    if (batch_dir / "originals").exists() or (batch_dir / "extracted").exists():
        return "nested"
    return "flat"


def _iter_extracted_resumes(batch_dir: Path, batch_type: str):
    """Yield (name_normalized, resume_extracted_path) for each candidate in a batch."""
    if batch_type == "nested":
        extracted_dir = batch_dir / "extracted"
        if extracted_dir.exists():
            for f in sorted(extracted_dir.glob("*_resume.txt")):
                stem = f.stem.replace("_resume", "")
                yield stem, str(f)
    else:
        for f in sorted(batch_dir.glob("*_resume.txt")):
            stem = f.stem.replace("_resume", "")
            yield stem, str(f)


# ---------------------------------------------------------------------------
# Phase 1: Clients
# ---------------------------------------------------------------------------

def backfill_clients(db: DatabaseManager, dry_run: bool) -> dict:
    """Insert all clients from client_info.yaml files."""
    stats = {"found": 0, "inserted": 0, "skipped": 0, "errors": 0}

    for client_code in list_clients():
        stats["found"] += 1
        try:
            cfg = get_client_info(client_code)
            if not cfg:
                stats["skipped"] += 1
                continue

            # Map YAML structure to DB fields
            billing = cfg.get("billing", {})
            data = {
                "client_code":             client_code,
                "company_name":            cfg.get("company_name", client_code),
                "industry":                cfg.get("industry"),
                "status":                  cfg.get("status", "active"),
                "pcr_company_name":        cfg.get("pcr_integration", {})
                                               .get("company", {})
                                               .get("company_name"),
                "default_commission_rate": billing.get("default_commission_rate"),
                "payment_terms":           billing.get("payment_terms"),
                "guarantee_period_days":   billing.get("guarantee_period_days"),
                "preferences":             cfg.get("preferences", {}),
                "contacts":                cfg.get("contacts", {}),
            }

            if dry_run:
                print(f"  [DRY] Would insert client: {client_code} "
                      f"({data['company_name']})")
            else:
                db.create_client(data)
            stats["inserted"] += 1

        except Exception as exc:
            print(f"  ERROR client {client_code}: {exc}")
            stats["errors"] += 1

    return stats


# ---------------------------------------------------------------------------
# Phase 2: Requisitions
# ---------------------------------------------------------------------------

def backfill_requisitions(db: DatabaseManager, dry_run: bool) -> dict:
    stats = {"found": 0, "inserted": 0, "skipped": 0, "errors": 0}

    for client_code in list_clients():
        for req_id in list_requisitions(client_code):
            stats["found"] += 1
            try:
                cfg = get_requisition_config(client_code, req_id)
                if not cfg:
                    stats["skipped"] += 1
                    continue

                req_root = get_requisition_root(client_code, req_id)

                # Detect job description file
                jd_file = None
                for ext in ("pdf", "docx", "txt"):
                    candidate = req_root / f"job_description.{ext}"
                    if candidate.exists():
                        jd_file = candidate.name
                        break

                # Detect framework source
                fw_file = req_root / "framework" / "assessment_framework.md"
                framework_source = (
                    "ai_generated" if fw_file.exists() else "template"
                )

                job = cfg.get("job", {})
                salary = job.get("salary_range", {})
                reqs = cfg.get("requirements", {})
                thresholds = cfg.get("assessment", {}).get("thresholds", {})
                pcr = cfg.get("pcr_integration", {}).get("job", {})

                data = {
                    "req_id":                  req_id,
                    "client_code":             client_code,
                    "job_title":               job.get("title", req_id),
                    "department":              job.get("department"),
                    "location":                job.get("location"),
                    "salary_min":              salary.get("min", 0),
                    "salary_max":              salary.get("max", 0),
                    "salary_currency":         salary.get("currency", "CAD"),
                    "commission_rate":         job.get("commission_rate"),
                    "status":                  cfg.get("status", "active"),
                    "experience_years_min":    reqs.get("experience_years_min", 0),
                    "education":               reqs.get("education"),
                    "threshold_strong":        thresholds.get("strong_recommend", 85),
                    "threshold_recommend":     thresholds.get("recommend", 70),
                    "threshold_conditional":   thresholds.get("conditional", 55),
                    "framework_version":       cfg.get("assessment", {})
                                                  .get("framework_version", "1.0"),
                    "max_score":               cfg.get("assessment", {})
                                                  .get("max_score", 100),
                    "job_description_file":    jd_file,
                    "framework_source":        framework_source,
                    "pcr_job_id":              pcr.get("job_id"),
                    "pcr_job_title":           pcr.get("title"),
                    "pcr_company_name":        pcr.get("company_name"),
                    "pcr_linked_date":         pcr.get("linked_date"),
                    "weight_overrides":        cfg.get("assessment", {})
                                                  .get("weight_overrides"),
                    "special_requirements":    reqs.get("special_requirements"),
                    "notes":                   cfg.get("notes"),
                    "created_date":            str(cfg.get("created_date", "")),
                }

                if dry_run:
                    print(f"  [DRY] Would insert requisition: {req_id} "
                          f"({data['job_title']})")
                else:
                    db.create_requisition(data)
                stats["inserted"] += 1

            except Exception as exc:
                print(f"  ERROR requisition {req_id}: {exc}")
                stats["errors"] += 1

    return stats


# ---------------------------------------------------------------------------
# Phase 3: Candidates + Assessments
# ---------------------------------------------------------------------------

def backfill_assessments(db: DatabaseManager, dry_run: bool) -> dict:
    stats = {"found": 0, "inserted": 0, "skipped": 0, "errors": 0}

    for client_code in list_clients():
        for req_id in list_requisitions(client_code):
            req_root = get_requisition_root(client_code, req_id)
            individual_dir = req_root / "assessments" / "individual"
            if not individual_dir.exists():
                continue

            for json_file in sorted(individual_dir.glob("*.json")):
                # Skip lifecycle files
                if json_file.stem.endswith("_lifecycle"):
                    continue
                stats["found"] += 1
                try:
                    with open(json_file, encoding="utf-8") as fh:
                        raw = json.load(fh)

                    metadata  = raw.get("metadata", {})
                    candidate = raw.get("candidate", {})
                    scores    = raw.get("scores", {})

                    name_norm = candidate.get(
                        "name_normalized",
                        _normalise_name(candidate.get("name", json_file.stem))
                    )

                    # Determine assessment mode from assessor field
                    assessor = metadata.get("assessor", "")
                    if "Claude" in assessor or "claude" in assessor:
                        mode = "ai"
                    elif assessor == "Manual" or assessor == "manual":
                        mode = "manual"
                    else:
                        mode = "ai"

                    # Locate extracted resume path
                    resume_path = None
                    for batch_dir in (req_root / "resumes" / "batches").glob("*"):
                        for candidate_path in (
                            batch_dir.glob(f"{name_norm}_resume.txt"),
                            (batch_dir / "extracted").glob(
                                f"{name_norm}_resume.txt"
                            ) if (batch_dir / "extracted").exists() else iter([]),
                        ):
                            try:
                                for p in candidate_path:
                                    if p.exists():
                                        resume_path = str(p)
                                        break
                            except TypeError:
                                if hasattr(candidate_path, "exists") and candidate_path.exists():
                                    resume_path = str(candidate_path)
                            if resume_path:
                                break
                        if resume_path:
                            break

                    data = {
                        "req_id":                req_id,
                        "name":                  candidate.get("name", name_norm),
                        "name_normalized":       name_norm,
                        "source_platform":       candidate.get("source_platform",
                                                               "Unknown"),
                        "batch":                 candidate.get("batch"),
                        "resume_extracted_path": resume_path,
                        "total_score":           raw.get("total_score"),
                        "percentage":            raw.get("percentage"),
                        "recommendation":        raw.get("recommendation"),
                        "assessment_mode":       mode,
                        "ai_model":              metadata.get("ai_model"),
                        "scores":                scores,
                        "summary":               raw.get("summary"),
                        "key_strengths":         raw.get("key_strengths", []),
                        "areas_of_concern":      raw.get("areas_of_concern", []),
                        "interview_focus_areas": raw.get("interview_focus_areas",
                                                         []),
                        "assessed_at":           metadata.get("assessed_at"),
                    }

                    if dry_run:
                        print(f"  [DRY] Would insert assessment: "
                              f"{name_norm} / {req_id} "
                              f"({raw.get('percentage', '?')}%)")
                    else:
                        db.save_assessment(data)
                    stats["inserted"] += 1

                except Exception as exc:
                    print(f"  ERROR assessment {json_file.name}: {exc}")
                    stats["errors"] += 1

    return stats


# ---------------------------------------------------------------------------
# Phase 4: Pending candidates (resume files without assessments)
# ---------------------------------------------------------------------------

def backfill_pending_candidates(db: DatabaseManager, dry_run: bool) -> dict:
    stats = {"found": 0, "inserted": 0, "skipped": 0, "errors": 0}

    for client_code in list_clients():
        for req_id in list_requisitions(client_code):
            req_root = get_requisition_root(client_code, req_id)
            batches_dir = req_root / "resumes" / "batches"
            if not batches_dir.exists():
                continue

            # Get names already in DB for this req so we don't double-insert
            if not dry_run:
                existing = {
                    c["name_normalized"]
                    for c in db.list_candidates(req_id)
                }
            else:
                existing = set()

            for batch_dir in sorted(batches_dir.iterdir()):
                if not batch_dir.is_dir():
                    continue
                batch_type = _detect_batch_type(batch_dir)
                for name_norm, resume_path in _iter_extracted_resumes(
                    batch_dir, batch_type
                ):
                    stats["found"] += 1
                    if name_norm in existing:
                        stats["skipped"] += 1
                        continue
                    try:
                        if dry_run:
                            print(f"  [DRY] Would insert pending candidate: "
                                  f"{name_norm} / {req_id}")
                        else:
                            db.upsert_candidate({
                                "req_id":                req_id,
                                "name":                  name_norm.replace(
                                    "_", " ").title(),
                                "name_normalized":       name_norm,
                                "batch":                 batch_dir.name,
                                "resume_extracted_path": resume_path,
                                "status":                "pending",
                            })
                            existing.add(name_norm)
                        stats["inserted"] += 1
                    except Exception as exc:
                        print(f"  ERROR pending candidate {name_norm}: {exc}")
                        stats["errors"] += 1

    return stats


# ---------------------------------------------------------------------------
# Phase 5: Batches
# ---------------------------------------------------------------------------

def backfill_batches(db: DatabaseManager, dry_run: bool) -> dict:
    stats = {"found": 0, "inserted": 0, "errors": 0}

    for client_code in list_clients():
        for req_id in list_requisitions(client_code):
            req_root = get_requisition_root(client_code, req_id)
            batches_dir = req_root / "resumes" / "batches"
            if not batches_dir.exists():
                continue

            for batch_dir in sorted(batches_dir.iterdir()):
                if not batch_dir.is_dir():
                    continue
                stats["found"] += 1
                try:
                    batch_type = _detect_batch_type(batch_dir)
                    manifest = batch_dir / "batch_manifest.yaml"
                    count = sum(
                        1 for _ in _iter_extracted_resumes(batch_dir, batch_type)
                    )

                    if dry_run:
                        print(f"  [DRY] Would insert batch: "
                              f"{batch_dir.name} / {req_id} "
                              f"({count} candidates, {batch_type})")
                    else:
                        db.upsert_batch(
                            req_id=req_id,
                            batch_name=batch_dir.name,
                            batch_type=batch_type,
                            candidate_count=count,
                            manifest_path=str(manifest)
                            if manifest.exists() else None,
                        )
                    stats["inserted"] += 1
                except Exception as exc:
                    print(f"  ERROR batch {batch_dir.name}: {exc}")
                    stats["errors"] += 1

    return stats


# ---------------------------------------------------------------------------
# Verify-only mode: compare DB counts vs file counts
# ---------------------------------------------------------------------------

def verify(db: DatabaseManager) -> None:
    print("\n=== Verification: DB counts vs filesystem ===\n")

    db_clients   = len(db.list_clients())
    db_reqs      = sum(
        len(db.list_requisitions(c["client_code"]))
        for c in db.list_clients()
    )
    db_assessed  = db.get_repository_stats()["total_candidates"]

    file_clients = len(list_clients())
    file_reqs    = sum(
        len(list_requisitions(c)) for c in list_clients()
    )
    file_assessed = sum(
        len([
            f for f in
            (get_requisition_root(c, r) / "assessments" / "individual").glob(
                "*.json"
            )
            if not f.stem.endswith("_lifecycle")
        ])
        for c in list_clients()
        for r in list_requisitions(c)
        if (get_requisition_root(c, r) / "assessments" / "individual").exists()
    )

    rows = [
        ("Clients",     file_clients,  db_clients),
        ("Requisitions", file_reqs,    db_reqs),
        ("Assessments", file_assessed, db_assessed),
    ]

    ok = True
    print(f"  {'Entity':<16} {'Files':>8} {'DB':>8} {'Match':>8}")
    print(f"  {'-'*44}")
    for label, files, db_count in rows:
        match = "OK" if files == db_count else "MISMATCH"
        if match == "MISMATCH":
            ok = False
        print(f"  {label:<16} {files:>8} {db_count:>8} {match:>8}")
    print()
    if ok:
        print("  All counts match.")
    else:
        print("  Mismatches found — re-run backfill_data.py to sync.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill existing RAAF file data into SQLite database"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be inserted without writing anything",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Compare DB row counts vs file counts and report gaps",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).parent.parent.parent / "data" / "raaf.db",
        help="Path to SQLite database file (default: data/raaf.db)",
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help=(
            "Root directory containing the clients/ folder. "
            "Defaults to the script's project root. "
            "Set to the production path when running from a worktree, "
            "e.g. --data-root /home/alonsop/RAAF"
        ),
    )
    args = parser.parse_args()

    if args.data_root:
        _patch_data_root(args.data_root.resolve())

    reset_db_instance()
    db = DatabaseManager(args.db)
    db.initialize()

    if args.verify_only:
        verify(db)
        return

    label = "[DRY RUN] " if args.dry_run else ""
    print(f"{label}Backfilling RAAF data into {args.db}\n")

    print("--- Clients ---")
    s = backfill_clients(db, args.dry_run)
    print(f"  Found {s['found']}, inserted {s['inserted']}, "
          f"errors {s['errors']}\n")

    print("--- Requisitions ---")
    s = backfill_requisitions(db, args.dry_run)
    print(f"  Found {s['found']}, inserted {s['inserted']}, "
          f"errors {s['errors']}\n")

    print("--- Assessments ---")
    s = backfill_assessments(db, args.dry_run)
    print(f"  Found {s['found']}, inserted {s['inserted']}, "
          f"errors {s['errors']}\n")

    print("--- Pending Candidates (no assessment yet) ---")
    s = backfill_pending_candidates(db, args.dry_run)
    print(f"  Found {s['found']}, inserted {s['inserted']}, "
          f"skipped {s['skipped']}, errors {s['errors']}\n")

    print("--- Batches ---")
    s = backfill_batches(db, args.dry_run)
    print(f"  Found {s['found']}, inserted {s['inserted']}, "
          f"errors {s['errors']}\n")

    if not args.dry_run:
        print("Rebuilding FTS5 index...")
        db.rebuild_fts_index()
        print("Done.\n")
        verify(db)
    else:
        print("[DRY RUN complete -- no data was written]")


if __name__ == "__main__":
    main()

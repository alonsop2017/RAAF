#!/usr/bin/env python3
"""Batch regenerate assessment frameworks for requisitions with missing or generic frameworks."""
import asyncio, sys, yaml
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

TARGETS = [
    ("cataldi_2026",  "REQ_2026_001_DIRFIN"),
    ("cataldi_2026",  "REQ-2026-007-PC"),
    ("efrat_2026",    "REQ-2025-1202-CEC"),
    ("efrat_2026",    "REQ-2026-001-ECSM"),
    ("efrat_europe",  "REQ-2026-001-Sales_Dir_EMEA"),
    ("efrat_europe",  "REQ-2026-004-BAE"),
    ("efrat_europe",  "REQ-2026-006-CAE"),
    ("tga_2026_05",   "REQ-2026-005-LQAR"),
]

async def get_jd_text(req_root, cfg):
    # 1. Local job description file
    for ext in (".pdf", ".docx"):
        jd_path = req_root / f"job_description{ext}"
        if jd_path.exists():
            try:
                if ext == ".pdf":
                    from scripts.utils.pdf_reader import extract_text
                    text = extract_text(jd_path, use_ocr_fallback=False)
                else:
                    from scripts.utils.docx_reader import extract_text
                    text = extract_text(jd_path)
                if text and text.strip():
                    return text.strip(), f"local file ({ext})"
            except Exception as e:
                print(f"    Local file extraction failed: {e}")

    # 2. Previously stored JD text
    stored = req_root / "framework" / "job_description_text.txt"
    if stored.exists():
        text = stored.read_text(encoding="utf-8", errors="ignore")
        lines = [l for l in text.splitlines() if not l.startswith("#")]
        text = "\n".join(lines).strip()
        if text:
            return text, "stored job_description_text.txt"

    # 3. PCR
    pcr_job_id = (cfg.get("pcr_integration") or {}).get("job_id") or cfg.get("pcr_job_id", "")
    if pcr_job_id:
        try:
            from scripts.utils.pcr_client import PCRClient
            client = PCRClient()
            client.ensure_authenticated()
            text = client.get_position_description(str(pcr_job_id))
            if text and text.strip():
                return text.strip(), f"PCR position {pcr_job_id}"
        except Exception as e:
            print(f"    PCR fetch failed: {e}")

    return None, "no source found"


async def main():
    from web.services.framework_generator import generate_framework

    results = []
    for client_code, req_id in TARGETS:
        req_root = Path(f"/app/clients/{client_code}/requisitions/{req_id}")
        yaml_path = req_root / "requisition.yaml"
        fw_path = req_root / "framework" / "assessment_framework.md"

        print(f"\n{'='*60}", flush=True)
        print(f"Processing: {client_code}/{req_id}", flush=True)

        if not yaml_path.exists():
            print(f"  SKIP — no requisition.yaml", flush=True)
            results.append((client_code, req_id, "SKIP", "no yaml"))
            continue

        cfg = yaml.safe_load(yaml_path.read_text()) or {}
        job = cfg.get("job", {})

        jd_text, source = await get_jd_text(req_root, cfg)
        if not jd_text:
            print(f"  SKIP — {source}", flush=True)
            results.append((client_code, req_id, "SKIP", source))
            continue

        print(f"  JD source: {source} ({len(jd_text)} chars)", flush=True)

        try:
            fw_path.parent.mkdir(parents=True, exist_ok=True)
            framework_md = await generate_framework(
                jd_text=jd_text,
                job_title=job.get("title", ""),
                department=job.get("department", ""),
                location=job.get("location", ""),
                experience_years_min=cfg.get("requirements", {}).get("experience_years_min", 0),
                education=cfg.get("requirements", {}).get("education", ""),
                notes=cfg.get("notes", ""),
            )
            fw_path.write_text(framework_md, encoding="utf-8")
            (req_root / "framework" / "job_description_text.txt").write_text(
                f"# Extracted Job Description Text\n# Source: {source}\n"
                f"# Generated: {datetime.now().strftime('%Y-%m-%d')}\n\n{jd_text}",
                encoding="utf-8"
            )
            print(f"  OK — framework generated ({len(framework_md)} chars)", flush=True)
            results.append((client_code, req_id, "OK", source))
        except Exception as e:
            print(f"  FAILED — {e}", flush=True)
            results.append((client_code, req_id, "FAILED", str(e)))

    print(f"\n{'='*60}")
    print("SUMMARY:")
    for r in results:
        print(f"  {r[2]:6} | {r[0]}/{r[1]} | {r[3]}")


if __name__ == "__main__":
    asyncio.run(main())

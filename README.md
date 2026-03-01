# RAAF - Resume Assessment Automation Framework

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Node.js 18+](https://img.shields.io/badge/node.js-18+-green.svg)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-teal.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)]()

A comprehensive automation framework for recruitment firms to assess candidate resumes against job requirements, producing professional assessment reports with hiring recommendations.

**Developed for Archtekt Consulting Inc. - Recruitment Services**

---

## Screenshots

### Dashboard
![Dashboard](docs/screenshots/dashboard.png)

### Requisition Detail
![Requisition Detail](docs/screenshots/requisition_detail.png)

### Assessments
![Assessments](docs/screenshots/assessments.png)

### PCR Integration
![PCR Integration](docs/screenshots/pcr.png)

<details>
<summary>More screenshots</summary>

### Clients
![Clients](docs/screenshots/clients.png)

### Requisitions
![Requisitions](docs/screenshots/requisitions.png)

### Candidates
![Candidates](docs/screenshots/candidates.png)

### Reports
![Reports](docs/screenshots/reports.png)

### Search
![Search](docs/screenshots/search.png)

</details>

---

## Overview

RAAF transforms the labor-intensive process of evaluating candidate resumes into a systematic, documented, and scalable operation. It integrates directly with **PCRecruiter (PCR)** to provide seamless candidate flow from job posting through Indeed to final assessment delivery.

### Key Features

- **Web Interface** - Modern, responsive FastAPI dashboard for managing the entire assessment workflow
- **Automated Resume Intake** - Continuous monitoring for new Indeed applicants via PCR API
- **Structured Assessment Framework** - 100-point scoring system with customizable templates
- **Professional Report Generation** - Polished DOCX reports with rankings and recommendations
- **Bi-Directional PCR Sync** - Scores and pipeline statuses pushed back to your ATS
- **Multi-Client Support** - Isolated data management for multiple clients and requisitions
- **SQLite Database** - Structured metadata storage with file-system fallback and dual-write migration support

### Time Savings

| Task | Manual Process | With RAAF |
|------|---------------|-----------|
| Resume organization | 30 min/candidate | Automated |
| Candidate scoring | 15-20 min/candidate | 2-3 min/candidate |
| Report compilation | 2-3 hours | 5 minutes |
| **Total (30 candidates)** | **12-15 hours** | **2-3 hours** |

---

## Architecture

### Runtime

RAAF runs as a **FastAPI web application** served by Uvicorn, managed as a **systemd service** (`raaf-web`) on a Raspberry Pi or any Linux host.

```
Browser → FastAPI (web/) → Routers → Services / Scripts → SQLite + Filesystem
                                   ↘ PCR API (PCRecruiter)
```

### Storage

Structured metadata is stored in **SQLite** (`data/raaf.db`). Binary files and documents remain on disk, referenced by path columns in the database.

| Stored in SQLite | Stored on Disk |
|-----------------|----------------|
| Clients, contacts | `resumes/batches/*/originals/*.pdf` / `*.docx` |
| Requisitions | `resumes/batches/*/extracted/*_resume.txt` |
| Candidates, batches | `framework/assessment_framework.md` |
| Assessments, scores | `reports/final/*.docx` / `reports/drafts/*.docx` |
| Reports (metadata) | `config/settings.yaml`, `config/pcr_credentials.yaml` |

### RAAF_DB_MODE

The `RAAF_DB_MODE` environment variable controls storage behaviour:

| Value | Behaviour |
|-------|-----------|
| `db` **(default)** | Reads/writes go to SQLite; YAML/JSON config files are not updated |
| `dual` | Writes go to both SQLite **and** YAML/JSON simultaneously (migration mode) |
| `files` | Legacy mode — reads/writes use YAML/JSON only; SQLite is not used |

**Rollback:** Set `RAAF_DB_MODE=files` to revert to file-based operation instantly. YAML/JSON files are never deleted.
**Rebuild DB from files:** `python scripts/migrate/backfill_data.py`

### Authentication

Google OAuth 2.0 via `web/auth/` — session-based, token stored in `config/.token_store.json`.

---

## Quick Start

### Prerequisites

- Python 3.11 or higher
- Node.js 18 or higher
- PCRecruiter account with API access

### Installation

```bash
# Clone the repository
git clone https://github.com/alonsop2017/RAAF.git
cd RAAF

# Install Python dependencies
pip install -r requirements.txt

# Install Node.js dependencies (for report generation)
cd scripts && npm install && cd ..

# Configure PCR credentials
cp config/pcr_credentials_template.yaml config/pcr_credentials.yaml
# Edit config/pcr_credentials.yaml with your credentials
```

### Web Interface

```bash
# Start the web application
./run_web.sh

# Or manually:
RAAF_DB_MODE=db python3 -m uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload
```

Access the web interface at **http://localhost:8000**

The web interface provides:
- Dashboard with overview of all clients and requisitions
- Client and requisition management
- Resume upload and candidate viewing
- Assessment dashboard with scoring and editing
- Report generation and download
- PCRecruiter sync operations
- Interview invitation management

### Service Management (systemd)

```bash
sudo systemctl restart raaf-web
sudo systemctl status raaf-web
sudo journalctl -u raaf-web -n 50
```

### CLI Usage

```bash
# 1. Initialize a new client
python3 scripts/init_client.py --code acme --name "Acme Corp"

# 2. Create a requisition
python3 scripts/init_requisition.py \
  --client acme \
  --req-id REQ-2025-001-CSM \
  --title "Customer Success Manager" \
  --template saas_csm

# 3. Sync candidates from PCR (or add resumes manually)
python3 scripts/pcr/sync_candidates.py --client acme --req REQ-2025-001-CSM
python3 scripts/pcr/download_resumes.py --client acme --req REQ-2025-001-CSM

# 4. Extract and assess candidates
python3 scripts/extract_resume.py --client acme --req REQ-2025-001-CSM
python3 scripts/create_batch.py --client acme --req REQ-2025-001-CSM
python3 scripts/assess_candidate.py --client acme --req REQ-2025-001-CSM --batch batch_20250119_1

# 5. Generate report
node scripts/generate_report.js --client acme --req REQ-2025-001-CSM --output-type final

# 6. Push scores back to PCR
python3 scripts/pcr/push_scores.py --client acme --req REQ-2025-001-CSM
```

---

## Project Structure

```
RAAF/
├── config/
│   ├── settings.yaml              # Global settings
│   ├── pcr_credentials.yaml       # PCR API credentials (not in repo)
│   ├── .token_store.json          # Google OAuth token (not in repo)
│   └── *_template.yaml            # Configuration templates
│
├── data/
│   └── raaf.db                    # SQLite database (not in repo)
│
├── web/                           # FastAPI web application
│   ├── app.py                     # App entrypoint, router registration
│   ├── auth/                      # Google OAuth 2.0 authentication
│   │   ├── config.py
│   │   ├── dependencies.py
│   │   ├── oauth.py
│   │   ├── session.py
│   │   └── token_store.py
│   ├── routers/                   # Route handlers
│   │   ├── admin.py
│   │   ├── assessments.py         # Assessment dashboard (DB-based)
│   │   ├── auth.py
│   │   ├── candidates.py          # Resume upload, candidate views
│   │   ├── clients.py
│   │   ├── correspondence.py      # Interview invitations (file-based)
│   │   ├── pcr.py                 # PCR sync operations
│   │   ├── reports.py             # Report generation and download
│   │   ├── requisitions.py        # Requisition list/detail (DB-based)
│   │   └── search.py
│   └── services/
│       ├── framework_generator.py # AI-assisted framework generation
│       └── google_drive.py        # Google Drive integration
│
├── templates/
│   ├── frameworks/                # Assessment framework templates
│   │   ├── base_framework_template.md
│   │   ├── saas_csm_template.md
│   │   ├── saas_ae_template.md
│   │   └── construction_pm_template.md
│   └── reports/                   # Report templates
│
├── clients/                       # Client and requisition data (not in repo)
│   └── [client_code]/
│       ├── client_info.yaml
│       └── requisitions/
│           └── [req_id]/
│               ├── requisition.yaml
│               ├── framework/
│               ├── resumes/
│               ├── assessments/
│               └── reports/
│
├── scripts/
│   ├── extract_resume.py          # Resume text extraction
│   ├── assess_candidate.py        # Candidate scoring
│   ├── create_batch.py            # Batch management
│   ├── generate_report.js         # DOCX report generation (Node.js)
│   ├── generate_interview_invitations.py
│   ├── init_client.py
│   ├── init_requisition.py
│   ├── list_requisitions.py
│   ├── pcr/                       # PCRecruiter integration
│   │   ├── cron_sync.sh           # Cron wrapper (sets PYTHONPATH + RAAF_DB_MODE)
│   │   ├── download_resumes.py    # Download resumes + optional auto-assess
│   │   ├── full_sync.py
│   │   ├── import_position.py
│   │   ├── push_scores.py
│   │   ├── refresh_token.py
│   │   ├── sync_candidates.py
│   │   ├── sync_positions.py
│   │   ├── test_connection.py
│   │   ├── update_pipeline.py
│   │   └── watch_applicants.py    # Continuous applicant monitoring
│   ├── migrate/                   # DB migration utilities
│   │   ├── 001_initial_schema.py
│   │   ├── backfill_data.py       # Sync files → DB
│   │   └── migrate_to_batches.py
│   └── utils/
│       ├── archive_requisition.py
│       ├── candidate_search.py
│       ├── claude_client.py       # Claude API wrapper
│       ├── client_utils.py        # Path helpers, normalize_candidate_name()
│       ├── database.py            # SQLite layer: save_assessment(), get_dashboard_data()
│       ├── docx_reader.py
│       ├── export_requisition.py
│       ├── list_archive.py
│       ├── normalize_filenames.py
│       ├── pcr_client.py          # PCR API client wrapper
│       ├── pdf_reader.py
│       ├── update_requisition.py
│       ├── validate_docx.py
│       └── validate_framework.py
│
├── docs/
│   ├── RAAF_Overview.pdf
│   └── RAAF_Overview.md
│
└── archive/                       # Completed requisitions
```

---

## Assessment Framework

### Scoring Categories (100 points)

| Category | Weight | Description |
|----------|--------|-------------|
| Core Experience | 25% | Years in role, industry alignment, education |
| Technical Skills | 20% | Tools, systems, domain expertise |
| Communication | 20% | Executive presence, presentation, collaboration |
| Strategic Acumen | 15% | Business impact, planning, problem-solving |
| Job Stability | 10% | Tenure patterns, flight risk assessment |
| Cultural Fit | 10% | Adaptability, initiative, values alignment |

### Recommendation Tiers

| Score | Recommendation | Action |
|-------|----------------|--------|
| 85%+ | STRONG RECOMMEND | Advance to interview immediately |
| 70-84% | RECOMMEND | Advance to interview |
| 55-69% | CONDITIONAL | Consider if top candidates unavailable |
| <55% | DO NOT RECOMMEND | Do not advance |

### Available Templates

- **SaaS Customer Success Manager** - Retention metrics, CRM proficiency, executive relationships
- **SaaS Account Executive** - Quota attainment, sales methodology, deal complexity
- **Construction Project Manager** - Safety certifications, project scale, subcontractor management
- **Base Template** - Generic framework adaptable to any role

---

## PCRecruiter Integration

RAAF provides deep integration with PCRecruiter:

### Inbound (PCR → RAAF)
- Import positions/jobs
- Sync candidate pipeline
- Download resumes automatically (`--auto-download`)
- Auto-assess after download (`--auto-assess`)
- Monitor for new Indeed applicants (`watch_applicants.py`)

### Outbound (RAAF → PCR)
- Push assessment scores (0-100)
- Update recommendation tier
- Add assessment notes to candidate records
- Update pipeline status based on recommendation

### Cron Sync

`scripts/pcr/cron_sync.sh` is the recommended wrapper for cron jobs — it sets `PYTHONPATH` and `RAAF_DB_MODE=db` so SQLite writes succeed from the cron environment.

### Setup

1. Get API credentials from [Main Sequence Developer Portal](https://main-sequence.3scale.net)
2. Copy `config/pcr_credentials_template.yaml` to `config/pcr_credentials.yaml`
3. Fill in your Database ID, username, password, and API key
4. Test connection: `python3 scripts/pcr/test_connection.py`

---

## Database

### Tables

| Table | Contents |
|-------|----------|
| `clients` | Client metadata |
| `client_contacts` | Client contact persons |
| `requisitions` | Job requisition details |
| `candidates` | Candidate records per requisition |
| `assessments` | Scored assessment results |
| `batches` | Assessment batch groupings |
| `reports` | Generated report metadata |
| `pcr_positions_cache` | Cached PCR position data |

### Maintenance

```bash
# Quick backup before upgrades
cp data/raaf.db data/raaf_backup_$(date +%Y%m%d).db

# Verify DB integrity
sqlite3 data/raaf.db "PRAGMA integrity_check;"

# Rebuild DB from YAML/JSON files
python scripts/migrate/backfill_data.py

# Rebuild FTS index after bulk import
python -c "from scripts.utils.database import get_db; get_db().rebuild_fts_index()"
```

---

## Scripts Reference

### Initialization
| Script | Description |
|--------|-------------|
| `init_client.py` | Create new client |
| `init_requisition.py` | Create new requisition |
| `list_requisitions.py` | List all requisitions |

### Processing
| Script | Description |
|--------|-------------|
| `extract_resume.py` | Extract text from PDF/DOCX |
| `create_batch.py` | Create assessment batch |
| `assess_candidate.py` | Score candidates |
| `generate_report.js` | Generate DOCX report |
| `generate_interview_invitations.py` | Generate invitation emails |

### PCR Integration
| Script | Description |
|--------|-------------|
| `pcr/test_connection.py` | Test API connection |
| `pcr/refresh_token.py` | Refresh PCR session token |
| `pcr/sync_positions.py` | Pull positions from PCR |
| `pcr/sync_candidates.py` | Pull candidates from pipeline |
| `pcr/download_resumes.py` | Download resume files |
| `pcr/push_scores.py` | Push scores to PCR |
| `pcr/update_pipeline.py` | Update pipeline status |
| `pcr/watch_applicants.py` | Monitor for new applicants |
| `pcr/cron_sync.sh` | Cron-safe sync wrapper |

### Migration & Management
| Script | Description |
|--------|-------------|
| `migrate/backfill_data.py` | Sync files → SQLite DB |
| `migrate/001_initial_schema.py` | Initialize DB schema |
| `context.py` | Set working context |
| `search_candidate.py` | Search across requisitions |
| `client_dashboard.py` | Client status overview |
| `utils/archive_requisition.py` | Archive completed requisitions |
| `utils/normalize_filenames.py` | Normalize resume filenames |
| `utils/validate_framework.py` | Validate framework completeness |

---

## Configuration

### Global Settings (`config/settings.yaml`)

```yaml
assessment:
  default_max_score: 100
  default_thresholds:
    strong_recommend: 85
    recommend: 70
    conditional: 55

stability:
  weights:
    four_plus_years: 10
    three_to_four_years: 8
    two_to_three_years: 6
    # ...

report:
  font_family: Arial
  body_font_size: 11
  header_shading: "D5E8F0"
```

### Per-Requisition Overrides

Each requisition can override default settings in `requisition.yaml`:

```yaml
assessment:
  thresholds:
    strong_recommend: 80  # Lower threshold for this role
  weight_overrides:
    technical_competencies: 30  # Increase for technical role
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `RAAF_DB_MODE` | `db` | Storage mode: `db`, `dual`, or `files` |
| `PYTHONPATH` | — | Must include project root for cron/systemd |

---

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Complete project context and instructions
- **[RAAF_Overview.pdf](docs/RAAF_Overview.pdf)** - Executive overview for company owners
- **[Assessment Templates](templates/frameworks/)** - Scoring framework templates

---

## Security Notes

- **Never commit** `config/pcr_credentials.yaml` (in `.gitignore`)
- **Never commit** `config/.token_store.json` (Google OAuth token)
- Client data in `clients/` and `data/raaf.db` are gitignored
- Assessment audit trail maintained in JSON files
- Archive system for completed requisitions

---

## License

Proprietary - Archtekt Consulting Inc.

---

## Support

For issues and feature requests, please contact the development team.

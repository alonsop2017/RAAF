# RAAF - Resume Assessment Automation Framework

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Node.js 18+](https://img.shields.io/badge/node.js-18+-green.svg)](https://nodejs.org/)
[![License](https://img.shields.io/badge/license-Proprietary-red.svg)]()

A comprehensive automation framework for recruitment firms to assess candidate resumes against job requirements, producing professional assessment reports with hiring recommendations.

**Developed for Archtekt Consulting Inc. - Recruitment Services**

---

## Overview

RAAF transforms the labor-intensive process of evaluating candidate resumes into a systematic, documented, and scalable operation. It integrates directly with **PCRecruiter (PCR)** to provide seamless candidate flow from job posting through Indeed to final assessment delivery.

### Key Features

- **Automated Resume Intake** - Continuous monitoring for new Indeed applicants via PCR API
- **Structured Assessment Framework** - 100-point scoring system with customizable templates
- **Professional Report Generation** - Polished DOCX reports with rankings and recommendations
- **Bi-Directional PCR Sync** - Scores and pipeline statuses pushed back to your ATS
- **Multi-Client Support** - Isolated data management for multiple clients and requisitions

### Time Savings

| Task | Manual Process | With RAAF |
|------|---------------|-----------|
| Resume organization | 30 min/candidate | Automated |
| Candidate scoring | 15-20 min/candidate | 2-3 min/candidate |
| Report compilation | 2-3 hours | 5 minutes |
| **Total (30 candidates)** | **12-15 hours** | **2-3 hours** |

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

### Basic Usage

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
│   └── *_template.yaml            # Configuration templates
│
├── templates/
│   ├── frameworks/                # Assessment framework templates
│   │   ├── base_framework_template.md
│   │   ├── saas_csm_template.md
│   │   ├── saas_ae_template.md
│   │   └── construction_pm_template.md
│   └── reports/                   # Report templates
│
├── clients/
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
│   ├── Main Scripts
│   │   ├── extract_resume.py      # Resume text extraction
│   │   ├── assess_candidate.py    # Candidate scoring
│   │   ├── create_batch.py        # Batch management
│   │   ├── generate_report.js     # DOCX report generation
│   │   └── ...
│   │
│   ├── pcr/                       # PCRecruiter integration
│   │   ├── test_connection.py
│   │   ├── sync_candidates.py
│   │   ├── download_resumes.py
│   │   ├── push_scores.py
│   │   └── ...
│   │
│   └── utils/                     # Utility modules
│       ├── client_utils.py
│       ├── pcr_client.py
│       ├── pdf_reader.py
│       └── ...
│
├── docs/
│   ├── RAAF_Overview.pdf          # Executive overview
│   └── RAAF_Overview.md           # Source document
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
- Download resumes automatically
- Monitor for new Indeed applicants

### Outbound (RAAF → PCR)
- Push assessment scores (0-100)
- Update recommendation tier
- Add assessment notes to candidate records
- Update pipeline status based on recommendation

### Setup

1. Get API credentials from [Main Sequence Developer Portal](https://main-sequence.3scale.net)
2. Copy `config/pcr_credentials_template.yaml` to `config/pcr_credentials.yaml`
3. Fill in your Database ID, username, password, and API key
4. Test connection: `python3 scripts/pcr/test_connection.py`

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

### PCR Integration
| Script | Description |
|--------|-------------|
| `pcr/test_connection.py` | Test API connection |
| `pcr/sync_candidates.py` | Pull candidates from pipeline |
| `pcr/download_resumes.py` | Download resume files |
| `pcr/push_scores.py` | Push scores to PCR |
| `pcr/update_pipeline.py` | Update pipeline status |
| `pcr/watch_applicants.py` | Monitor for new applicants |

### Management
| Script | Description |
|--------|-------------|
| `context.py` | Set working context |
| `search_candidate.py` | Search across requisitions |
| `client_dashboard.py` | Client status overview |
| `utils/archive_requisition.py` | Archive completed requisitions |

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

---

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Complete project context and instructions
- **[RAAF_Overview.pdf](docs/RAAF_Overview.pdf)** - Executive overview for company owners
- **[Assessment Templates](templates/frameworks/)** - Scoring framework templates

---

## Security Notes

- **Never commit** `config/pcr_credentials.yaml` (in `.gitignore`)
- Client data is isolated by folder structure
- Assessment audit trail maintained in JSON files
- Archive system for completed requisitions

---

## License

Proprietary - Archtekt Consulting Inc.

---

## Support

For issues and feature requests, please contact the development team.

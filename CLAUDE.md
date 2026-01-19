# CLAUDE.md - Resume Assessment Automation Framework
# Archtekt Consulting Inc. - Recruitment Services

## Project Overview

This repository automates the assessment of candidate resumes against client-provided job descriptions using a structured scoring framework. The system integrates with **PCRecruiter (PCR)** by Main Sequence Technology to automatically extract job descriptions and candidate resumes, evaluates candidates against a job-specific assessment framework, and produces professional assessment reports with hiring recommendations.

**Primary Workflow:**
1. Create Position in PCR (Company → Positions → "+") with job description and code (e.g., INDML for Indeed)
2. Candidates apply via Indeed and flow into PCR pipeline automatically
3. System syncs candidates and resumes from PCR
4. Assessment framework is created/adapted for the specific role
5. Resumes are batch-processed against the framework
6. Consolidated assessment report is generated with recommendations
7. Assessment scores are pushed back to PCR
8. Report is delivered to client for interview decisions

**Business Model:** Commission-based on percentage of annual salary for successful placements.

**ATS Integration:** PCRecruiter (PCR) by Main Sequence Technology (Cleveland, OH)
- API Documentation: https://www.pcrecruiter.net/apidocs_v2/
- Developer Portal: https://main-sequence.3scale.net

---

## Directory Structure

The structure isolates data by client and job requisition, enabling parallel work on multiple positions while preventing data cross-contamination.

```
project_root/
├── CLAUDE.md                              # This file - project context and instructions
├── config/
│   ├── settings.yaml                      # Global settings (thresholds, output formats, PCR config)
│   ├── pcr_credentials.yaml               # PCR API credentials (DO NOT COMMIT - in .gitignore)
│   └── clients/
│       └── [client_code].yaml             # Client-specific settings and contacts
│
├── templates/
│   ├── frameworks/
│   │   ├── base_framework_template.md     # Base assessment framework template
│   │   ├── saas_csm_template.md           # SaaS Customer Success Manager template
│   │   ├── saas_ae_template.md            # SaaS Account Executive template
│   │   └── construction_pm_template.md    # Construction Project Manager template
│   └── reports/
│       └── consolidated_report_template.md # Report structure template
│
├── clients/
│   └── [client_code]/                     # e.g., "techco", "buildcorp"
│       ├── client_info.yaml               # Client metadata, contacts, PCR company link
│       └── requisitions/
│           └── [req_id]/                  # e.g., "REQ-2025-001-CSM"
│               ├── requisition.yaml       # Job details, PCR position link, requirements
│               ├── job_description.pdf    # Original JD (auto-pulled from PCR or manual)
│               ├── framework/
│               │   ├── assessment_framework.pdf   # Finalized framework for this role
│               │   └── framework_notes.md         # Adaptations from template, client requests
│               ├── resumes/
│               │   ├── incoming/          # Raw resumes (auto-downloaded from PCR)
│               │   ├── processed/         # Extracted/normalized resumes
│               │   └── batches/
│               │       └── batch_[YYYYMMDD]_[n]/  # Organized by assessment batch
│               ├── assessments/
│               │   ├── individual/        # Per-candidate assessment JSON files
│               │   └── consolidated/      # Batch-level consolidated assessments
│               ├── reports/
│               │   ├── drafts/            # Work-in-progress reports
│               │   └── final/             # Client-ready deliverables
│               └── correspondence/        # Client communications, feedback
│
├── scripts/
│   ├── extract_resume.py                  # Resume text extraction
│   ├── assess_candidate.py                # Individual candidate scoring
│   ├── generate_report.js                 # Report generation using docx-js
│   ├── init_requisition.py                # Initialize new requisition structure
│   ├── pcr/                               # PCRecruiter integration scripts
│   │   ├── test_connection.py             # Test PCR API connection
│   │   ├── sync_positions.py              # Pull positions from PCR
│   │   ├── sync_candidates.py             # Pull candidates from PCR pipeline
│   │   ├── download_resumes.py            # Download resumes from PCR
│   │   ├── import_position.py             # Import PCR position as requisition
│   │   ├── push_scores.py                 # Push assessment scores to PCR
│   │   ├── update_pipeline.py             # Update candidate pipeline status
│   │   └── watch_applicants.py            # Monitor for new Indeed applicants
│   └── utils/
│       ├── pdf_reader.py
│       ├── docx_reader.py
│       ├── client_utils.py                # Client/requisition path helpers
│       └── pcr_client.py                  # PCR API client wrapper
│
├── archive/
│   └── [client_code]/
│       └── [req_id]_[YYYYMMDD]/           # Completed/closed requisitions
│
└── logs/
    └── [client_code]/
        └── [req_id]_assessment_[date].log
```

### Naming Conventions

| Element | Format | Example |
|---------|--------|---------|
| Client Code | lowercase, no spaces | `techco`, `buildcorp`, `acme_inc` |
| Requisition ID | `REQ-YYYY-NNN-ROLE` | `REQ-2025-001-CSM`, `REQ-2025-002-AE` |
| Batch Folder | `batch_YYYYMMDD_N` | `batch_20251226_1`, `batch_20251226_2` |
| Assessment File | `lastname_firstname_assessment.json` | `khattab_mohamed_assessment.json` |
| Report File | `[req_id]_assessment_report_[YYMMDD].docx` | `REQ-2025-001-CSM_assessment_report_251226.docx` |

### Requisition Configuration (requisition.yaml)

```yaml
requisition_id: REQ-2025-001-CSM
client_code: techco
created_date: 2025-12-20
status: active  # active, on_hold, filled, cancelled

job:
  title: Enterprise Customer Success Manager
  department: Customer Success
  location: Toronto, ON (Hybrid)
  salary_range:
    min: 95000
    max: 120000
    currency: CAD
  commission_rate: 0.20  # 20% of annual salary

requirements:
  experience_years_min: 5
  education: Bachelor's degree required
  industry_preference: SaaS/Technology
  special_requirements:
    - "Must have Salesforce experience"
    - "Bilingual (English/French) preferred"

assessment:
  framework_version: "1.0"
  max_score: 100
  thresholds:
    strong_recommend: 85
    recommend: 70
    conditional: 55
  # Override default weights if needed
  weight_overrides:
    technical_competencies: 25  # Increased from 20 for this role
    cultural_fit: 5             # Decreased from 10

contacts:
  hiring_manager: "Jane Smith, VP Customer Success"
  hr_contact: "Bob Johnson, Talent Acquisition"
  
notes: |
  Client emphasized need for candidates with enterprise experience.
  Previous hire churned after 6 months - stability is critical.
```

### Client Configuration (client_info.yaml)

```yaml
client_code: techco
company_name: TechCo Solutions Inc.
industry: SaaS / Enterprise Software
relationship_start: 2025-06-15
status: active

contacts:
  primary:
    name: Sarah Chen
    title: Director of Talent
    email: schen@techco.com
    phone: 416-555-1234
  billing:
    name: Accounts Payable
    email: ap@techco.com

billing:
  default_commission_rate: 0.20
  payment_terms: Net 30
  guarantee_period_days: 90

preferences:
  report_format: docx
  delivery_method: email
  include_rejected_candidates: false  # Don't show DNR candidates in reports
  
active_requisitions:
  - REQ-2025-001-CSM
  - REQ-2025-002-AE
```

---

## Tech Stack

- **Python 3.11+** - Primary automation language
- **Node.js 18+** - Document generation (docx-js)
- **Libraries:**
  - `pdfplumber` or `pymupdf` - PDF text extraction
  - `python-docx` - DOCX reading (for resumes)
  - `docx` (npm) - Report generation
  - `pyyaml` - Configuration management
  - `pandas` - Data aggregation and ranking

---

## Assessment Framework Structure

Each job-specific framework follows this scoring model (adapt weights per client requirements):

### Standard Framework Categories

| Category | Default Weight | Description |
|----------|---------------|-------------|
| Core Experience & Qualifications | 25% | Years of experience, industry alignment, education |
| Technical & Analytical Competencies | 20% | Tools, data skills, domain-specific technical knowledge |
| Relationship & Communication Skills | 20% | Executive presence, presentation, collaboration |
| Strategic & Business Acumen | 15% | Planning, expansion/growth mindset, risk management |
| Job Stability Assessment | 10% | Tenure analysis (last 3 roles) |
| Cultural Fit & Soft Skills | 10% | Customer-centricity, adaptability, initiative |

### Scoring Scale

- **Total Points:** 100 (or 85 for simplified frameworks without cultural fit)
- **Recommendation Thresholds:**
  - STRONG RECOMMEND: 85%+ (or 80% for simplified)
  - RECOMMEND: 70-84% (or 65-79%)
  - CONDITIONAL: 55-69% (or 50-64%)
  - DO NOT RECOMMEND: <55% (or <50%)

### Job Stability Calculation

Calculate average tenure across last 3 positions:
- 4+ years average: 10/10 (Low Risk)
- 3-3.9 years: 8/10 (Low-Medium Risk)
- 2-2.9 years: 6/10 (Medium Risk)
- 1.5-1.9 years: 4/10 (Medium-High Risk)
- 1-1.4 years: 2/10 (High Risk)
- <1 year: 0/10 (Very High Risk)

---

## Coding Conventions

### Python Style
- Follow PEP 8 with Black formatting (line length 100)
- Use type hints for all function signatures
- Google-style docstrings
- Snake_case for functions and variables
- PascalCase for classes

### File Naming
- Resumes: `[lastname]_[firstname]_resume.[ext]` (normalize on ingestion)
- Assessments: `[lastname]_[firstname]_assessment.json`
- Reports: `[client]_[role]_assessment_report_[YYMMDD].docx`

### JSON Assessment Output Structure

```json
{
  "metadata": {
    "client_code": "techco",
    "requisition_id": "REQ-2025-001-CSM",
    "framework_version": "1.0",
    "assessed_at": "2025-12-26T14:30:00Z",
    "assessor": "Claude/Automated"
  },
  "candidate": {
    "name": "Mohamed Khattab",
    "name_normalized": "khattab_mohamed",
    "email": "extracted if available",
    "phone": "extracted if available",
    "source_file": "original_filename.pdf",
    "source_platform": "Indeed",
    "batch": "batch_20251226_1"
  },
  "scores": {
    "core_experience": {
      "score": 20,
      "max": 25,
      "breakdown": {
        "years_experience": {"score": 8, "max": 10, "evidence": "8+ years at Rogers, DealTap"},
        "enterprise_accounts": {"score": 7, "max": 8, "evidence": "Multi-million dollar book"},
        "education": {"score": 3, "max": 4, "evidence": "Bachelor's degree noted"},
        "language": {"score": 2, "max": 3, "evidence": "Native English fluency"}
      },
      "notes": "Strong enterprise background in telecom and SaaS"
    },
    "technical_competencies": {
      "score": 15,
      "max": 20,
      "breakdown": {
        "data_driven": {"score": 6, "max": 8, "evidence": "A/B testing, behavioral analytics"},
        "saas_knowledge": {"score": 5, "max": 7, "evidence": "DealTap SaaS experience"},
        "renewal_track_record": {"score": 4, "max": 5, "evidence": "26% churn reduction"}
      },
      "notes": "Strong analytics; SaaS depth could be deeper"
    },
    "communication_skills": {
      "score": 16,
      "max": 20,
      "breakdown": {
        "executive_engagement": {"score": 7, "max": 8, "evidence": "Senior Manager level"},
        "presentation_skills": {"score": 5, "max": 7, "evidence": "Customer education programs"},
        "collaboration": {"score": 4, "max": 5, "evidence": "Cross-functional implied"}
      },
      "notes": "Leadership roles suggest strong executive presence"
    },
    "strategic_acumen": {
      "score": 10,
      "max": 15,
      "breakdown": {
        "account_planning": {"score": 4, "max": 6, "evidence": "41% digital adoption increase"},
        "expansion_skills": {"score": 3, "max": 5, "evidence": "Not explicitly stated"},
        "risk_management": {"score": 3, "max": 4, "evidence": "Churn reduction focus"}
      },
      "notes": "Results-oriented but expansion experience unclear"
    },
    "job_stability": {
      "score": 8,
      "max": 10,
      "tenure_analysis": {
        "positions": [
          {"company": "Rogers", "months": 96, "role": "Senior Manager"},
          {"company": "DealTap", "months": 36, "role": "CSM"}
        ],
        "average_months": 66,
        "risk_level": "Low"
      },
      "notes": "Excellent stability - 8 years at Rogers"
    },
    "cultural_fit": {
      "score": 7,
      "max": 10,
      "breakdown": {
        "customer_centricity": {"score": 3, "max": 4, "evidence": "Customer education focus"},
        "adaptability": {"score": 2, "max": 3, "evidence": "Transition to SaaS"},
        "initiative": {"score": 2, "max": 3, "evidence": "$12M cost savings"}
      },
      "notes": "Strong ownership demonstrated"
    }
  },
  "total_score": 76,
  "max_score": 100,
  "percentage": 76,
  "recommendation": "RECOMMEND",
  "recommendation_tier": 2,
  "summary": "Strong enterprise customer success background with proven metrics at Rogers (8 years) and DealTap SaaS (3 years). Demonstrated impact: 41% digital adoption increase, 26% churn reduction, $12M cost savings. Excellent job stability. Minor gap in explicit expansion/upsell experience.",
  "key_strengths": [
    "8+ years enterprise customer success experience",
    "Proven quantifiable results (churn reduction, cost savings)",
    "Excellent job stability",
    "Strong analytics and data-driven approach"
  ],
  "areas_of_concern": [
    "Limited explicit upsell/expansion track record",
    "SaaS experience concentrated in one company (DealTap)"
  ],
  "interview_focus_areas": [
    "Probe for specific expansion/upsell examples",
    "Understand transition from telecom to SaaS",
    "Explore executive relationship-building approach"
  ]
}
```

---

## Common Commands

### PCRecruiter (PCR) Integration Commands

```bash
# Test PCR API connection
python scripts/pcr/test_connection.py

# Refresh PCR session token
python scripts/pcr/refresh_token.py

# Pull all open positions from PCR
python scripts/pcr/sync_positions.py --status Open

# Import a PCR position as a new requisition
python scripts/pcr/import_position.py \
  --job-id 12345 \
  --client techco \
  --req-id REQ-2025-001-CSM

# Pull candidates from PCR pipeline for a requisition
python scripts/pcr/sync_candidates.py \
  --client techco \
  --req REQ-2025-001-CSM

# Download all resumes for candidates in a requisition
python scripts/pcr/download_resumes.py \
  --client techco \
  --req REQ-2025-001-CSM

# Pull new candidates since last sync (incremental)
python scripts/pcr/sync_candidates.py --since-last-sync

# Watch for new Indeed applicants (continuous monitoring)
python scripts/pcr/watch_applicants.py --interval 15

# Push assessment scores back to PCR
python scripts/pcr/push_scores.py \
  --client techco \
  --req REQ-2025-001-CSM

# Update candidate pipeline status in PCR
python scripts/pcr/update_pipeline.py \
  --client techco \
  --req REQ-2025-001-CSM

# Full sync: positions + candidates + resumes for a client
python scripts/pcr/full_sync.py --client techco
```

### Requisition Initialization

```bash
# Initialize a new client
python scripts/init_client.py --code techco --name "TechCo Solutions Inc."

# Initialize a new requisition for a client
python scripts/init_requisition.py \
  --client techco \
  --req-id REQ-2025-001-CSM \
  --title "Enterprise Customer Success Manager" \
  --template saas_csm

# List active requisitions for a client
python scripts/list_requisitions.py --client techco --status active

# List all active requisitions across all clients
python scripts/list_requisitions.py --status active
```

### Resume Processing

```bash
# Extract text from all resumes in a requisition's incoming folder
python scripts/extract_resume.py \
  --client techco \
  --req REQ-2025-001-CSM \
  --input incoming \
  --output processed

# Create a new batch from processed resumes
python scripts/create_batch.py \
  --client techco \
  --req REQ-2025-001-CSM \
  --batch-name batch_20251226_1

# Assess a single candidate within a requisition
python scripts/assess_candidate.py \
  --client techco \
  --req REQ-2025-001-CSM \
  --resume khattab_mohamed.txt

# Batch assess all candidates in a specific batch
python scripts/assess_candidate.py \
  --client techco \
  --req REQ-2025-001-CSM \
  --batch batch_20251226_1

# Assess all unprocessed resumes in a requisition
python scripts/assess_candidate.py \
  --client techco \
  --req REQ-2025-001-CSM \
  --all-pending
```

### Report Generation

```bash
# Generate consolidated report for a requisition (all batches)
node scripts/generate_report.js \
  --client techco \
  --req REQ-2025-001-CSM \
  --output-type final

# Generate report for a specific batch only
node scripts/generate_report.js \
  --client techco \
  --req REQ-2025-001-CSM \
  --batch batch_20251226_1 \
  --output-type draft

# Generate report with custom thresholds (overrides requisition.yaml)
node scripts/generate_report.js \
  --client techco \
  --req REQ-2025-001-CSM \
  --strong-threshold 80 \
  --recommend-threshold 65
```

### Cross-Requisition Operations

```bash
# Compare candidate across multiple requisitions (same client)
python scripts/compare_candidate.py \
  --client techco \
  --candidate "Mohamed Khattab" \
  --reqs REQ-2025-001-CSM REQ-2025-002-AE

# Search for candidate across all client requisitions
python scripts/search_candidate.py \
  --client techco \
  --name "David Goodfellow"

# Generate client summary report (all active requisitions)
node scripts/generate_client_summary.js \
  --client techco \
  --status active
```

### Utilities

```bash
# Validate framework completeness for a requisition
python scripts/utils/validate_framework.py \
  --client techco \
  --req REQ-2025-001-CSM

# Normalize resume filenames in incoming folder
python scripts/utils/normalize_filenames.py \
  --client techco \
  --req REQ-2025-001-CSM

# Archive completed requisition
python scripts/utils/archive_requisition.py \
  --client techco \
  --req REQ-2025-001-CSM \
  --status filled

# Update requisition status
python scripts/utils/update_requisition.py \
  --client techco \
  --req REQ-2025-001-CSM \
  --status on_hold \
  --note "Client paused hiring - budget review"

# Export requisition data for backup
python scripts/utils/export_requisition.py \
  --client techco \
  --req REQ-2025-001-CSM \
  --format zip
```

### Quick Context Commands

```bash
# Show current working context (last accessed client/requisition)
python scripts/context.py --show

# Set working context (avoids repeating --client --req flags)
python scripts/context.py --set --client techco --req REQ-2025-001-CSM

# Run command using current context
python scripts/assess_candidate.py --use-context --batch batch_20251226_1

# Clear working context
python scripts/context.py --clear
```

---

## Assessment Workflow Instructions

### PCR-Integrated Workflow (Recommended)

This workflow leverages PCRecruiter for job posting and candidate management, with automatic resume extraction.

#### Step 0: One-Time PCR Setup

1. **Configure PCR API credentials:**
   ```bash
   # Copy template and fill in credentials
   cp config/pcr_credentials_template.yaml config/pcr_credentials.yaml
   # Edit with your Database ID, username, password, and API key
   ```

2. **Test connection:**
   ```bash
   python scripts/pcr/test_connection.py
   ```

3. **Link client to PCR Company:**
   - In `client_info.yaml`, set `pcr_integration.company.company_id` to the PCR Company ID

#### Step 1: Create Position in PCR

1. **In PCR application:**
   - Navigate to the Company record
   - Click **Positions** tab
   - Click **"+"** to add new position
   - Enter job title and description
   - Set **Job Code** = `INDML` (for Indeed posting)
   - Save and note the Job ID

2. **Import position to assessment system:**
   ```bash
   python scripts/pcr/import_position.py \
     --job-id [PCR_JOB_ID] \
     --client [client_code] \
     --req-id REQ-YYYY-NNN-ROLE
   ```
   This creates the requisition folder structure and links to PCR.

#### Step 2: Prepare Assessment Framework

1. Review the auto-generated framework from template in `[req]/framework/`
2. Adapt categories and weights to specific job requirements
3. Document adaptations in `framework_notes.md`
4. Export finalized framework as `assessment_framework.pdf`
5. Update `requisition.yaml` with `framework_version`

#### Step 3: Monitor for Candidates (Automated)

Candidates apply via Indeed → flow into PCR pipeline automatically.

**Option A: Continuous monitoring**
```bash
# Start applicant watcher (runs in background)
python scripts/pcr/watch_applicants.py --interval 15
```

**Option B: Manual sync**
```bash
# Pull new candidates from PCR
python scripts/pcr/sync_candidates.py --client [code] --req [req_id]

# Download their resumes
python scripts/pcr/download_resumes.py --client [code] --req [req_id]
```

#### Step 4: Assess Candidates

1. Extract text from downloaded resumes:
   ```bash
   python scripts/extract_resume.py --client [code] --req [req_id]
   ```

2. Create batch and run assessment:
   ```bash
   python scripts/create_batch.py --client [code] --req [req_id] --batch-name batch_YYYYMMDD_N
   python scripts/assess_candidate.py --client [code] --req [req_id] --batch [batch_name]
   ```

3. Review individual assessment JSONs and adjust if needed

#### Step 5: Generate Report & Push to PCR

1. Generate report:
   ```bash
   node scripts/generate_report.js --client [code] --req [req_id] --output-type final
   ```

2. Push assessment results back to PCR:
   ```bash
   # Push scores to PCR candidate records
   python scripts/pcr/push_scores.py --client [code] --req [req_id]
   
   # Update pipeline status (Interview, Hold, Rejected)
   python scripts/pcr/update_pipeline.py --client [code] --req [req_id]
   ```

#### Step 6: Deliver to Client

1. Final review of consolidated report
2. Deliver per client preferences
3. Save correspondence to `[req]/correspondence/`

#### Step 7: Post-Delivery

1. Record client feedback
2. Track interview outcomes in PCR
3. When position is filled:
   ```bash
   python scripts/utils/archive_requisition.py --client [code] --req [req_id] --status filled
   ```

---

### Manual Workflow (Without PCR)

Use this workflow when receiving resumes directly via email instead of through PCR.

#### Step 0: Client and Requisition Setup

**For New Clients:**
1. Initialize client folder: `python scripts/init_client.py --code [code] --name "[Company Name]"`
2. Complete `client_info.yaml` with contacts, billing preferences, commission rates
3. Verify client preferences for report format and content

**For New Requisitions:**
1. Receive job description from client
2. Initialize requisition: `python scripts/init_requisition.py --client [code] --req-id [REQ-YYYY-NNN-ROLE] --title "[Job Title]" --template [template_name]`
3. Place original job description PDF in requisition folder
4. Complete `requisition.yaml` with job details, requirements, special instructions
5. Document any client requirements not in job description under `notes`

#### Step 1: Prepare the Assessment Framework

1. Review the auto-generated framework from template in `[req]/framework/`
2. Adapt categories and weights to specific job requirements
3. Document adaptations in `framework_notes.md`:
   - Why weights were adjusted
   - Additional criteria added per client request
   - Scoring clarifications for edge cases
4. Export finalized framework as `assessment_framework.pdf`
5. Update `requisition.yaml` with `framework_version`

#### Step 2: Ingest Resumes

1. Download resumes from Indeed emails to `[req]/resumes/incoming/`
2. Run filename normalization:
   ```bash
   python scripts/utils/normalize_filenames.py --client [code] --req [req_id]
   ```
3. Extract text for processing:
   ```bash
   python scripts/extract_resume.py --client [code] --req [req_id]
   ```
4. Create batch folder for this assessment round:
   ```bash
   python scripts/create_batch.py --client [code] --req [req_id] --batch-name batch_YYYYMMDD_N
   ```

#### Step 3: Assess Candidates

1. Run batch assessment:
   ```bash
   python scripts/assess_candidate.py --client [code] --req [req_id] --batch [batch_name]
   ```
2. Review individual assessment JSONs in `[req]/assessments/individual/`
3. Manually adjust scores if extraction missed key information
4. Document any manual adjustments in assessment JSON `notes` fields

#### Step 4: Generate Report

1. Generate draft report:
   ```bash
   node scripts/generate_report.js --client [code] --req [req_id] --output-type draft
   ```
2. Review draft in `[req]/reports/drafts/`
3. Verify:
   - Recommendation thresholds applied correctly
   - Candidate ranking is accurate
   - Top candidate summaries are complete
   - Formatting matches client preferences
4. Generate final report:
   ```bash
   node scripts/generate_report.js --client [code] --req [req_id] --output-type final
   ```
5. Add evaluator signature block if required

#### Step 5: Deliver to Client

1. Final review of consolidated report in `[req]/reports/final/`
2. Deliver per client preferences (email, portal, etc.)
3. Save any client correspondence to `[req]/correspondence/`
4. Update `requisition.yaml` status if needed

#### Step 6: Post-Delivery

1. Record client feedback in `[req]/correspondence/`
2. Track interview outcomes and placements
3. When requisition is filled or cancelled:
   ```bash
   python scripts/utils/archive_requisition.py --client [code] --req [req_id] --status [filled|cancelled]
   ```

---

## Report Format Specifications

### Document Structure (following client sample format)

1. **Title Page**
   - CONSOLIDATED CANDIDATE ASSESSMENT REPORT
   - Position title
   - Assessment date, total candidates, confidentiality notice

2. **Executive Summary**
   - Framework reference
   - Scoring methodology (brief)
   - Recommendation thresholds
   - Summary counts by recommendation tier

3. **Complete Candidate Ranking Table**
   - Columns: Rank, Candidate Name, Batch, Score, %, Stability, Recommendation
   - Sorted by percentage descending
   - Bold formatting for STRONG RECOMMEND and RECOMMEND candidates

4. **Top Candidate Profiles**
   - Top 6 candidates with detailed summaries
   - Include: Batch, Score, Stability rating
   - Narrative highlighting relevant experience

5. **Hiring Recommendations**
   - Primary Recommendations (advance to interview)
   - Conditional Candidates (consider if primary unavailable)
   - Not Recommended (do not advance) with summary of common gaps

6. **Batch Analysis**
   - Breakdown by batch
   - Top candidate per batch

7. **Signature Block**
   - Evaluator signature line
   - Report generation date
   - Framework reference

### Formatting Standards

- Font: Arial 11pt body, 14pt headings
- Margins: 1 inch all sides
- Tables: Light gray header row (#D5E8F0), bordered cells
- Page numbers in footer
- Confidentiality notice in header

---

## Domain-Specific Context

### SaaS/Technology Roles (CSM, Account Manager)

Key assessment indicators:
- Experience with specific CRM platforms (Salesforce, HubSpot, Zendesk)
- Retention and expansion metrics (NRR, churn rate)
- Technical product understanding (APIs, integrations, ITSM)
- Executive Business Review (EBR) experience
- Multi-year renewal ownership

### Construction/Project Management Roles

Key assessment indicators:
- Project scale and budget responsibility
- Safety certifications and compliance experience
- Subcontractor management experience
- Specific trade/industry alignment
- Technology adoption (project management software)

---

## Things to Avoid

- **Do not** store or include candidate personal identifiers beyond name and contact info
- **Do not** include age, photos, or protected class information in assessments
- **Do not** use Unicode bullet characters in DOCX output (use proper list formatting)
- **Do not** hardcode recommendation thresholds (use config file)
- **Do not** overwrite framework files without versioning
- **Do not** assess candidates without a framework - create one first

---

## Testing and Validation

```bash
# Run assessment validation on sample resume
python -m pytest tests/test_assessment.py -v

# Validate report generation
node scripts/generate_report.js --test --output /tmp/test_report.docx

# Check DOCX validity
python scripts/utils/validate_docx.py reports/latest_report.docx
```

---

## Configuration Reference

### Global Settings (config/settings.yaml)

```yaml
# Default assessment settings (can be overridden per requisition)
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
    eighteen_months_to_two_years: 4
    one_to_eighteen_months: 2
    less_than_one_year: 0

report:
  font_family: Arial
  body_font_size: 11
  heading_font_size: 14
  margins_inches: 1.0
  header_shading: "D5E8F0"

output:
  date_format: "%Y-%m-%d"
  filename_date_format: "%y%m%d"

# Path patterns (use {client} and {req} placeholders)
paths:
  client_root: "clients/{client}"
  requisition_root: "clients/{client}/requisitions/{req}"
  archive_root: "archive/{client}"
  log_root: "logs/{client}"

# Context persistence
context:
  file: ".current_context.yaml"
  auto_save: true
```

### Template Framework Categories (templates/frameworks/)

Each role template defines default categories and weights:

**SaaS CSM Template (saas_csm_template.md):**
```yaml
categories:
  core_experience:
    weight: 25
    criteria:
      - years_in_customer_success
      - enterprise_account_management
      - saas_industry_experience
  technical_competencies:
    weight: 20
    criteria:
      - crm_proficiency
      - data_analysis_skills
      - product_technical_knowledge
  # ... additional categories
```

**Construction PM Template (construction_pm_template.md):**
```yaml
categories:
  core_experience:
    weight: 30
    criteria:
      - years_in_project_management
      - project_scale_budget
      - construction_industry_experience
  technical_competencies:
    weight: 20
    criteria:
      - pm_software_proficiency
      - estimating_skills
      - safety_certifications
  # ... additional categories
```

---

## Integration Notes

### Indeed Resume Downloads

Resumes downloaded from Indeed typically come as:
- PDF format (most common)
- Occasionally DOCX
- Named with candidate name or Indeed's internal ID

The ingestion process should:
1. Handle both formats
2. Normalize filenames to `lastname_firstname` pattern
3. Preserve original file in requisition's `incoming/` folder for reference
4. Track source (Indeed, LinkedIn, referral) in assessment metadata

### Claude Projects Integration

Assessment frameworks created in Claude Projects should be:
1. Exported as PDF or markdown
2. Placed in the requisition's `framework/` folder
3. Referenced via `requisition.yaml` framework settings

Note: Claude Code cannot directly access Claude Projects - frameworks must be manually exported and placed in this repository structure.

### Working with Multiple Requisitions

**Parallel Processing:**
- Each requisition is fully isolated - no shared state
- Can process batches for different requisitions simultaneously
- Context commands (`scripts/context.py`) help switch between active requisitions

**Candidate Overlap:**
- Same candidate may apply to multiple requisitions
- Use `search_candidate.py` to check for existing assessments
- Assessment scores are requisition-specific (different frameworks)
- Consider noting prior assessments in new assessment's notes

**Client Dashboard Pattern:**
```bash
# Quick status check across all client requisitions
python scripts/client_dashboard.py --client techco

# Output:
# TechCo Solutions Inc. - Active Requisitions
# ─────────────────────────────────────────────
# REQ-2025-001-CSM | Enterprise CSM    | 32 assessed | 4 recommended | Report: Final
# REQ-2025-002-AE  | Account Executive | 18 assessed | 2 recommended | Report: Draft
# REQ-2025-003-PM  | Project Manager   | 0 assessed  | Pending       | Framework: Ready
```

---

## Data Isolation Principles

### Why Isolation Matters

- **Client confidentiality:** Candidate data for Client A must never leak to Client B
- **Assessment integrity:** Each requisition has its own framework; cross-contamination invalidates scores
- **Audit trail:** Clear provenance of which framework assessed which candidates
- **Parallel processing:** Multiple recruiters/processes can work simultaneously without conflicts

### Isolation Boundaries

| Boundary | Isolation Level | Shared Resources |
|----------|-----------------|------------------|
| Client | Complete | Global config, templates only |
| Requisition | Complete within client | Client info, nothing else |
| Batch | Logical grouping | Requisition framework, settings |
| Candidate | Per-requisition | None - same person gets separate assessments per req |

### Data Flow Rules

1. **Resumes never move between requisitions** - if a candidate applies to multiple roles, their resume exists separately in each requisition's folder

2. **Assessments are requisition-bound** - an assessment JSON belongs to exactly one requisition and references only that requisition's framework

3. **Reports aggregate within requisition only** - consolidated reports pull from one requisition's assessments only

4. **Cross-requisition queries are read-only** - searching for candidates across requisitions doesn't modify any data

5. **Archive preserves structure** - when archiving, the entire requisition folder moves as a unit

---

## Maintenance

### Regular Maintenance Tasks

**Daily:**
- Process incoming resumes for active requisitions
- Update requisition statuses as needed

**Weekly:**
- Review `logs/` for errors or warnings
- Check for stale requisitions (no activity > 30 days)
- Back up `clients/` directory

**Monthly:**
- Archive completed/cancelled requisitions older than 60 days
- Update framework templates based on lessons learned
- Review client configurations for accuracy

**Quarterly:**
- Audit archived requisitions for retention policy compliance
- Update role templates with new industry patterns
- Review and update global threshold settings

### Archive Management

```bash
# Archive requisition (moves to archive/[client]/[req_id]_[YYYYMMDD]/)
python scripts/utils/archive_requisition.py \
  --client techco \
  --req REQ-2025-001-CSM \
  --status filled

# List archived requisitions for a client
python scripts/utils/list_archive.py --client techco

# Restore archived requisition (for reference only - creates read-only copy)
python scripts/utils/restore_archive.py \
  --client techco \
  --archive-id REQ-2025-001-CSM_20260115 \
  --destination /tmp/reference/
```

### Backup Strategy

```bash
# Full backup of all client data
tar -czvf backup_$(date +%Y%m%d).tar.gz clients/ config/ templates/

# Client-specific backup
tar -czvf techco_backup_$(date +%Y%m%d).tar.gz clients/techco/

# Requisition-specific backup (for handoff)
tar -czvf REQ-2025-001-CSM_handoff.tar.gz \
  clients/techco/requisitions/REQ-2025-001-CSM/
```

### Log Retention

- Active requisition logs: Keep indefinitely
- Archived requisition logs: Keep 1 year, then delete
- Global error logs: Keep 90 days

# SQLite Migration Plan for RAAF

## Context

RAAF currently stores all data as files on disk: YAML configs for clients/requisitions, JSON files for assessments, TXT/PDF files for resumes. There is no database. Every web request scans directories and reads multiple files - the dashboard iterates ALL clients and ALL requisitions, counting files via glob. Candidate search does a full scan of every assessment JSON across every requisition. This is slow, doesn't support concurrent writes, and scales poorly.

This plan migrates structured data (clients, requisitions, candidates, assessments) to SQLite while keeping binary files (PDFs, DOCX, resume text files) on disk. SQLite requires no new Python dependencies (built into stdlib), no server process, and is ideal for the Raspberry Pi deployment.

---

## Phase 1: Database Infrastructure

**Create `scripts/utils/database.py`** (~400 lines) with:

- `DatabaseManager` class with connection management (context manager, `sqlite3.Row` factory, `PRAGMA foreign_keys = ON`)
- Schema creation method with these tables:

| Table | Key Columns | Notes |
|-------|------------|-------|
| `clients` | client_code (UNIQUE), company_name, industry, status, pcr_company_name, billing fields, `preferences_json` TEXT | Replaces `client_info.yaml` |
| `client_contacts` | client_id FK, contact_type, name, email, phone | Normalized from YAML contacts dict |
| `requisitions` | req_id (UNIQUE), client_id FK, job_title, salary fields, status, threshold fields, pcr fields, job_description_file, framework_source, framework_generated_at, `weight_overrides_json` TEXT, `special_requirements_json` TEXT | Replaces `requisition.yaml` |
| `candidates` | requisition_id FK, name, name_normalized, email, source_platform, batch, resume file paths, status | UNIQUE(requisition_id, name_normalized). Currently implicit from file existence |
| `assessments` | candidate_id FK (UNIQUE), requisition_id FK, total_score, percentage, recommendation, assessment_mode, ai_model, `scores_json` TEXT, summary, `key_strengths_json` TEXT, `areas_of_concern_json` TEXT | Replaces `*_assessment.json`. Nested score breakdowns stored as JSON text (SQLite supports `json_extract`) |
| `reports` | requisition_id FK, filename, file_path, report_status, generated_at | Tracks report files on disk |
| `batches` | requisition_id FK, batch_name, batch_type, candidate_count, manifest_path | Replaces batch directory scanning |

### Schema Details

**`clients` table:**
```sql
CREATE TABLE clients (
  id INTEGER PRIMARY KEY,
  client_code TEXT UNIQUE NOT NULL,
  company_name TEXT NOT NULL,
  industry TEXT,
  status TEXT DEFAULT 'active',
  pcr_company_name TEXT,              -- PCR company name for position search
  default_commission_rate REAL,
  payment_terms TEXT,
  guarantee_period_days INTEGER,
  preferences_json TEXT,              -- report_format, delivery_method, etc.
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**`requisitions` table:**
```sql
CREATE TABLE requisitions (
  id INTEGER PRIMARY KEY,
  req_id TEXT UNIQUE NOT NULL,
  client_id INTEGER NOT NULL REFERENCES clients(id),
  job_title TEXT NOT NULL,
  department TEXT,
  location TEXT,
  salary_min INTEGER DEFAULT 0,
  salary_max INTEGER DEFAULT 0,
  salary_currency TEXT DEFAULT 'CAD',
  commission_rate REAL,
  status TEXT DEFAULT 'active',       -- active, on_hold, filled, cancelled
  experience_years_min INTEGER DEFAULT 0,
  education TEXT,
  threshold_strong INTEGER DEFAULT 85,
  threshold_recommend INTEGER DEFAULT 70,
  threshold_conditional INTEGER DEFAULT 55,
  framework_version TEXT DEFAULT '1.0',
  max_score INTEGER DEFAULT 100,
  job_description_file TEXT,          -- original uploaded filename
  framework_source TEXT DEFAULT 'template',  -- 'template' | 'ai_generated'
  framework_generated_at TIMESTAMP,
  pcr_job_id TEXT,
  pcr_job_title TEXT,
  pcr_company_name TEXT,
  pcr_linked_date TEXT,
  weight_overrides_json TEXT,
  special_requirements_json TEXT,
  notes TEXT,
  created_date TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**`assessments` table:**
```sql
CREATE TABLE assessments (
  id INTEGER PRIMARY KEY,
  candidate_id INTEGER UNIQUE NOT NULL REFERENCES candidates(id),
  requisition_id INTEGER NOT NULL REFERENCES requisitions(id),
  total_score REAL,
  percentage REAL,
  recommendation TEXT,                -- STRONG RECOMMEND, RECOMMEND, CONDITIONAL, DO NOT RECOMMEND
  assessment_mode TEXT DEFAULT 'pending',  -- 'ai' | 'manual' | 'pending'
  ai_model TEXT,                      -- e.g., 'claude-sonnet-4-20250514'
  scores_json TEXT,                   -- full nested score breakdown
  summary TEXT,
  key_strengths_json TEXT,
  areas_of_concern_json TEXT,
  interview_focus_json TEXT,
  assessed_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**`batches` table:**
```sql
CREATE TABLE batches (
  id INTEGER PRIMARY KEY,
  requisition_id INTEGER NOT NULL REFERENCES requisitions(id),
  batch_name TEXT NOT NULL,
  batch_type TEXT DEFAULT 'flat',     -- 'flat' (files in batch root) | 'nested' (originals/ + extracted/)
  candidate_count INTEGER DEFAULT 0,
  manifest_path TEXT,                 -- path to batch_manifest.yaml if exists
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(requisition_id, batch_name)
);
```

- Views: `v_requisition_dashboard` (JOIN clients+requisitions+counts), `v_candidate_search` (JOIN candidates+assessments+requisitions)
- FTS5 virtual table `assessments_fts` for full-text candidate search
- Singleton `get_db()` accessor
- CRUD methods for each entity (get/list/create/update)

**DB location:** `data/raaf.db` (add `data/` to `.gitignore`)

**Files created:**
- `scripts/utils/database.py` - database manager and schema
- `scripts/migrate/__init__.py`
- `scripts/migrate/001_initial_schema.py` - idempotent schema creation script

---

## Phase 2: Backfill Existing Data

**Create `scripts/migrate/backfill_data.py`** that:

1. Iterates `list_clients()` -> reads each `client_info.yaml` -> inserts into `clients` + `client_contacts`
   - Includes `pcr_company_name` field from client config
2. Iterates `list_requisitions()` -> reads each `requisition.yaml` -> inserts into `requisitions`
   - Includes `job.description_file`, PCR integration fields, framework source
   - Checks for `job_description.pdf`/`.docx` existence to populate `job_description_file`
   - Checks for `framework/assessment_framework.md` to determine `framework_source`
3. Iterates all `assessments/individual/*_assessment.json` files -> inserts into `candidates` + `assessments` (parsing the nested JSON)
   - Extracts `assessment_mode` from metadata assessor field (`"Claude/*"` = ai, else manual)
   - Extracts `ai_model` from metadata if present
4. Scans both batch structures for candidates without assessments:
   - `resumes/batches/batch_YYYYMMDD_N/*.txt` (flat) and `resumes/batches/*/extracted/*.txt` (nested)
   - Legacy `resumes/processed/*.txt`
   - Inserts into `candidates` with status='pending'
5. Scans `resumes/batches/` directories -> inserts into `batches` table
   - Detects batch_type ('flat' vs 'nested') based on directory structure
   - Records manifest_path if `batch_manifest.yaml` exists
6. Runs verification: compares DB row counts against file counts for each entity

Supports `--dry-run` (preview only) and `--verify-only` (just count comparison) flags.

**Files created:**
- `scripts/migrate/backfill_data.py`

---

## Phase 3: Add Dual-Write to All Write Paths

Add `RAAF_DB_MODE` env var (`files` | `dual` | `db`, default `files`). Introduce helper `_use_database()` in `client_utils.py`.

When mode is `dual`, every write operation saves to **both** files and DB. This keeps the system fully functional on files while populating the DB.

**Files modified and what changes:**

| File | Changes |
|------|---------|
| `scripts/utils/client_utils.py` | Add `_use_database()` helper. Add DB writes to `save_requisition_config()`. Add new `save_client_info()` that dual-writes. |
| `web/routers/clients.py` | `create_client()` and `update_client()` - add `get_db().create_client()` / update after YAML write |
| `web/routers/requisitions.py` | `create_requisition()` - add DB insert after YAML write (include JD file, framework source). `update_requisition()` - add DB update (include JD file upload). `update_job_description()` - update DB `job_description_file`. `link_pcr_position()` / `unlink_pcr_position()` - update DB PCR fields. `regenerate_framework()` - update DB `framework_source`, `framework_generated_at`. |
| `web/routers/candidates.py` | Resume upload handler - insert into `candidates` table with file path references |
| `web/routers/assessments.py` | `update_assessment()` - add `get_db().save_assessment()` after JSON write (include `assessment_mode`, `ai_model`) |
| `scripts/assess_candidate.py` | After writing `*_assessment.json`, also call `get_db().save_assessment()` with mode and model info |
| `scripts/pcr/sync_candidates.py` | After writing manifest JSON, insert candidates into DB |
| `web/services/framework_generator.py` | After generating framework, update DB `framework_source='ai_generated'`, `framework_generated_at` |

---

## Phase 4: Migrate Reads to Database

Switch read operations to query SQLite instead of scanning files. Done in priority order by performance impact:

### 4a. Dashboard (`web/app.py` dashboard route)
**Before:** Nested loop over all clients/requisitions, loading YAML + globbing files on every page load
**After:** Single query against `v_requisition_dashboard` view

### 4b. Requisition View (`web/routers/requisitions.py` `view_requisition()`)
**Before:** Loads YAML, globs resumes/assessments/reports directories, checks for JD file existence
**After:** `get_db().get_requisition(req_id)` + `get_db().list_candidates(req_id)`. JD availability from `job_description_file IS NOT NULL`.

### 4c. Search (`web/routers/search.py` + `scripts/utils/candidate_search.py`)
**Before:** `load_candidate_repository()` scans every assessment JSON across every client/requisition
**After:** FTS5 query against `assessments_fts` or simple SQL query against `v_candidate_search`

### 4d. Assessment Dashboard (`web/routers/assessments.py`)
**Before:** Globs `*.json`, loads each file
**After:** `SELECT ... FROM assessments JOIN candidates WHERE requisition_id = ?`

### 4e. Client Utils Functions (`scripts/utils/client_utils.py`)
Refactor these functions to check `_use_database()` and query DB when enabled, falling back to file reads otherwise:
- `list_clients()` -> `SELECT client_code FROM clients`
- `get_client_info()` -> `SELECT * FROM clients WHERE client_code = ?` (transform row to match YAML dict shape)
- `list_requisitions()` -> `SELECT req_id FROM requisitions WHERE client_id = ?`
- `get_requisition_config()` -> `SELECT * FROM requisitions WHERE req_id = ?` (transform row to match YAML dict shape)
- `list_all_extracted_resumes()` -> `SELECT resume_path FROM candidates WHERE requisition_id = ?`

### 4f. Node.js Report Generator (`scripts/generate_report.js`)
- Create `scripts/utils/db_adapter.js` using `better-sqlite3` (npm package)
- Add `getAssessmentsForReport(reqId)` function that queries DB
- Modify `generate_report.js` to use DB adapter when available, fall back to JSON files

### 4g. PCR Position Search (`web/routers/pcr.py`)
**Before:** `api_list_positions()` fetches up to 5000 positions via parallel HTTP requests to PCR API every search (~8s)
**After:** Optional position cache table. PCR positions fetched periodically and cached in DB, searches query local cache. Falls back to live API if cache is stale (>1 hour).

---

## Phase 5: Cleanup

1. Set `RAAF_DB_MODE=db` as default
2. Remove YAML/JSON write calls from routers (keep file reads as fallback)
3. Keep all existing YAML/JSON files on disk for archival (don't delete)
4. Add DB backup to maintenance routine: `cp data/raaf.db data/raaf_backup_$(date +%Y%m%d).db`
5. Update CLAUDE.md with new architecture notes

---

## What Stays on Disk (Never Migrated to DB)

- `resumes/batches/*/originals/*.pdf` / `*.docx` - original resume files
- `resumes/batches/*/extracted/*_resume.txt` - extracted text files
- `resumes/processed/*_resume.txt` - legacy extracted text files
- `job_description.pdf` / `job_description.docx` - uploaded job descriptions
- `framework/assessment_framework.md` - framework documents
- `framework/job_description_text.txt` - extracted JD text
- `reports/final/*.docx` / `reports/drafts/*.docx` - generated reports
- `config/settings.yaml` - global settings (loaded once at startup)
- `config/pcr_credentials.yaml` - secrets

These are referenced by file path columns in the database.

---

## Rollback Safety

- **Env var toggle:** Set `RAAF_DB_MODE=files` to instantly revert to file-based reads
- **Files preserved:** Original YAML/JSON files are never deleted during migration
- **Rebuild from files:** Run `backfill_data.py` to recreate DB from files at any time

---

## New Dependencies

- **Python:** None (sqlite3 is in stdlib)
- **Node.js:** `better-sqlite3` (for `generate_report.js`)

---

## Verification

After each phase:
1. Run `python scripts/migrate/backfill_data.py --verify-only` to compare DB vs file counts
2. Load dashboard, verify same data appears
3. Search for a known candidate, verify results match
4. Create a test requisition with JD upload and AI framework generation, verify DB fields populated
5. Run an assessment, verify JSON file and DB record match (including assessment_mode)
6. Upload/replace a job description, verify DB `job_description_file` updated
7. Generate a report, verify it produces identical output

---

## Implementation Order

| Step | Phase | Key Files | Est. Lines Changed |
|------|-------|-----------|-------------------|
| 1 | Database infrastructure | `scripts/utils/database.py` (new, ~450 lines), `scripts/migrate/001_initial_schema.py` (new) | +500 |
| 2 | Backfill script | `scripts/migrate/backfill_data.py` (new, ~300 lines) | +300 |
| 3 | Dual-write | `client_utils.py`, 5 routers, `assess_candidate.py`, `sync_candidates.py`, `framework_generator.py` | ~250 |
| 4 | Migrate reads | `app.py`, 5 routers, `client_utils.py`, `candidate_search.py`, `pcr.py` | ~350 |
| 5 | Node.js adapter | `scripts/utils/db_adapter.js` (new), `generate_report.js` | ~80 |
| 6 | Cleanup | Remove file writes, update docs | ~-100 |
| | **Total** | | **~1,380 net new lines** |

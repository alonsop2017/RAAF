"""
RAAF Database Manager — SQLite backend for structured data.

Replaces file-based YAML/JSON storage for clients, requisitions, candidates,
assessments, batches, and reports. Resume files, PDFs, and DOCX documents
remain on disk; they are referenced via file path columns.

Environment variables:
    RAAF_DB_MODE   — 'db' (default), 'dual', or 'files'
    RAAF_DB_PATH   — override default DB location (data/raaf.db)

Usage:
    from scripts.utils.database import get_db, _use_database

    if _use_database():
        db = get_db()
        db.create_client({...})
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# ---------------------------------------------------------------------------
# DB location
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "raaf.db"

_db_instance: Optional["DatabaseManager"] = None


def get_db(db_path: Optional[Path] = None) -> "DatabaseManager":
    """Return the singleton DatabaseManager, initialising it on first call."""
    global _db_instance
    if _db_instance is None:
        path = db_path or Path(os.environ.get("RAAF_DB_PATH", str(_DEFAULT_DB_PATH)))
        _db_instance = DatabaseManager(path)
        _db_instance.initialize()
    return _db_instance


def reset_db_instance() -> None:
    """Reset singleton — used in tests and migration scripts."""
    global _db_instance
    _db_instance = None


def _use_database() -> bool:
    """Return True when RAAF_DB_MODE is 'dual' or 'db' (default)."""
    return os.environ.get("RAAF_DB_MODE", "db") in ("dual", "db")


def _files_mode() -> bool:
    """Return True when file writes should be performed ('files' or 'dual' mode).

    In the default 'db' mode this returns False — the DB is the source of
    truth and YAML/JSON config files are not updated on write.  Set
    RAAF_DB_MODE=files (or =dual) to re-enable file writes for rollback or
    migration purposes.
    """
    return os.environ.get("RAAF_DB_MODE", "db") in ("files", "dual")


# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------

class DatabaseManager:
    """
    SQLite-backed metadata store for RAAF.

    All write methods are idempotent (INSERT OR REPLACE / ON CONFLICT DO UPDATE).
    The DB uses WAL mode so concurrent reads never block a write.
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Connection management
    # -----------------------------------------------------------------------

    @contextmanager
    def _conn(self):
        """Yield a connection configured for safe concurrent use."""
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Schema initialisation  (idempotent)
    # -----------------------------------------------------------------------

    def initialize(self) -> None:
        """Create all tables, views, and FTS index if they don't exist yet."""
        with self._conn() as conn:
            self._create_tables(conn)
            self._create_views(conn)
            self._create_fts(conn)

    def _create_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                id                      INTEGER PRIMARY KEY,
                client_code             TEXT UNIQUE NOT NULL,
                company_name            TEXT NOT NULL,
                industry                TEXT,
                status                  TEXT DEFAULT 'active',
                pcr_company_name        TEXT,
                default_commission_rate REAL,
                payment_terms           TEXT,
                guarantee_period_days   INTEGER,
                preferences_json        TEXT,
                created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS client_contacts (
                id           INTEGER PRIMARY KEY,
                client_id    INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                contact_type TEXT NOT NULL,
                name         TEXT,
                title        TEXT,
                email        TEXT,
                phone        TEXT
            );

            CREATE TABLE IF NOT EXISTS requisitions (
                id                       INTEGER PRIMARY KEY,
                req_id                   TEXT UNIQUE NOT NULL,
                client_id                INTEGER NOT NULL REFERENCES clients(id),
                job_title                TEXT NOT NULL,
                department               TEXT,
                location                 TEXT,
                salary_min               INTEGER DEFAULT 0,
                salary_max               INTEGER DEFAULT 0,
                salary_currency          TEXT DEFAULT 'CAD',
                commission_rate          REAL,
                status                   TEXT DEFAULT 'active',
                experience_years_min     INTEGER DEFAULT 0,
                education                TEXT,
                threshold_strong         INTEGER DEFAULT 85,
                threshold_recommend      INTEGER DEFAULT 70,
                threshold_conditional    INTEGER DEFAULT 55,
                framework_version        TEXT DEFAULT '1.0',
                max_score                INTEGER DEFAULT 100,
                job_description_file     TEXT,
                framework_source         TEXT DEFAULT 'template',
                framework_generated_at   TIMESTAMP,
                pcr_job_id               TEXT,
                pcr_job_title            TEXT,
                pcr_company_name         TEXT,
                pcr_linked_date          TEXT,
                weight_overrides_json    TEXT,
                special_requirements_json TEXT,
                notes                    TEXT,
                created_date             TEXT,
                created_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS candidates (
                id                    INTEGER PRIMARY KEY,
                requisition_id        INTEGER NOT NULL REFERENCES requisitions(id),
                name                  TEXT NOT NULL,
                name_normalized       TEXT NOT NULL,
                email                 TEXT,
                phone                 TEXT,
                source_platform       TEXT DEFAULT 'Unknown',
                batch                 TEXT,
                resume_original_path  TEXT,
                resume_extracted_path TEXT,
                pcr_candidate_id      TEXT,
                pipeline_status       TEXT,
                status                TEXT DEFAULT 'pending',
                created_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(requisition_id, name_normalized)
            );

            CREATE TABLE IF NOT EXISTS assessments (
                id                  INTEGER PRIMARY KEY,
                candidate_id        INTEGER UNIQUE NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                requisition_id      INTEGER NOT NULL REFERENCES requisitions(id),
                total_score         REAL,
                percentage          REAL,
                recommendation      TEXT,
                assessment_mode     TEXT DEFAULT 'pending',
                ai_model            TEXT,
                scores_json         TEXT,
                summary             TEXT,
                key_strengths_json  TEXT,
                areas_of_concern_json TEXT,
                interview_focus_json  TEXT,
                assessed_at         TIMESTAMP,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS batches (
                id             INTEGER PRIMARY KEY,
                requisition_id INTEGER NOT NULL REFERENCES requisitions(id),
                batch_name     TEXT NOT NULL,
                batch_type     TEXT DEFAULT 'flat',
                candidate_count INTEGER DEFAULT 0,
                manifest_path  TEXT,
                created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(requisition_id, batch_name)
            );

            CREATE TABLE IF NOT EXISTS reports (
                id             INTEGER PRIMARY KEY,
                requisition_id INTEGER NOT NULL REFERENCES requisitions(id),
                filename       TEXT NOT NULL,
                file_path      TEXT NOT NULL,
                report_type    TEXT DEFAULT 'final',
                report_status  TEXT DEFAULT 'generated',
                generated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS pcr_positions_cache (
                job_id    TEXT PRIMARY KEY,
                data_json TEXT NOT NULL,
                cached_at TIMESTAMP NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schema_version (
                version    INTEGER PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            INSERT OR IGNORE INTO schema_version (version) VALUES (1);
        """)

    def _create_views(self, conn: sqlite3.Connection) -> None:
        # Views are DROP + CREATE so they always reflect the latest definition.
        conn.executescript("""
            DROP VIEW IF EXISTS v_requisition_dashboard;
            CREATE VIEW v_requisition_dashboard AS
            SELECT
                c.client_code,
                c.company_name,
                c.industry,
                c.status                                                    AS client_status,
                r.req_id,
                r.job_title,
                r.status                                                    AS req_status,
                r.location,
                r.salary_min,
                r.salary_max,
                r.salary_currency,
                r.created_date,
                r.pcr_job_id,
                COUNT(DISTINCT cand.id)                                     AS candidate_count,
                COUNT(DISTINCT a.id)                                        AS assessed_count,
                COUNT(DISTINCT CASE
                    WHEN a.recommendation IN ('STRONG RECOMMEND', 'RECOMMEND')
                    THEN a.id END)                                          AS recommended_count
            FROM clients c
            JOIN requisitions r   ON r.client_id    = c.id
            LEFT JOIN candidates cand ON cand.requisition_id = r.id
            LEFT JOIN assessments a   ON a.requisition_id    = r.id
                AND a.assessment_mode != 'pending'
            GROUP BY c.id, r.id
            ORDER BY c.company_name, r.created_date DESC;

            DROP VIEW IF EXISTS v_candidate_search;
            CREATE VIEW v_candidate_search AS
            SELECT
                cand.id                 AS candidate_id,
                cand.name,
                cand.name_normalized,
                cand.source_platform,
                cand.batch,
                cand.resume_extracted_path,
                cand.pipeline_status,
                r.req_id,
                r.job_title,
                c.client_code,
                c.company_name,
                a.id                    AS assessment_id,
                a.total_score,
                a.percentage,
                a.recommendation,
                a.summary,
                a.key_strengths_json,
                a.areas_of_concern_json,
                a.interview_focus_json,
                a.scores_json,
                a.assessed_at,
                a.ai_model
            FROM candidates cand
            JOIN requisitions r ON r.id = cand.requisition_id
            JOIN clients c      ON c.id = r.client_id
            LEFT JOIN assessments a ON a.candidate_id = cand.id;
        """)

    def _create_fts(self, conn: sqlite3.Connection) -> None:
        """FTS5 virtual table for fast full-text candidate search."""
        conn.executescript("""
            CREATE VIRTUAL TABLE IF NOT EXISTS assessments_fts
            USING fts5(
                candidate_name,
                req_id,
                job_title,
                client_code,
                summary,
                key_strengths,
                areas_of_concern,
                recommendation,
                content=v_candidate_search,
                content_rowid=candidate_id
            );
        """)

    def rebuild_fts_index(self) -> None:
        """Rebuild the FTS5 index from scratch. Call after bulk inserts."""
        with self._conn() as conn:
            conn.execute("INSERT INTO assessments_fts(assessments_fts) VALUES('rebuild')")

    # -----------------------------------------------------------------------
    # Clients
    # -----------------------------------------------------------------------

    def get_client(self, client_code: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM clients WHERE client_code = ?", (client_code,)
            ).fetchone()
            if not row:
                return None
            client = dict(row)
            if client.get("preferences_json"):
                client["preferences"] = json.loads(client["preferences_json"])
            client["contacts"] = self._get_contacts(conn, client["id"])
            return client

    def list_clients(self, status: Optional[str] = None) -> list:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM clients WHERE status = ? ORDER BY company_name",
                    (status,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM clients ORDER BY company_name"
                ).fetchall()
            return [dict(r) for r in rows]

    def create_client(self, data: dict) -> int:
        with self._conn() as conn:
            preferences = data.get("preferences", {})
            cursor = conn.execute("""
                INSERT OR REPLACE INTO clients
                    (client_code, company_name, industry, status, pcr_company_name,
                     default_commission_rate, payment_terms, guarantee_period_days,
                     preferences_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                data["client_code"],
                data["company_name"],
                data.get("industry"),
                data.get("status", "active"),
                data.get("pcr_company_name"),
                data.get("default_commission_rate"),
                data.get("payment_terms"),
                data.get("guarantee_period_days"),
                json.dumps(preferences) if preferences else None,
            ))
            client_id = cursor.lastrowid
            if "contacts" in data:
                self._upsert_contacts(conn, client_id, data["contacts"])
            return client_id

    def update_client(self, client_code: str, data: dict) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM clients WHERE client_code = ?", (client_code,)
            ).fetchone()
            if not row:
                return False
            client_id = row["id"]
            preferences = data.get("preferences")
            conn.execute("""
                UPDATE clients SET
                    company_name            = COALESCE(?, company_name),
                    industry                = COALESCE(?, industry),
                    status                  = COALESCE(?, status),
                    pcr_company_name        = COALESCE(?, pcr_company_name),
                    default_commission_rate = COALESCE(?, default_commission_rate),
                    payment_terms           = COALESCE(?, payment_terms),
                    guarantee_period_days   = COALESCE(?, guarantee_period_days),
                    preferences_json        = COALESCE(?, preferences_json),
                    updated_at              = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                data.get("company_name"),
                data.get("industry"),
                data.get("status"),
                data.get("pcr_company_name"),
                data.get("default_commission_rate"),
                data.get("payment_terms"),
                data.get("guarantee_period_days"),
                json.dumps(preferences) if preferences else None,
                client_id,
            ))
            if "contacts" in data:
                self._upsert_contacts(conn, client_id, data["contacts"])
            return True

    def _get_contacts(self, conn: sqlite3.Connection, client_id: int) -> dict:
        rows = conn.execute(
            "SELECT * FROM client_contacts WHERE client_id = ?", (client_id,)
        ).fetchall()
        return {r["contact_type"]: dict(r) for r in rows}

    def _upsert_contacts(self, conn: sqlite3.Connection, client_id: int,
                         contacts: dict) -> None:
        conn.execute("DELETE FROM client_contacts WHERE client_id = ?", (client_id,))
        for contact_type, contact_data in contacts.items():
            if not isinstance(contact_data, dict):
                continue
            conn.execute("""
                INSERT INTO client_contacts
                    (client_id, contact_type, name, title, email, phone)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                client_id,
                contact_type,
                contact_data.get("name"),
                contact_data.get("title"),
                contact_data.get("email"),
                contact_data.get("phone"),
            ))

    # -----------------------------------------------------------------------
    # Requisitions
    # -----------------------------------------------------------------------

    def get_requisition(self, req_id: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM requisitions WHERE req_id = ?", (req_id,)
            ).fetchone()
            if not row:
                return None
            req = dict(row)
            for field in ("weight_overrides_json", "special_requirements_json"):
                if req.get(field):
                    req[field.replace("_json", "")] = json.loads(req[field])
            return req

    def list_requisitions(self, client_code: str,
                          status: Optional[str] = None) -> list:
        with self._conn() as conn:
            if status:
                rows = conn.execute("""
                    SELECT r.* FROM requisitions r
                    JOIN clients c ON c.id = r.client_id
                    WHERE c.client_code = ? AND r.status = ?
                    ORDER BY r.created_at DESC
                """, (client_code, status)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT r.* FROM requisitions r
                    JOIN clients c ON c.id = r.client_id
                    WHERE c.client_code = ?
                    ORDER BY r.created_at DESC
                """, (client_code,)).fetchall()
            return [dict(r) for r in rows]

    def create_requisition(self, data: dict) -> int:
        with self._conn() as conn:
            client_row = conn.execute(
                "SELECT id FROM clients WHERE client_code = ?", (data["client_code"],)
            ).fetchone()
            if not client_row:
                raise ValueError(
                    f"Client '{data['client_code']}' not found. "
                    "Create the client record first."
                )
            cursor = conn.execute("""
                INSERT OR REPLACE INTO requisitions (
                    req_id, client_id, job_title, department, location,
                    salary_min, salary_max, salary_currency, commission_rate,
                    status, experience_years_min, education,
                    threshold_strong, threshold_recommend, threshold_conditional,
                    framework_version, max_score,
                    job_description_file, framework_source, framework_generated_at,
                    pcr_job_id, pcr_job_title, pcr_company_name, pcr_linked_date,
                    weight_overrides_json, special_requirements_json,
                    notes, created_date, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP
                )
            """, (
                data["req_id"],
                client_row["id"],
                data["job_title"],
                data.get("department"),
                data.get("location"),
                data.get("salary_min", 0),
                data.get("salary_max", 0),
                data.get("salary_currency", "CAD"),
                data.get("commission_rate"),
                data.get("status", "active"),
                data.get("experience_years_min", 0),
                data.get("education"),
                data.get("threshold_strong", 85),
                data.get("threshold_recommend", 70),
                data.get("threshold_conditional", 55),
                data.get("framework_version", "1.0"),
                data.get("max_score", 100),
                data.get("job_description_file"),
                data.get("framework_source", "template"),
                data.get("framework_generated_at"),
                data.get("pcr_job_id"),
                data.get("pcr_job_title"),
                data.get("pcr_company_name"),
                data.get("pcr_linked_date"),
                json.dumps(data["weight_overrides"])
                    if data.get("weight_overrides") else None,
                json.dumps(data["special_requirements"])
                    if data.get("special_requirements") else None,
                data.get("notes"),
                data.get("created_date",
                          datetime.now().strftime("%Y-%m-%d")),
            ))
            return cursor.lastrowid

    def update_requisition(self, req_id: str, data: dict) -> bool:
        with self._conn() as conn:
            if not conn.execute(
                "SELECT id FROM requisitions WHERE req_id = ?", (req_id,)
            ).fetchone():
                return False

            scalar_fields = {
                "job_title":             "job_title",
                "department":            "department",
                "location":              "location",
                "salary_min":            "salary_min",
                "salary_max":            "salary_max",
                "status":                "status",
                "job_description_file":  "job_description_file",
                "framework_source":      "framework_source",
                "framework_generated_at": "framework_generated_at",
                "pcr_job_id":            "pcr_job_id",
                "pcr_job_title":         "pcr_job_title",
                "pcr_company_name":      "pcr_company_name",
                "pcr_linked_date":       "pcr_linked_date",
                "notes":                 "notes",
                "threshold_strong":      "threshold_strong",
                "threshold_recommend":   "threshold_recommend",
                "threshold_conditional": "threshold_conditional",
            }
            fields, values = [], []
            for key, col in scalar_fields.items():
                if key in data:
                    fields.append(f"{col} = ?")
                    values.append(data[key])
            if "weight_overrides" in data:
                fields.append("weight_overrides_json = ?")
                values.append(
                    json.dumps(data["weight_overrides"])
                    if data["weight_overrides"] else None
                )
            if "special_requirements" in data:
                fields.append("special_requirements_json = ?")
                values.append(
                    json.dumps(data["special_requirements"])
                    if data["special_requirements"] else None
                )
            if not fields:
                return True
            fields.append("updated_at = CURRENT_TIMESTAMP")
            values.append(req_id)
            conn.execute(
                f"UPDATE requisitions SET {', '.join(fields)} WHERE req_id = ?",
                values
            )
            return True

    # -----------------------------------------------------------------------
    # Candidates
    # -----------------------------------------------------------------------

    def get_candidate(self, requisition_id: int,
                      name_normalized: str) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM candidates
                WHERE requisition_id = ? AND name_normalized = ?
            """, (requisition_id, name_normalized)).fetchone()
            return dict(row) if row else None

    def list_candidates(self, req_id: str,
                        status: Optional[str] = None) -> list:
        with self._conn() as conn:
            req_row = conn.execute(
                "SELECT id FROM requisitions WHERE req_id = ?", (req_id,)
            ).fetchone()
            if not req_row:
                return []
            if status:
                rows = conn.execute("""
                    SELECT * FROM candidates
                    WHERE requisition_id = ? AND status = ?
                    ORDER BY name
                """, (req_row["id"], status)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM candidates
                    WHERE requisition_id = ?
                    ORDER BY name
                """, (req_row["id"],)).fetchall()
            return [dict(r) for r in rows]

    def upsert_candidate(self, data: dict) -> int:
        with self._conn() as conn:
            req_row = conn.execute(
                "SELECT id FROM requisitions WHERE req_id = ?", (data["req_id"],)
            ).fetchone()
            if not req_row:
                raise ValueError(f"Requisition '{data['req_id']}' not found.")
            cursor = conn.execute("""
                INSERT INTO candidates
                    (requisition_id, name, name_normalized, email, phone,
                     source_platform, batch, resume_original_path,
                     resume_extracted_path, pcr_candidate_id,
                     pipeline_status, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(requisition_id, name_normalized) DO UPDATE SET
                    name                  = excluded.name,
                    email                 = COALESCE(excluded.email, email),
                    phone                 = COALESCE(excluded.phone, phone),
                    source_platform       = COALESCE(excluded.source_platform,
                                                     source_platform),
                    batch                 = COALESCE(excluded.batch, batch),
                    resume_original_path  = COALESCE(excluded.resume_original_path,
                                                     resume_original_path),
                    resume_extracted_path = COALESCE(excluded.resume_extracted_path,
                                                     resume_extracted_path),
                    pcr_candidate_id      = COALESCE(excluded.pcr_candidate_id,
                                                     pcr_candidate_id),
                    pipeline_status       = COALESCE(excluded.pipeline_status,
                                                     pipeline_status),
                    status                = excluded.status,
                    updated_at            = CURRENT_TIMESTAMP
            """, (
                req_row["id"],
                data["name"],
                data["name_normalized"],
                data.get("email"),
                data.get("phone"),
                data.get("source_platform", "Unknown"),
                data.get("batch"),
                data.get("resume_original_path"),
                data.get("resume_extracted_path"),
                data.get("pcr_candidate_id"),
                data.get("pipeline_status"),
                data.get("status", "pending"),
            ))
            return cursor.lastrowid

    def update_candidate_pipeline(self, candidate_id: int,
                                  pipeline_status: str) -> bool:
        with self._conn() as conn:
            conn.execute("""
                UPDATE candidates
                SET pipeline_status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (pipeline_status, candidate_id))
            return True

    # -----------------------------------------------------------------------
    # Assessments
    # -----------------------------------------------------------------------

    def get_assessment(self, candidate_id: int) -> Optional[dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM assessments WHERE candidate_id = ?",
                (candidate_id,)
            ).fetchone()
            if not row:
                return None
            return self._deserialise_assessment(dict(row))

    def list_assessments(self, req_id: str) -> list:
        """Return all assessments for a requisition, ranked by score descending."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT
                    a.*,
                    cand.name,
                    cand.name_normalized,
                    cand.batch,
                    cand.source_platform,
                    cand.pipeline_status
                FROM assessments a
                JOIN candidates cand ON cand.id    = a.candidate_id
                JOIN requisitions r  ON r.id       = a.requisition_id
                WHERE r.req_id = ?
                ORDER BY a.percentage DESC
            """, (req_id,)).fetchall()
            return [self._deserialise_assessment(dict(r)) for r in rows]

    def save_assessment(self, data: dict) -> int:
        """Insert or update an assessment record. Creates candidate row if absent."""
        with self._conn() as conn:
            req_row = conn.execute(
                "SELECT id FROM requisitions WHERE req_id = ?", (data["req_id"],)
            ).fetchone()
            if not req_row:
                raise ValueError(f"Requisition '{data['req_id']}' not found.")
            req_id_int = req_row["id"]

            # Ensure the candidate row exists
            cand_row = conn.execute("""
                SELECT id FROM candidates
                WHERE requisition_id = ? AND name_normalized = ?
            """, (req_id_int, data["name_normalized"])).fetchone()

            if not cand_row:
                conn.execute("""
                    INSERT INTO candidates
                        (requisition_id, name, name_normalized, source_platform,
                         batch, resume_extracted_path, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'assessed')
                """, (
                    req_id_int,
                    data.get("name",
                              data["name_normalized"].replace("_", " ").title()),
                    data["name_normalized"],
                    data.get("source_platform", "Unknown"),
                    data.get("batch"),
                    data.get("resume_extracted_path"),
                ))
                cand_id = conn.execute(
                    "SELECT last_insert_rowid()"
                ).fetchone()[0]
            else:
                cand_id = cand_row["id"]
                conn.execute("""
                    UPDATE candidates
                    SET status = 'assessed', updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (cand_id,))

            cursor = conn.execute("""
                INSERT INTO assessments
                    (candidate_id, requisition_id, total_score, percentage,
                     recommendation, assessment_mode, ai_model,
                     scores_json, summary, key_strengths_json,
                     areas_of_concern_json, interview_focus_json,
                     assessed_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        CURRENT_TIMESTAMP)
                ON CONFLICT(candidate_id) DO UPDATE SET
                    total_score           = excluded.total_score,
                    percentage            = excluded.percentage,
                    recommendation        = excluded.recommendation,
                    assessment_mode       = excluded.assessment_mode,
                    ai_model              = COALESCE(excluded.ai_model, ai_model),
                    scores_json           = excluded.scores_json,
                    summary               = excluded.summary,
                    key_strengths_json    = excluded.key_strengths_json,
                    areas_of_concern_json = excluded.areas_of_concern_json,
                    interview_focus_json  = excluded.interview_focus_json,
                    assessed_at           = excluded.assessed_at,
                    updated_at            = CURRENT_TIMESTAMP
            """, (
                cand_id,
                req_id_int,
                data.get("total_score"),
                data.get("percentage"),
                data.get("recommendation"),
                data.get("assessment_mode", "ai"),
                data.get("ai_model"),
                json.dumps(data["scores"])
                    if data.get("scores") else None,
                data.get("summary"),
                json.dumps(data["key_strengths"])
                    if data.get("key_strengths") else None,
                json.dumps(data["areas_of_concern"])
                    if data.get("areas_of_concern") else None,
                json.dumps(data["interview_focus_areas"])
                    if data.get("interview_focus_areas") else None,
                data.get("assessed_at",
                          datetime.utcnow().isoformat()),
            ))
            return cursor.lastrowid

    @staticmethod
    def _deserialise_assessment(a: dict) -> dict:
        """Expand JSON text columns back to Python objects."""
        for field in ("scores_json", "key_strengths_json",
                      "areas_of_concern_json", "interview_focus_json"):
            if a.get(field):
                a[field.replace("_json", "")] = json.loads(a[field])
        return a

    # -----------------------------------------------------------------------
    # Batches
    # -----------------------------------------------------------------------

    def list_batches(self, req_id: str) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT b.* FROM batches b
                JOIN requisitions r ON r.id = b.requisition_id
                WHERE r.req_id = ?
                ORDER BY b.batch_name
            """, (req_id,)).fetchall()
            return [dict(r) for r in rows]

    def upsert_batch(self, req_id: str, batch_name: str,
                     batch_type: str = "flat", candidate_count: int = 0,
                     manifest_path: Optional[str] = None) -> int:
        with self._conn() as conn:
            req_row = conn.execute(
                "SELECT id FROM requisitions WHERE req_id = ?", (req_id,)
            ).fetchone()
            if not req_row:
                raise ValueError(f"Requisition '{req_id}' not found.")
            cursor = conn.execute("""
                INSERT INTO batches
                    (requisition_id, batch_name, batch_type,
                     candidate_count, manifest_path)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(requisition_id, batch_name) DO UPDATE SET
                    candidate_count = excluded.candidate_count,
                    manifest_path   = COALESCE(excluded.manifest_path,
                                               manifest_path)
            """, (req_row["id"], batch_name, batch_type,
                  candidate_count, manifest_path))
            return cursor.lastrowid

    # -----------------------------------------------------------------------
    # Reports
    # -----------------------------------------------------------------------

    def save_report(self, req_id: str, filename: str, file_path: str,
                    report_type: str = "final") -> int:
        with self._conn() as conn:
            req_row = conn.execute(
                "SELECT id FROM requisitions WHERE req_id = ?", (req_id,)
            ).fetchone()
            if not req_row:
                raise ValueError(f"Requisition '{req_id}' not found.")
            cursor = conn.execute("""
                INSERT INTO reports
                    (requisition_id, filename, file_path, report_type)
                VALUES (?, ?, ?, ?)
            """, (req_row["id"], filename, file_path, report_type))
            return cursor.lastrowid

    def list_reports(self, req_id: str) -> list:
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT rpt.* FROM reports rpt
                JOIN requisitions r ON r.id = rpt.requisition_id
                WHERE r.req_id = ?
                ORDER BY rpt.generated_at DESC
            """, (req_id,)).fetchall()
            return [dict(r) for r in rows]

    # -----------------------------------------------------------------------
    # Dashboard
    # -----------------------------------------------------------------------

    def get_dashboard_data(self) -> list:
        """
        Single query replaces the nested client/requisition file loop in app.py.
        Returns one row per requisition with candidate and assessment counts.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM v_requisition_dashboard"
            ).fetchall()
            return [dict(r) for r in rows]

    # -----------------------------------------------------------------------
    # Search
    # -----------------------------------------------------------------------

    def search_candidates_fts(self, query: str, limit: int = 50) -> list:
        """Full-text search via FTS5 index. Returns ranked results."""
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT v.*, rank
                FROM assessments_fts
                JOIN v_candidate_search v
                     ON v.candidate_id = assessments_fts.rowid
                WHERE assessments_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit)).fetchall()
            return [dict(r) for r in rows]

    def search_candidates_sql(self, query: str, limit: int = 50) -> list:
        """Fallback keyword search using SQL LIKE across key text fields."""
        like = f"%{query}%"
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT * FROM v_candidate_search
                WHERE  name               LIKE ?
                   OR  summary            LIKE ?
                   OR  key_strengths_json LIKE ?
                   OR  job_title          LIKE ?
                   OR  recommendation     LIKE ?
                ORDER BY percentage DESC
                LIMIT ?
            """, (like, like, like, like, like, limit)).fetchall()
            return [dict(r) for r in rows]

    # -----------------------------------------------------------------------
    # Repository stats
    # -----------------------------------------------------------------------

    def get_repository_stats(self) -> dict:
        """
        Aggregate stats across all clients.
        Replaces the file-scanning get_repository_stats() in candidate_search.py.
        """
        with self._conn() as conn:
            total = conn.execute("""
                SELECT COUNT(*) FROM assessments WHERE assessment_mode != 'pending'
            """).fetchone()[0]

            by_rec = conn.execute("""
                SELECT recommendation, COUNT(*) AS count
                FROM assessments
                WHERE assessment_mode != 'pending'
                GROUP BY recommendation
            """).fetchall()

            avg_row = conn.execute("""
                SELECT AVG(percentage) FROM assessments
                WHERE assessment_mode != 'pending'
            """).fetchone()

            return {
                "total_candidates": total,
                "by_recommendation": {
                    r["recommendation"]: r["count"] for r in by_rec
                },
                "avg_score": round(avg_row[0] or 0.0, 1),
            }

    # -----------------------------------------------------------------------
    # PCR positions cache
    # -----------------------------------------------------------------------

    def cache_pcr_positions(self, positions: list) -> None:
        """Replace the PCR positions cache with a fresh snapshot."""
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute("DELETE FROM pcr_positions_cache")
            conn.executemany(
                "INSERT INTO pcr_positions_cache (job_id, data_json, cached_at) VALUES (?, ?, ?)",
                [
                    (str(pos.get("JobId", "")), json.dumps(pos, default=str), now)
                    for pos in positions
                    if pos.get("JobId")
                ],
            )

    def get_cached_pcr_positions(self, max_age_seconds: int = 3600) -> Optional[list]:
        """Return cached raw PCR positions if the cache is fresh, else None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MAX(cached_at) FROM pcr_positions_cache"
            ).fetchone()
            if not row or not row[0]:
                return None
            cached_at = datetime.fromisoformat(row[0])
            age = (datetime.utcnow() - cached_at).total_seconds()
            if age > max_age_seconds:
                return None
            rows = conn.execute(
                "SELECT data_json FROM pcr_positions_cache"
            ).fetchall()
            return [json.loads(r[0]) for r in rows]

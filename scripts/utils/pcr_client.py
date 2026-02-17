#!/usr/bin/env python3
"""
PCRecruiter API client wrapper.
Handles authentication, session management, and API calls to PCR.

API Documentation: https://www.pcrecruiter.net/apidocs_v2/
"""

import html
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    requests = None

import yaml

import sys
sys.path.insert(0, str(Path(__file__).parent))
from client_utils import get_config_path, get_settings


class PCRClientError(Exception):
    """Base exception for PCR client errors."""
    pass


class PCRAuthenticationError(PCRClientError):
    """Authentication failed."""
    pass


class PCRAPIError(PCRClientError):
    """API call failed."""
    def __init__(self, message: str, status_code: int = None, response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class PCRClient:
    """
    PCRecruiter API client.

    Usage:
        client = PCRClient()
        client.authenticate()
        positions = client.get_positions(status="Open")
    """

    def __init__(self, credentials_path: Optional[Path] = None):
        """
        Initialize the PCR client.

        Args:
            credentials_path: Path to credentials YAML file.
                            Defaults to config/pcr_credentials.yaml
        """
        if requests is None:
            raise ImportError("requests library is required. Run: pip install requests")

        self.credentials_path = credentials_path or (get_config_path() / "pcr_credentials.yaml")
        self.credentials = self._load_credentials()
        self.settings = get_settings().get("pcr", {})

        self.base_url = self.settings.get("api_base_url", "https://www2.pcrecruiter.net/rest/api")
        self.session_token = None
        self.session_expires = None

        # Load existing session if available
        self._load_session()

    def _load_credentials(self) -> dict:
        """Load credentials from YAML file."""
        if not self.credentials_path.exists():
            raise FileNotFoundError(
                f"PCR credentials not found: {self.credentials_path}\n"
                "Copy pcr_credentials_template.yaml and fill in your credentials."
            )

        with open(self.credentials_path, "r") as f:
            creds = yaml.safe_load(f)

        # Validate required fields
        required = ["database.database_id", "database.username", "database.password", "api.api_key"]
        for field in required:
            parts = field.split(".")
            value = creds
            for part in parts:
                value = value.get(part, {}) if isinstance(value, dict) else None
            if not value or value.startswith("YOUR_"):
                raise ValueError(f"Missing or invalid credential: {field}")

        return creds

    def _load_session(self) -> None:
        """Load existing session token if valid."""
        session = self.credentials.get("session", {})
        token = session.get("token")
        expires = session.get("expires_at")

        if token and expires:
            try:
                expires_dt = datetime.fromisoformat(expires)
                if expires_dt > datetime.now():
                    self.session_token = token
                    self.session_expires = expires_dt
            except (ValueError, TypeError):
                pass

    def _save_session(self) -> None:
        """Save session token to credentials file."""
        self.credentials["session"] = {
            "token": self.session_token,
            "expires_at": self.session_expires.isoformat() if self.session_expires else ""
        }
        with open(self.credentials_path, "w") as f:
            yaml.dump(self.credentials, f, default_flow_style=False)

    def _get_headers(self, include_auth: bool = True) -> dict:
        """Get request headers."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Api-Key": self.credentials["api"]["api_key"]
        }
        if include_auth and self.session_token:
            headers["Authorization"] = f"BEARER {self.session_token}"
        return headers

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        include_auth: bool = True
    ) -> dict:
        """
        Make an API request.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (relative to base URL)
            params: Query parameters
            data: Request body data
            include_auth: Whether to include auth header

        Returns:
            Response JSON as dictionary
        """
        url = urljoin(self.base_url + "/", endpoint.lstrip("/"))
        headers = self._get_headers(include_auth)

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=data,
                timeout=30
            )

            if response.status_code == 401:
                raise PCRAuthenticationError("Authentication failed or session expired")

            if response.status_code >= 400:
                error_msg = f"API error: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg = error_data.get("message", error_msg)
                except Exception:
                    error_msg = response.text or error_msg
                raise PCRAPIError(error_msg, response.status_code, response.json() if response.text else None)

            if response.text:
                return response.json()
            return {}

        except requests.RequestException as e:
            raise PCRClientError(f"Request failed: {e}")

    def authenticate(self, force: bool = False) -> str:
        """
        Authenticate with PCR and get a session token.

        Args:
            force: Force re-authentication even if session is valid

        Returns:
            Session token
        """
        # Check if existing session is still valid
        if not force and self.session_token and self.session_expires:
            if self.session_expires > datetime.now() + timedelta(minutes=5):
                return self.session_token

        db = self.credentials["database"]
        api_key = self.credentials["api"]["api_key"]
        auth_params = {
            "DatabaseId": db["database_id"],
            "Username": db["username"],
            "Password": db["password"],
            "ApiKey": api_key,
            "AppId": api_key
        }

        response = self._make_request(
            "GET",
            "/access-token",
            params=auth_params,
            include_auth=False
        )

        self.session_token = response.get("SessionId")
        if not self.session_token:
            raise PCRAuthenticationError("No session token in response")

        # Set expiration (default 60 minutes)
        timeout = self.settings.get("session_timeout_minutes", 60)
        self.session_expires = datetime.now() + timedelta(minutes=timeout)

        self._save_session()
        return self.session_token

    def ensure_authenticated(self) -> None:
        """Ensure we have a valid session, authenticating if needed."""
        if not self.session_token or not self.session_expires:
            self.authenticate()
        elif self.session_expires <= datetime.now() + timedelta(minutes=5):
            self.authenticate(force=True)

    def refresh_token(self) -> str:
        """Refresh the session token."""
        return self.authenticate(force=True)

    # ========== Position/Job Methods ==========

    def get_positions(
        self,
        status: Optional[str] = None,
        company_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[dict]:
        """
        Get positions/jobs from PCR.

        Args:
            status: Filter by status (Open, Closed, etc.)
            company_id: Filter by company ID
            limit: Maximum results to return
            offset: Results offset for pagination

        Returns:
            List of position records
        """
        self.ensure_authenticated()

        params = {
            "ResultsPerPage": limit,
            "Page": (offset // limit) + 1
        }
        if status:
            params["Status"] = status
        if company_id:
            params["CompanyId"] = company_id

        response = self._make_request("GET", "/positions", params=params)
        return response.get("Results", [])

    def get_position(self, position_id: str) -> dict:
        """Get a single position by ID."""
        self.ensure_authenticated()
        return self._make_request("GET", f"/positions/{position_id}")

    def get_position_candidates(
        self,
        position_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> list[dict]:
        """Get candidates in a position's pipeline.

        Uses position activities (INQUIRY type) to find applicants,
        then fetches PipelineInterviews to get CandidateId for each.
        The /positions/{id}/candidates endpoint does not exist in PCR API v2.
        """
        self.ensure_authenticated()

        # Step 1: Get all INQUIRY activities for this position
        response = self._make_request(
            "GET",
            f"/positions/{position_id}/activities",
            params={"ResultsPerPage": 500}
        )
        activities = response.get("Results", [])
        inquiry_ids = [
            a["ActivityId"] for a in activities
            if a.get("ActivityType") == "INQUIRY"
        ]

        if not inquiry_ids:
            return []

        # Step 2: For each activity, get the PipelineInterview to obtain CandidateId
        candidates = []
        seen_candidate_ids = set()
        for act_id in inquiry_ids:
            try:
                pi = self._make_request("GET", f"/PipelineInterviews/{act_id}")
                cid = pi.get("CandidateId")
                if cid and cid not in seen_candidate_ids:
                    seen_candidate_ids.add(cid)
                    # PCR returns HTML-encoded names with double-encoded UTF-8;
                    # decode HTML entities, then fix the mojibake
                    raw_name = html.unescape(pi.get("CandidateName", "") or "")
                    try:
                        raw_name = raw_name.encode("latin-1").decode("utf-8")
                    except (UnicodeDecodeError, UnicodeEncodeError):
                        pass
                    parts = raw_name.split(None, 1)
                    candidates.append({
                        "CandidateId": cid,
                        "FirstName": parts[0] if parts else "",
                        "LastName": parts[1] if len(parts) > 1 else "",
                        "CandidateName": raw_name,
                        "DateAdded": pi.get("AppointmentDate", ""),
                        "PipelineStatus": pi.get("InterviewStatus", ""),
                        "SendoutId": pi.get("SendoutId"),
                        "JobId": pi.get("JobId"),
                    })
            except PCRClientError:
                continue

        return candidates

    # ========== Candidate Methods ==========

    def get_candidate(self, candidate_id: str) -> dict:
        """Get a single candidate by ID."""
        self.ensure_authenticated()
        return self._make_request("GET", f"/candidates/{candidate_id}")

    def search_candidates(
        self,
        query: Optional[str] = None,
        email: Optional[str] = None,
        name: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[dict]:
        """
        Search for candidates.

        Args:
            query: General search query
            email: Search by email
            name: Search by name
            limit: Maximum results
            offset: Results offset

        Returns:
            List of matching candidates
        """
        self.ensure_authenticated()

        params = {
            "ResultsPerPage": limit,
            "Page": (offset // limit) + 1
        }
        if query:
            params["Query"] = query
        if email:
            params["Email"] = email
        if name:
            params["Name"] = name

        response = self._make_request("GET", "/candidates", params=params)
        return response.get("Results", [])

    def update_candidate(self, candidate_id: str, data: dict) -> dict:
        """Update a candidate record."""
        self.ensure_authenticated()
        return self._make_request("PUT", f"/candidates/{candidate_id}", data=data)

    def add_candidate_note(self, candidate_id: str, note: str, note_type: str = "General") -> dict:
        """Add a note to a candidate record."""
        self.ensure_authenticated()
        data = {
            "NoteType": note_type,
            "NoteText": note
        }
        return self._make_request("POST", f"/candidates/{candidate_id}/notes", data=data)

    # ========== Resume/Document Methods ==========

    def get_candidate_documents(self, candidate_id: str) -> list[dict]:
        """Get list of attachments for a candidate.

        PCR API v2 uses /candidates/{id}/attachments (not /documents).
        Maps attachment fields to the document field names used by callers.
        """
        self.ensure_authenticated()
        response = self._make_request("GET", f"/candidates/{candidate_id}/attachments")
        results = response.get("Results", [])
        # Map attachment fields to expected document field names
        return [
            {
                "DocumentId": att.get("AttachmentId"),
                "FileName": att.get("Name", ""),
                "DocumentType": att.get("Description", ""),
                "Size": att.get("Size", 0),
                "Date": att.get("Date", ""),
            }
            for att in results
        ]

    def download_document(self, candidate_id: str, document_id: str) -> bytes:
        """
        Download an attachment file.

        Fetches /candidates/{id}/attachments/{id} which returns JSON
        with base64-encoded Data field.

        Returns:
            Document content as bytes
        """
        import base64
        self.ensure_authenticated()
        response = self._make_request(
            "GET", f"/candidates/{candidate_id}/attachments/{document_id}"
        )
        data_b64 = response.get("Data", "")
        if not data_b64:
            raise PCRAPIError(f"No data in attachment {document_id}")
        return base64.b64decode(data_b64)

    # ========== Pipeline Methods ==========

    def update_pipeline_interview(
        self,
        sendout_id: str,
        status: str = None,
        notes: str = None
    ) -> dict:
        """
        Update a PipelineInterview record (candidate's pipeline entry).

        Args:
            sendout_id: The SendoutId / activity ID of the pipeline entry
            status: New InterviewStatus value (e.g., "Resume Reviewed", "Assessed")
            notes: Optional notes to append
        """
        self.ensure_authenticated()

        data = {}
        if status:
            data["InterviewStatus"] = status
        if notes:
            data["Notes"] = notes

        return self._make_request("PUT", f"/PipelineInterviews/{sendout_id}", data=data)

    # ========== Company Methods ==========

    def get_company(self, company_id: str) -> dict:
        """Get a company by ID."""
        self.ensure_authenticated()
        return self._make_request("GET", f"/companies/{company_id}")

    def get_company_positions(self, company_id: str) -> list[dict]:
        """Get all positions for a company."""
        return self.get_positions(company_id=company_id)

    # ========== Custom Fields ==========

    def update_candidate_custom_field(
        self,
        candidate_id: str,
        field_name: str,
        value: Any
    ) -> dict:
        """Update a custom field on a candidate record."""
        self.ensure_authenticated()
        data = {field_name: value}
        return self._make_request("PUT", f"/candidates/{candidate_id}", data=data)

    def set_assessment_score(
        self,
        candidate_id: str,
        score: float,
        recommendation: str,
        field_name: str = "AssessmentScore"
    ) -> dict:
        """
        Set assessment score on a candidate record.

        Args:
            candidate_id: Candidate ID
            score: Assessment score (0-100)
            recommendation: Recommendation text
            field_name: Custom field name for score
        """
        self.ensure_authenticated()
        data = {
            field_name: score,
            f"{field_name}Recommendation": recommendation
        }
        return self._make_request("PUT", f"/candidates/{candidate_id}", data=data)


def test_connection() -> bool:
    """Test PCR API connection and authentication."""
    try:
        client = PCRClient()
        client.authenticate()
        print("Successfully connected to PCRecruiter API")
        print(f"Session token: {client.session_token[:20]}...")
        print(f"Expires: {client.session_expires}")
        return True
    except Exception as e:
        print(f"Connection failed: {e}")
        return False


if __name__ == "__main__":
    test_connection()

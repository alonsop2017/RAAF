"""Shared state for backup quiesce. Imported by app.py middleware and admin router."""
backup_in_progress: bool = False

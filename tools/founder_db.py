"""
tools/founder_db.py

Clean interface for reading, writing, and versioning founder profiles.
Every agent and route should use this instead of raw json.load() calls.

Features:
  - Load a single founder or all founders
  - Save and update founder profiles with automatic versioning
  - Track profile change history
  - Validate required fields on write
  - List all available founder slugs

Usage:
    from tools.founder_db import FounderDB

    db = FounderDB()

    # Load one founder
    founder = db.get("claravision")

    # Load all founders
    all_founders = db.get_all()

    # Update a field
    db.update("claravision", {"deployment_target": "hybrid cloud"})

    # Check change history
    changes = db.get_changes("claravision")

    # List all slugs
    slugs = db.list_slugs()
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

FOUNDERS_DIR = Path("founders")
OUTPUTS_DIR  = Path("outputs")

REQUIRED_FIELDS = [
    "founder_name",
    "company",
    "domain",
    "primary_challenge",
    "deployment_target",
    "twelve_month_goal",
]


# ── FounderDB ─────────────────────────────────────────────────────────────────

class FounderDB:
    """
    Read/write interface for founder JSON profiles.
    All file I/O goes through this class.
    """

    def __init__(
        self,
        founders_dir: Path = FOUNDERS_DIR,
        outputs_dir: Path = OUTPUTS_DIR,
    ):
        self.founders_dir = Path(founders_dir)
        self.outputs_dir  = Path(outputs_dir)
        self.outputs_dir.mkdir(exist_ok=True)

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, slug: str) -> dict:
        """
        Load a single founder profile by slug.
        Raises FileNotFoundError if the profile doesn't exist.
        Raises ValueError if the JSON is malformed or empty.
        """
        path = self._path(slug)
        if not path.exists():
            raise FileNotFoundError(
                f"Founder profile not found: {path}\n"
                f"Available slugs: {', '.join(self.list_slugs())}"
            )
        try:
            content = path.read_text().strip()
            if not content:
                raise ValueError(f"Founder file is empty: {path}")
            data = json.loads(content)
            data["_slug"] = slug   # Attach slug for convenience
            return data
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in {path}: {e}") from e

    def get_all(self) -> list[dict]:
        """
        Load all founder profiles. Skips broken files with a warning.
        Returns a list sorted by company name.
        """
        founders = []
        for path in sorted(self.founders_dir.glob("*.json")):
            slug = path.stem
            try:
                founder = self.get(slug)
                founders.append(founder)
            except (ValueError, json.JSONDecodeError) as e:
                print(f"[FounderDB] WARNING: Skipping {slug} — {e}")
        return founders

    def get_summary(self, slug: str) -> dict:
        """
        Returns a lightweight summary dict for portfolio views.
        Does not include full profile fields.
        """
        f = self.get(slug)
        return {
            "slug":              slug,
            "name":              f.get("founder_name"),
            "company":           f.get("company"),
            "domain":            f.get("domain"),
            "funding_stage":     f.get("funding_stage"),
            "primary_challenge": (f.get("primary_challenge") or "")[:100],
            "compliance":        f.get("compliance_requirements", []),
            "nvidia_tools":      f.get("nvidia_tools", []),
        }

    def get_all_summaries(self) -> list[dict]:
        """Returns lightweight summaries for all founders."""
        return [self.get_summary(slug) for slug in self.list_slugs()]

    def list_slugs(self) -> list[str]:
        """Returns all available founder slugs (filenames without .json)."""
        return sorted([p.stem for p in self.founders_dir.glob("*.json")])

    def exists(self, slug: str) -> bool:
        return self._path(slug).exists()

    # ── Write ─────────────────────────────────────────────────────────────────

    def save(self, slug: str, data: dict, validate: bool = True) -> dict:
        """
        Save a founder profile. Creates the file if it doesn't exist.
        Validates required fields by default.
        Returns the saved data.
        """
        if validate:
            self._validate(slug, data)

        # Strip internal keys before saving
        clean = {k: v for k, v in data.items() if not k.startswith("_")}

        path = self._path(slug)
        path.write_text(json.dumps(clean, indent=2))
        return clean

    def update(self, slug: str, updates: dict) -> dict:
        """
        Update specific fields on an existing founder profile.
        Automatically logs the change to the change history.
        Returns the full updated profile.
        """
        current = self.get(slug)

        # Log changes before applying
        changed_fields = []
        for key, new_val in updates.items():
            old_val = current.get(key)
            if old_val != new_val:
                changed_fields.append({
                    "field":     key,
                    "old_value": old_val,
                    "new_value": new_val,
                    "timestamp": datetime.now().isoformat(),
                })

        # Apply updates
        current.update(updates)
        self.save(slug, current)

        # Persist change log
        if changed_fields:
            self._append_changes(slug, changed_fields)

        return current

    # ── Change history ────────────────────────────────────────────────────────

    def get_changes(self, slug: str) -> list[dict]:
        """
        Returns the change history for a founder profile.
        Each entry has: field, old_value, new_value, timestamp.
        """
        path = self._changes_path(slug)
        if not path.exists():
            return []
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, ValueError):
            return []

    def get_latest_change(self, slug: str) -> Optional[dict]:
        """Returns the most recent change, or None if no changes."""
        changes = self.get_changes(slug)
        return changes[-1] if changes else None

    def has_changes_since(self, slug: str, since_iso: str) -> bool:
        """Returns True if any profile changes were made after the given ISO timestamp."""
        changes = self.get_changes(slug)
        for change in changes:
            if change.get("timestamp", "") > since_iso:
                return True
        return False

    # ── Output tracking ───────────────────────────────────────────────────────

    def get_outputs(self, slug: str) -> list[dict]:
        """
        Returns a list of generated output files for a founder.
        Each entry has: filename, doc_type, timestamp, content.
        """
        files = []
        for path in sorted(self.outputs_dir.glob(f"{slug}_*.md"), reverse=True):
            parts = path.stem.split("_")
            doc_type = "vision_brief" if "vision_brief" in path.stem else "roadmap"
            files.append({
                "filename": path.name,
                "doc_type":  doc_type,
                "timestamp": "_".join(parts[-2:]) if len(parts) >= 2 else "",
                "content":   path.read_text(),
            })
        return files

    def save_output(self, slug: str, doc_type: str, content: str) -> str:
        """
        Save a generated document to the outputs directory.
        Returns the file path.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.outputs_dir / f"{slug}_{doc_type}_{timestamp}.md"
        path.write_text(content)
        return str(path)

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate(self, slug: str, data: dict) -> None:
        missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
        if missing:
            raise ValueError(
                f"Founder profile '{slug}' is missing required fields: {', '.join(missing)}"
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _path(self, slug: str) -> Path:
        return self.founders_dir / f"{slug}.json"

    def _changes_path(self, slug: str) -> Path:
        return self.outputs_dir / f"{slug}_profile_changes.json"

    def _append_changes(self, slug: str, new_changes: list[dict]) -> None:
        existing = self.get_changes(slug)
        existing.extend(new_changes)
        self._changes_path(slug).write_text(json.dumps(existing, indent=2))


# ── Module-level singleton ────────────────────────────────────────────────────

db = FounderDB()
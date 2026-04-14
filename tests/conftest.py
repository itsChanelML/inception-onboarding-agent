"""
tests/conftest.py

Shared pytest fixtures and configuration.
"""

import pytest
from pathlib import Path


# ── Ensure outputs dir exists for tests ──────────────────────────────────────

@pytest.fixture(autouse=True)
def ensure_dirs(tmp_path, monkeypatch):
    """
    Redirect file writes to tmp_path during tests so tests never
    touch the real outputs/ or founders/ directories.
    """
    # Create temp dirs
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "journeys").mkdir()
    (tmp_path / "founders").mkdir()
    (tmp_path / "data").mkdir()
    return tmp_path


# ── Sample founder dict ───────────────────────────────────────────────────────

@pytest.fixture
def sample_founder():
    return {
        "founder_name": "Dr. Maya Chen",
        "company": "ClaraVision",
        "domain": "medical imaging",
        "primary_challenge": "HIPAA-compliant on-premise deployment",
        "deployment_target": "on-premise",
        "twelve_month_goal": "First signed hospital partnership",
        "nvidia_tools": ["NIM", "Clara", "MONAI", "FLARE"],
        "compliance_requirements": ["HIPAA"],
        "funding_stage": "Seed",
        "current_stack": ["PyTorch", "MONAI"],
        "team_size": "3 people",
    }


@pytest.fixture
def sample_founder_edge():
    return {
        "founder_name": "Ravi Krishnamurthy",
        "company": "NovaCrop AI",
        "domain": "precision agriculture",
        "primary_challenge": "Sub-100ms edge inference on Jetson",
        "deployment_target": "edge",
        "twelve_month_goal": "200-farm network, Series A",
        "nvidia_tools": ["Jetson Orin", "TAO Toolkit", "NIM"],
        "compliance_requirements": [],
        "funding_stage": "Pre-seed",
        "current_stack": ["PyTorch"],
        "team_size": "4 people",
    }
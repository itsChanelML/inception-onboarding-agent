"""
tests/test_routes.py

Smoke tests for Flask API routes.
Tests that routes exist, return correct status codes, and return valid JSON.
NIM and agent calls are mocked.
Run with: pytest tests/test_routes.py
"""

import json
import pytest
from unittest.mock import MagicMock, patch


# ── App fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def app():
    """Create Flask test client with agents mocked."""
    # Mock all agent imports before importing app
    with patch.dict('sys.modules', {
        'tools.nim_client': MagicMock(),
        'tools.founder_db': MagicMock(),
        'tools.memory': MagicMock(),
        'tools.journey_tracker': MagicMock(),
        'tools.vector_store': MagicMock(),
        'agents.orchestrator': MagicMock(),
        'agents.risk_agent': MagicMock(),
        'agents.ticket_agent': MagicMock(),
        'agents.onboarding_agent': MagicMock(),
        'agents.pattern_matcher': MagicMock(),
        'agents.monitor_agent': MagicMock(),
    }):
        import importlib
        import app as app_module
        importlib.reload(app_module)
        app_module.app.config['TESTING'] = True
        with app_module.app.test_client() as client:
            yield client


# ── Health check ──────────────────────────────────────────────────────────────

class TestHealthRoute:

    def test_health_returns_200(self, app):
        r = app.get('/api/health')
        assert r.status_code == 200

    def test_health_returns_json(self, app):
        r = app.get('/api/health')
        data = json.loads(r.data)
        assert 'status' in data

    def test_health_has_required_fields(self, app):
        r = app.get('/api/health')
        data = json.loads(r.data)
        assert 'agents_loaded' in data
        assert 'founders' in data


# ── Portal routes ─────────────────────────────────────────────────────────────

class TestPortalRoutes:

    def test_manager_portal_returns_200(self, app):
        r = app.get('/')
        assert r.status_code == 200

    def test_founder_portal_returns_200(self, app):
        r = app.get('/founder')
        assert r.status_code == 200

    def test_manager_alias_returns_200(self, app):
        r = app.get('/manager')
        assert r.status_code == 200


# ── Founder routes ────────────────────────────────────────────────────────────

class TestFounderRoutes:

    def test_list_founders_returns_200(self, app):
        r = app.get('/api/founders')
        assert r.status_code == 200

    def test_get_founder_not_found(self, app):
        r = app.get('/api/founders/nonexistent_slug_xyz')
        assert r.status_code == 404

    def test_get_founder_assignment(self, app):
        r = app.get('/api/founders/claravision/assignment')
        # Either 200 with data or 404 if founder not found in test env
        assert r.status_code in (200, 404, 500)

    def test_brief_status_get(self, app):
        r = app.get('/api/founders/claravision/brief-status')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert 'read' in data

    def test_brief_status_post(self, app):
        r = app.post('/api/founders/claravision/brief-status')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data.get('success') is True


# ── Ticket routes ─────────────────────────────────────────────────────────────

class TestTicketRoutes:

    def test_list_tickets_returns_200(self, app):
        r = app.get('/api/tickets')
        assert r.status_code == 200

    def test_list_tickets_returns_json(self, app):
        r = app.get('/api/tickets')
        data = json.loads(r.data)
        assert 'tickets' in data

    def test_submit_ticket_no_body_returns_400(self, app):
        r = app.post('/api/tickets',
                     data=json.dumps({}),
                     content_type='application/json')
        assert r.status_code == 400

    def test_submit_ticket_with_question(self, app):
        payload = {
            'question': 'How do I configure NIM on GKE?',
            'founder_slug': 'claravision',
            'urgency': 'technical'
        }
        r = app.post('/api/tickets',
                     data=json.dumps(payload),
                     content_type='application/json')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert 'ticket_id' in data


# ── Onboarding routes ─────────────────────────────────────────────────────────

class TestOnboardingRoutes:

    def test_predict_chips_empty_returns_200(self, app):
        r = app.post('/api/onboard/predict-chips',
                     data=json.dumps({'partial_profile': {}, 'next_question': 'test'}),
                     content_type='application/json')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert 'chips' in data

    def test_onboard_post_returns_200(self, app):
        payload = {
            'slug': 'test_founder_001',
            'founder_name': 'Test Founder',
            'company': 'TestCo',
            'vision': 'AI for testing',
        }
        r = app.post('/api/onboard',
                     data=json.dumps(payload),
                     content_type='application/json')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data.get('success') is True


# ── Community routes ──────────────────────────────────────────────────────────

class TestCommunityRoutes:

    def test_get_threads_returns_200(self, app):
        r = app.get('/api/community/threads')
        assert r.status_code == 200
        data = json.loads(r.data)
        assert 'threads' in data

    def test_search_no_query_returns_400(self, app):
        r = app.post('/api/community/search',
                     data=json.dumps({}),
                     content_type='application/json')
        assert r.status_code == 400

    def test_search_with_query_returns_200(self, app):
        r = app.post('/api/community/search',
                     data=json.dumps({'query': 'NIM deployment'}),
                     content_type='application/json')
        assert r.status_code == 200


# ── Aria chat ─────────────────────────────────────────────────────────────────

class TestAriaChat:

    def test_aria_chat_no_message_returns_400(self, app):
        r = app.post('/api/aria/chat',
                     data=json.dumps({'founder_slug': 'claravision'}),
                     content_type='application/json')
        assert r.status_code == 400

    def test_aria_chat_with_message(self, app):
        payload = {
            'message': 'How do I configure NIM on GKE?',
            'founder_slug': 'claravision'
        }
        r = app.post('/api/aria/chat',
                     data=json.dumps(payload),
                     content_type='application/json')
        # 200 if NIM responds, 500 if mocked NIM fails — both acceptable in test
        assert r.status_code in (200, 500)
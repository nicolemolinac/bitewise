"""Offline API authentication and account-boundary QA.

Uses a temporary SQLite database and mocked Supabase responses. No external
auth requests, production database, or real credentials are used.
"""
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_TEMP = tempfile.TemporaryDirectory(prefix="bitewise-api-auth-qa-")
os.environ["BITEWISE_LOCAL_DB_PATH"] = str(Path(_TEMP.name) / "auth.sqlite")
os.environ["DATABASE_URL"] = ""
os.environ["AUTO_RESTORE_LOCAL_REWE"] = "false"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_PUBLISHABLE_KEY"] = ""
os.environ["ALLOWED_USER_EMAIL"] = ""
os.environ["SERVICE_TOKEN"] = ""

from fastapi.testclient import TestClient

from app import server
from app.database import Base, engine
from app.cloud_sync import requests as auth_requests

Base.metadata.create_all(engine)
client = TestClient(server.app)


def response(status_code, user=None):
    return SimpleNamespace(status_code=status_code, json=lambda: user or {})


def main():
    auth_env = {
        "SUPABASE_URL": "https://qa-project.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "qa-publishable-key",
        "ALLOWED_USER_EMAIL": "allowed@example.test",
        "SERVICE_TOKEN": "qa-service-token",
    }

    with patch.dict(os.environ, auth_env, clear=False):
        # Protected routes must fail closed when the bearer token is absent.
        missing = client.get("/api/user-state")
        assert missing.status_code == 401, missing.text

        # Invalid/expired Supabase sessions must not reach the user-state route.
        with patch.object(auth_requests, "get", return_value=response(401)):
            expired = client.get("/api/user-state", headers={"Authorization": "Bearer expired-token"})
        assert expired.status_code == 401, expired.text

        # A valid session for a different account must be denied by the allowlist.
        wrong_user = {"id": "qa-other-user", "email": "other@example.test"}
        with patch.object(auth_requests, "get", return_value=response(200, wrong_user)):
            forbidden = client.get("/api/user-state", headers={"Authorization": "Bearer valid-token"})
        assert forbidden.status_code == 403, forbidden.text

        # A valid, allowlisted session is bound to its own user ID.
        allowed_user = {"id": "qa-allowed-user", "email": "allowed@example.test"}
        with patch.object(auth_requests, "get", return_value=response(200, allowed_user)):
            allowed = client.get("/api/user-state", headers={"Authorization": "Bearer valid-token"})
        assert allowed.status_code == 200, allowed.text
        assert allowed.json()["user_id"] == "qa-allowed-user", allowed.json()

        # The internal service token has a separate explicit identity; a wrong
        # token must not silently receive that bypass.
        service = client.get("/api/user-state", headers={"x-service-token": "qa-service-token"})
        assert service.status_code == 200, service.text
        assert service.json()["user_id"] == "personal-ai-os", service.json()
        rejected_service = client.get("/api/user-state", headers={"x-service-token": "wrong-token"})
        assert rejected_service.status_code == 401, rejected_service.text

    print("API AUTH QA PASS: missing/expired bearer, account allowlist, valid user binding and service-token boundary")


if __name__ == "__main__":
    main()

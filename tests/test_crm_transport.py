import json
import subprocess
from unittest.mock import patch

import pytest

from crm_client import CRMClientError, _powershell_get_json


def test_http_error_shows_crm_message_and_redacts_credentials():
    result = subprocess.CompletedProcess([], 22, json.dumps({
        "mybarid_transport_error": True,
        "status": 500,
        "body": json.dumps({"error": {"message": "Invalid field for user alice secret"}}),
        "message": "Internal Server Error",
    }), "")
    with patch("crm_client.subprocess.run", return_value=result):
        with pytest.raises(CRMClientError) as exc:
            _powershell_get_json("https://example.invalid/Main/api/data/v9.1/incidents?fetchXml=private", "alice", "secret")
    message = str(exc.value)
    assert "500" in message and "Invalid field" in message
    assert "alice" not in message and "secret" not in message
    assert "private" not in message


def test_successful_response_is_unchanged():
    result = subprocess.CompletedProcess([], 0, '{"value": [{"incidentid": "123"}]}', "")
    with patch("crm_client.subprocess.run", return_value=result):
        assert _powershell_get_json("https://example.invalid") == {"value": [{"incidentid": "123"}]}


def test_transport_timeout_keeps_original_cause():
    result = subprocess.CompletedProcess([], 22, json.dumps({
        "mybarid_transport_error": True, "status": 0,
        "body": "", "message": "The operation has timed out.",
    }), "")
    with patch("crm_client.subprocess.run", return_value=result):
        with pytest.raises(CRMClientError, match="timed out"):
            _powershell_get_json("https://example.invalid")

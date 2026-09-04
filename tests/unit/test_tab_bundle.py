"""One certificate per response; presentation failures remain actionable."""

import pytest
from fastapi import HTTPException

from webapp import app as app_module
from webapp import presentation


def test_bundle_issues_certificate_once_and_binds_presentation(monkeypatch):
    report = {"journal": []}
    certificate = {"content_sha256": "test-hash"}
    calls = []

    def issue(value):
        assert value is report
        calls.append(value)
        return certificate

    def present(value, *, certificate):
        assert value is report
        assert certificate["content_sha256"] == "test-hash"
        return {"certificate_status": certificate}

    monkeypatch.setattr(app_module, "issue_certificate", issue)
    monkeypatch.setattr(presentation, "build_presentation_payload", present)
    bundle = app_module._tab_bundle(report, {}, "your_run")
    assert len(calls) == 1
    assert bundle["certificate"] is certificate
    assert bundle["presentation"]["certificate_status"] is certificate
    assert bundle["mode"] == bundle["presentation"]["mode"] == bundle["investigations"]["mode"]
    assert not hasattr(app_module, "_RUNS")


def test_bundle_invalid_presentation_is_422(monkeypatch):
    monkeypatch.setattr(app_module, "issue_certificate", lambda report: {})

    def invalid(*args, **kwargs):
        raise presentation.PresentationSchemaError("Invalid report")

    monkeypatch.setattr(presentation, "build_presentation_payload", invalid)
    with pytest.raises(HTTPException) as exc:
        app_module._tab_bundle({}, {}, "your_run")
    assert exc.value.status_code == 422

"""Phase-1 contract serialization smoke tests.

The other suites call route functions and assert on the raw dict. These assert
on what FastAPI actually emits to clients: for each contract endpoint, FastAPI
runs ``response_model.model_validate(data).model_dump(mode="json")`` before
sending. We reproduce that exact step here to prove that declaring a
response_model does NOT drop any field (thanks to ``extra="allow"``), and that
the live-created and persisted views expose a consistent contract field set.

This avoids the starlette-0.36 / httpx-0.28 TestClient incompatibility in this
environment while still verifying the real serialization contract.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.orchestrator import AgentContext, OralAgentOrchestrator
from app.api import routes
from app.core.config import settings
from app.core.database import Base
from app.models.entities import Consultation, DoctorReview, User
from app.schemas.contracts import (
    ConsultationDetailResponse,
    ConsultationTraceItem,
    PendingReviewItem,
)
from app.services.auth import CurrentUser


def _sqlite_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed(db):
    settings.deepseek_enabled = False
    user_row = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user_row)
    db.commit()
    db.refresh(user_row)

    message = "牙痛三天，脸肿了，我能不能吃头孢？"
    response = OralAgentOrchestrator().run(AgentContext(message=message))
    consultation = routes._persist_consultation(
        db,
        CurrentUser(id=user_row.id, external_id="patient-demo", role="patient", display_name="患者 Demo"),
        message,
        response,
    )
    return consultation


def _serialize(model_cls, data):
    """Reproduce FastAPI's response_model serialization step."""
    return model_cls.model_validate(data).model_dump(mode="json")


def test_consultation_detail_serialized_keeps_archive_and_traceability_fields():
    db = _sqlite_session()
    consultation = _seed(db)

    raw = routes._consultation_detail_payload(db, consultation, include_llm=True)
    body = _serialize(ConsultationDetailResponse, raw)

    for key in ("consultation", "archive_summary", "traceability", "review_context"):
        assert key in body, f"missing top-level key after serialization: {key}"

    archive = body["archive_summary"]
    for key in (
        "consultation_id",
        "doctor_review_id",
        "workflow_agent_count",
        "visited_agents",
        "safety_flag_count",
        "refusal",
        "has_image",
    ):
        assert key in archive, f"archive_summary lost field after serialization: {key}"

    trace = body["traceability"]
    assert trace["persistence"]["doctor_review_table"] == "doctor_reviews"
    assert "persisted_hit_count" in trace["rag"]
    assert "persisted_call_count" in trace["llm"]
    assert any(step.get("stage") == "workflow_agent" for step in trace["execution_timeline"])

    # No field loss: every key in the raw dict survives into the serialized body.
    assert set(raw["archive_summary"]).issubset(set(archive))


def test_live_and_persisted_archive_summary_field_sets_match():
    """The whole point of phase-1: the field set a patient sees at creation time
    equals the field set seen later via the persisted detail view. Compared on
    the raw dicts (like-for-like, neither passed through the DTO) so the check
    reflects the real builders, not model-injected defaults."""
    db = _sqlite_session()
    consultation = _seed(db)

    live = routes._json_loads(consultation.result_json, {})["structured_data"]["archive_summary"]
    persisted = routes._consultation_detail_payload(db, consultation, include_llm=True)["archive_summary"]

    assert set(live) == set(persisted), (
        f"archive_summary field drift -> only live: {set(live) - set(persisted)}, "
        f"only persisted: {set(persisted) - set(live)}"
    )


def test_admin_consultation_trace_serialized_is_list_with_contract_fields():
    db = _sqlite_session()
    consultation = _seed(db)

    admin = CurrentUser(id=1, external_id="admin-demo", role="admin", display_name="Admin")
    rows = routes.admin_consultation_trace(db=db, user=admin)
    assert rows
    serialized = [_serialize(ConsultationTraceItem, row) for row in rows]

    row = next(r for r in serialized if r["consultation_id"] == consultation.id)
    assert row["archive_summary"]["consultation_id"] == consultation.id
    assert "traceability" in row
    assert "persisted_call_count" in row["traceability"]["llm"]


def test_doctor_reviews_list_serialized_keeps_fields():
    db = _sqlite_session()
    _seed(db)

    doctor = CurrentUser(id=1, external_id="doctor-demo", role="doctor", display_name="Doctor")
    rows = routes.pending_reviews(db=db, user=doctor)
    assert rows
    serialized = [_serialize(PendingReviewItem, row) for row in rows]
    row = serialized[0]
    for key in ("review_id", "consultation_id", "status", "agent_type", "risk_level", "summary"):
        assert key in row, f"pending review row lost field: {key}"

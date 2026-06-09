"""End-to-end business-chain tests — the refactor safety net for phase 4.

The other suites cover individual links (creation, archive, trace, review,
evaluation) in isolation. These tests walk a SINGLE consultation through the
whole real-world chain and assert the data stays correctly linked across every
hand-off:

    patient consultation
      -> RAG retrieval
        -> agent output (contract)
          -> archive (traceability)
            -> doctor review
              -> patient views result
                -> admin consultation trace
                  -> backend evaluation report

If a later refactor (service extraction / routes split) breaks the continuity
between any two links, one of these tests fails — even when the per-link unit
tests still pass. Uses the same in-memory SQLite + deepseek_enabled=False setup
as the rest of the suite, so it needs neither MySQL nor a live LLM.
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.orchestrator import AgentContext, OralAgentOrchestrator
from app.api import routes
from app.core.config import settings
from app.core.database import Base
from app.models.entities import DoctorReview, User
from app.schemas.dto import PatientProfileInput, ReviewUpdate
from app.services.auth import CurrentUser


PATIENT = CurrentUser(id=1, external_id="patient-demo", role="patient", display_name="患者 Demo")
DOCTOR = CurrentUser(id=2, external_id="doctor-demo", role="doctor", display_name="医生 Demo")
ADMIN = CurrentUser(id=3, external_id="admin-demo", role="admin", display_name="管理员 Demo")


def _session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _seed_users(db):
    for cu in (PATIENT, DOCTOR, ADMIN):
        db.add(User(external_id=cu.external_id, role=cu.role, display_name=cu.display_name))
    db.commit()


def test_full_chain_consultation_to_review_to_trace_to_evaluation():
    settings.deepseek_enabled = False
    db = _session()
    _seed_users(db)

    # 1) Patient consultation -> RAG retrieval -> agent output -> archive.
    # A high-risk medication question guarantees doctor_review_required + sources.
    message = "牙痛肿胀，想问阿莫西林吃几片。我青霉素过敏，体重60kg，肾功能不好。"
    response = OralAgentOrchestrator().run(
        AgentContext(
            message=message,
            requested_agent="medication",
            patient_profile=PatientProfileInput(age=70, allergies="青霉素过敏", conditions="肾功能不好"),
        )
    )
    consultation = routes._persist_consultation(db, PATIENT, message, response)
    cid = consultation.id

    # RAG retrieval actually happened and the agent produced a contract.
    assert response.sources, "expected RAG sources on a medication consultation"
    assert response.doctor_review_required is True
    assert response.structured_data and "agent_contract" in response.structured_data

    # Archive was written linking this consultation to its traceability.
    archived = routes._json_loads(consultation.result_json, {})["structured_data"]
    assert archived["archive_summary"]["consultation_id"] == cid
    assert archived["traceability"]["consultation_id"] == cid

    # 2) Doctor sees the review in their queue, keyed to the same consultation.
    pending = routes.pending_reviews(db=db, user=DOCTOR)
    assert any(item["consultation_id"] == cid for item in pending)
    review = db.query(DoctorReview).filter(DoctorReview.consultation_id == cid).first()
    assert review is not None

    # 3) Doctor approves; the decision must sync back into the archived traceability.
    routes.update_review(
        review.id,
        ReviewUpdate(
            status="approved",
            note="已复核：禁止自行用药，需线下处理病因。",
            risk_assessment="青霉素过敏合并肾功能异常，维持高风险。",
            treatment_decision="offline_visit",
            signature="doctor-demo",
            signature_title="口腔医生",
        ),
        db=db,
        user=DOCTOR,
    )
    db.refresh(consultation)
    assert consultation.status == "review_approved"

    # 4) Patient views the result -> sees the doctor's decision reflected.
    detail = routes.consultation_detail(cid, db=db, user=PATIENT)
    assert detail["consultation"]["id"] == cid
    assert detail["review_context"]["status"] == "approved"
    assert detail["archive_summary"]["review_status"] == "approved"
    assert detail["traceability"]["review"]["status"] == "approved"

    # Patient history lists the same consultation.
    history = routes.consultation_history(db=db, user=PATIENT)
    assert any(item.id == cid for item in history)

    # 5) Admin trace exposes the full retrieval/LLM/review state for this consultation.
    trace_rows = routes.admin_consultation_trace(db=db, user=ADMIN)
    trace = next((r for r in trace_rows if r["consultation_id"] == cid), None)
    assert trace is not None
    assert trace["review"]["status"] == "approved"
    assert trace["archive_summary"]["consultation_id"] == cid
    assert trace["traceability"]["persistence"]["doctor_review_table"] == "doctor_reviews"

    # 6) Backend evaluation report runs end-to-end and produces a readiness summary.
    run = routes.create_evaluation_run({"name": "E2E 链路验收"}, db=db, user=ADMIN)
    assert run["total_cases"] >= 1
    assert run["summary"]["passed_cases"] >= 0
    assert run["summary"]["total_cases"] == run["total_cases"]
    report = routes.admin_evaluation_report(db=db, user=ADMIN)
    assert report["latest_run"] is not None
    assert report["latest_run"]["run_id"] == run["run_id"]


def test_full_chain_low_risk_consultation_completes_without_review():
    """The other arm of the chain: a low-risk consultation archives and is
    viewable without ever entering the doctor-review branch."""
    settings.deepseek_enabled = False
    db = _session()
    _seed_users(db)

    message = "想了解日常如何正确刷牙和使用牙线做口腔保健。"
    response = OralAgentOrchestrator().run(
        AgentContext(message=message, requested_agent="health")
    )
    consultation = routes._persist_consultation(db, PATIENT, message, response)
    cid = consultation.id

    assert consultation.status == "completed"
    assert response.doctor_review_required is False

    # Patient can view it; there is no review context yet.
    detail = routes.consultation_detail(cid, db=db, user=PATIENT)
    assert detail["consultation"]["id"] == cid
    assert detail["review"] is None
    assert detail["review_context"] is None
    # Archive/traceability are still fully populated for a completed consultation.
    assert detail["archive_summary"]["consultation_id"] == cid
    assert detail["traceability"]["consultation_id"] == cid


def test_patient_cannot_view_another_patients_consultation():
    """Cross-patient access control holds across the chain."""
    settings.deepseek_enabled = False
    db = _session()
    _seed_users(db)
    db.add(User(external_id="patient-other", role="patient", display_name="其他患者"))
    db.commit()

    message = "想了解日常如何正确刷牙和使用牙线做口腔保健。"
    response = OralAgentOrchestrator().run(
        AgentContext(message=message, requested_agent="health")
    )
    consultation = routes._persist_consultation(db, PATIENT, message, response)

    other = CurrentUser(id=4, external_id="patient-other", role="patient", display_name="其他患者")
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        routes.consultation_detail(consultation.id, db=db, user=other)
    assert exc.value.status_code == 403

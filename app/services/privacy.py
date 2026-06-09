"""Privacy & data-subject request service.

Relocated from app/api/routes.py during the phase-4 service extraction. Handles
GDPR-style data export / deletion for a patient, default privacy record seeding,
and the export summary used by the /patient/data-request* and /admin/privacy/*
endpoints.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import (
    Consultation,
    DataRetentionPolicy,
    FollowUpReminder,
    HealthPlan,
    Notification,
    PatientConsent,
    PatientProfile,
    PrivacyImpactAssessment,
    ToothRecord,
    TreatmentRecord,
)
from app.api.serializers import (
    _notification_payload,
    _patient_profile_payload,
    _reminder_payload,
    _tooth_record_payload,
    _treatment_record_payload,
)
from app.services.traceability import _json_loads


def _generate_data_export(db: Session, user_external_id: str, data_scope: str) -> str:
    """Generate data export for user."""
    scope = {item.strip().lower() for item in data_scope.split(",") if item.strip()}
    include_all = "all" in scope or "全部" in data_scope
    data = {
        "scope": data_scope,
        "exported_at": datetime.utcnow().isoformat(),
        "patient_profile": None,
        "consent_history": [],
        "consultations": [],
        "treatment_records": [],
        "tooth_records": [],
        "health_plans": [],
        "reminders": [],
        "notifications": [],
    }
    if include_all or "profile" in scope or "patient_profiles" in scope:
        profile = db.query(PatientProfile).filter(PatientProfile.user_external_id == user_external_id).first()
        data["patient_profile"] = _patient_profile_payload(profile)
    if include_all or "consents" in scope or "consent" in scope:
        consents = db.query(PatientConsent).filter(PatientConsent.user_external_id == user_external_id).all()
        data["consent_history"] = [
            {
                "type": c.consent_type,
                "version": c.consent_version,
                "scope": c.scope,
                "consented": c.consented,
                "signed_at": c.signed_at.isoformat() if c.signed_at else None,
                "revoked_at": c.revoked_at.isoformat() if c.revoked_at else None,
            }
            for c in consents
        ]
    if include_all or "consultations" in scope:
        consultations = db.query(Consultation).filter(Consultation.patient_external_id == user_external_id).all()
        data["consultations"] = [
            {
                "id": c.id,
                "agent_type": c.agent_type,
                "risk_level": c.risk_level,
                "status": c.status,
                "doctor_review_required": c.doctor_review_required,
                "created_at": c.created_at.isoformat(),
                "summary": c.summary[:500],
                "sources": _json_loads(c.sources_json, []),
            }
            for c in consultations
        ]
    if include_all or "treatment_records" in scope or "treatments" in scope:
        data["treatment_records"] = [
            _treatment_record_payload(row)
            for row in db.query(TreatmentRecord).filter(TreatmentRecord.user_external_id == user_external_id).all()
        ]
    if include_all or "tooth_records" in scope or "tooth" in scope:
        data["tooth_records"] = [
            _tooth_record_payload(row)
            for row in db.query(ToothRecord).filter(ToothRecord.user_external_id == user_external_id).all()
        ]
    if include_all or "health_plans" in scope or "health" in scope:
        data["health_plans"] = [
            {
                "id": row.id,
                "consultation_id": row.consultation_id,
                "plan_type": row.plan_type,
                "plan": _json_loads(row.plan_json, {}),
                "status": row.status,
                "created_at": row.created_at.isoformat(),
            }
            for row in db.query(HealthPlan).filter(HealthPlan.user_external_id == user_external_id).all()
        ]
    if include_all or "reminders" in scope:
        data["reminders"] = [
            _reminder_payload(row)
            for row in db.query(FollowUpReminder).filter(FollowUpReminder.user_external_id == user_external_id).all()
        ]
    if include_all or "notifications" in scope:
        data["notifications"] = [
            _notification_payload(row)
            for row in db.query(Notification).filter(Notification.user_external_id == user_external_id).all()
        ]
    return json.dumps(data, ensure_ascii=False)


def _process_data_deletion(db: Session, user_external_id: str, data_scope: str) -> None:
    """Process data deletion request."""
    if "consultations" in data_scope.lower():
        db.query(Consultation).filter(Consultation.patient_external_id == user_external_id).delete()
    if "profile" in data_scope.lower():
        db.query(PatientProfile).filter(PatientProfile.user_external_id == user_external_id).delete()
    db.commit()


def _ensure_default_privacy_records(db: Session) -> dict[str, int]:
    policies = [
        ("consultations", 1095, "咨询记录、Agent输出、RAG来源和医生复核记录保留3年。"),
        ("patient_profiles", 1095, "患者档案随咨询服务保留，支持患者发起导出或删除申请。"),
        ("uploaded_files", 180, "影像上传文件仅作归档占位，默认保留180天。"),
        ("llm_call_logs", 365, "模型调用日志保留1年用于审计、费用和延迟监控。"),
        ("audit_logs", 1825, "关键操作审计日志保留5年。"),
    ]
    created_policies = 0
    for category, days, description in policies:
        row = db.query(DataRetentionPolicy).filter(DataRetentionPolicy.data_category == category).first()
        if row is None:
            db.add(
                DataRetentionPolicy(
                    data_category=category,
                    retention_days=days,
                    description=description,
                    auto_delete=True,
                    archived=False,
                )
            )
            created_policies += 1

    assessment = (
        db.query(PrivacyImpactAssessment)
        .filter(PrivacyImpactAssessment.assessment_id == "pia-internal-beta-001")
        .first()
    )
    created_assessments = 0
    if assessment is None:
        db.add(
            PrivacyImpactAssessment(
                assessment_id="pia-internal-beta-001",
                title="生产级内测隐私影响评估",
                description="覆盖患者档案、咨询文本、RAG检索来源、医生复核、上传文件和调用日志。",
                data_types="姓名/账号、年龄、妊娠状态、过敏史、基础病、口腔病史、咨询文本、影像上传元数据、模型调用日志。",
                risk_level="medium",
                mitigation_measures="角色权限、审计日志、敏感信息脱敏、数据导出/删除申请、保留期限策略、影像不做真实诊断。",
                compliance_status="active",
            )
        )
        created_assessments = 1
    db.commit()
    return {"retention_policies_created": created_policies, "assessments_created": created_assessments}


def _data_export_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": result.get("scope"),
        "exported_at": result.get("exported_at"),
        "patient_profile": bool(result.get("patient_profile")),
        "consent_count": len(result.get("consent_history") or []),
        "consultation_count": len(result.get("consultations") or []),
        "treatment_record_count": len(result.get("treatment_records") or []),
        "tooth_record_count": len(result.get("tooth_records") or []),
        "health_plan_count": len(result.get("health_plans") or []),
        "reminder_count": len(result.get("reminders") or []),
        "notification_count": len(result.get("notifications") or []),
    }

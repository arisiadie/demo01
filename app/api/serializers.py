"""Shared row serializers.

Pure functions that turn ORM rows into API dicts, used by multiple endpoint
domains and services. Extracted in phase-4 so both app/api/routes.py and
app/services/* can import them without circular dependencies.
"""
from __future__ import annotations

from typing import Any

from app.models.entities import (
    FollowUpReminder,
    Notification,
    PatientProfile,
    ToothRecord,
    TreatmentRecord,
)
from app.services.security import mask_sensitive_data


def _patient_profile_payload(profile: PatientProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
        "name": mask_sensitive_data(profile.name),
        "age": profile.age,
        "sex": profile.sex,
        "pregnancy_status": profile.pregnancy_status,
        "allergies": profile.allergies,
        "conditions": profile.conditions,
        "oral_history": profile.oral_history,
        "updated_at": profile.updated_at.isoformat(),
    }


def _treatment_record_payload(row: TreatmentRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_external_id": row.user_external_id,
        "consultation_id": row.consultation_id,
        "tooth_position": row.tooth_position,
        "diagnosis_text": row.diagnosis_text,
        "treatment_name": row.treatment_name,
        "treatment_date": row.treatment_date.isoformat() if row.treatment_date else None,
        "doctor_name": row.doctor_name,
        "institution": row.institution,
        "cost_amount": row.cost_amount,
        "next_visit_at": row.next_visit_at.isoformat() if row.next_visit_at else None,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _tooth_record_payload(row: ToothRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_external_id": row.user_external_id,
        "tooth_position": row.tooth_position,
        "status": row.status,
        "diagnosis_text": row.diagnosis_text,
        "treatment_summary": row.treatment_summary,
        "maintenance_cycle_days": row.maintenance_cycle_days,
        "next_check_at": row.next_check_at.isoformat() if row.next_check_at else None,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _reminder_payload(row: FollowUpReminder) -> dict[str, Any]:
    return {
        "id": row.id,
        "consultation_id": row.consultation_id,
        "user_external_id": row.user_external_id,
        "reminder_type": row.reminder_type,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "status": row.status,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
    }


def _notification_payload(row: Notification) -> dict[str, Any]:
    return {
        "id": row.id,
        "user_external_id": row.user_external_id,
        "channel": row.channel,
        "title": row.title,
        "content": row.content,
        "status": row.status,
        "scheduled_at": row.scheduled_at.isoformat() if row.scheduled_at else None,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "created_at": row.created_at.isoformat(),
    }

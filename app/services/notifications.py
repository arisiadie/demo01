"""Notification & reminder generation service.

Relocated from app/api/routes.py during the phase-4 service extraction. Creates
due follow-up notifications from reminders and tooth-record maintenance cycles,
and the education-feed notifications, used by the /patient/notifications* and
/admin/notifications endpoints plus the startup scheduler.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import FollowUpReminder, Notification, ToothRecord
from app.api.serializers import _notification_payload


def _create_education_notifications(
    db: Session,
    user_external_id: str,
    items: list[dict[str, Any]],
) -> list[Notification]:
    created: list[Notification] = []
    for item in items:
        title = f"科普推送：{item['title']}"
        content = f"{item['recommendation_reason']} {item['excerpt']}"
        duplicate = (
            db.query(Notification)
            .filter(Notification.user_external_id == user_external_id)
            .filter(Notification.title == title)
            .first()
        )
        if duplicate is not None:
            continue
        row = Notification(
            user_external_id=user_external_id,
            channel="in_app",
            title=title,
            content=content,
            status="unread",
            scheduled_at=datetime.utcnow(),
            sent_at=datetime.utcnow(),
        )
        db.add(row)
        created.append(row)
    db.commit()
    for row in created:
        db.refresh(row)
    return created


def _create_notification(
    db: Session,
    *,
    user_external_id: str,
    title: str,
    content: str,
    scheduled_at: datetime | None = None,
) -> None:
    db.add(
        Notification(
            user_external_id=user_external_id,
            channel="in_app",
            title=title,
            content=content,
            status="unread",
            scheduled_at=scheduled_at,
        )
    )
    db.commit()


def _generate_due_notifications(db: Session, user_external_id: str) -> list[Notification]:
    now = datetime.utcnow()
    due_scheduled_notifications = (
        db.query(Notification)
        .filter(Notification.user_external_id == user_external_id)
        .filter(Notification.status == "unread")
        .filter(Notification.sent_at.is_(None))
        .filter(Notification.scheduled_at.is_not(None))
        .filter(Notification.scheduled_at <= now)
        .order_by(Notification.scheduled_at)
        .limit(50)
        .all()
    )
    for notification in due_scheduled_notifications:
        notification.sent_at = now

    reminders = (
        db.query(FollowUpReminder)
        .filter(FollowUpReminder.user_external_id == user_external_id)
        .filter(FollowUpReminder.status == "pending")
        .filter((FollowUpReminder.due_at.is_(None)) | (FollowUpReminder.due_at <= now))
        .order_by(FollowUpReminder.created_at)
        .limit(50)
        .all()
    )
    created: list[Notification] = list(due_scheduled_notifications)
    for reminder in reminders:
        title = "复诊/护理到期提醒"
        content = reminder.note
        duplicate = (
            db.query(Notification)
            .filter(Notification.user_external_id == user_external_id)
            .filter(Notification.title == title)
            .filter(Notification.content == content)
            .first()
        )
        if duplicate is not None:
            reminder.status = "notified"
            continue
        notification = Notification(
            user_external_id=user_external_id,
            channel="in_app",
            title=title,
            content=content,
            status="unread",
            scheduled_at=reminder.due_at,
            sent_at=now,
        )
        db.add(notification)
        created.append(notification)
        reminder.status = "notified"
    db.commit()
    for item in created:
        db.refresh(item)
    return created


def _run_due_notifications_for_all(db: Session) -> list[Notification]:
    reminder_users = [row[0] for row in db.query(FollowUpReminder.user_external_id).distinct().all()]
    notification_users = [
        row[0]
        for row in (
            db.query(Notification.user_external_id)
            .filter(Notification.status == "unread")
            .filter(Notification.sent_at.is_(None))
            .filter(Notification.scheduled_at.is_not(None))
            .distinct()
            .all()
        )
    ]
    created: list[Notification] = []
    for external_id in sorted(set(reminder_users + notification_users)):
        created.extend(_generate_due_notifications(db, external_id))
    return created

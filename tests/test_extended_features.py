from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.orchestrator import AgentContext, OralAgentOrchestrator
from app.agents.workflow import MultiAgentWorkflow
from app.api import routes
from app.core.config import settings
from app.core.database import Base
from app.models.entities import (
    AgentRun,
    AuditLog,
    Consultation,
    DataAccessRequest,
    DoctorReview,
    EvaluationCase,
    EvaluationResult,
    EvaluationRun,
    FollowUpReminder,
    KnowledgeDocument,
    KnowledgeVersion,
    LLMCallLog,
    Notification,
    PatientProfile,
    RetrievalHit,
    ToothRecord,
    TreatmentRecord,
    User,
)
from app.rag.store import KnowledgeStore
from app.schemas.dto import PatientProfileInput, ReviewUpdate
from app.services.auth import CurrentUser
from app.services.llm import LLMClient


def _sqlite_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    return session_factory()


def test_runtime_admin_knowledge_sync_enters_retrieval_store():
    db = _sqlite_session()
    version = KnowledgeVersion(
        version="test-admin-sync",
        title="测试知识库",
        document_count=1,
        retrieval_backend="local-hybrid",
        quality_score=1.0,
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    db.add(
        KnowledgeDocument(
            knowledge_version_id=version.id,
            doc_uid="admin-test-fluoride",
            title="管理员儿童涂氟规则",
            category="health",
            source="管理员测试",
            tags_json='["儿童", "涂氟", "管理员知识"]',
            content="管理员知识：儿童高龋风险可按医生评估进行涂氟和复诊维护。",
            active=True,
        )
    )
    db.commit()

    result = routes._sync_runtime_knowledge_from_db(db)
    hits = routes.store.retrieve("管理员知识 儿童 涂氟", categories=["health"], top_k=5)

    assert result["admin_document_count"] >= 1
    assert any(hit.document.id == "admin-test-fluoride" for hit in hits)


def test_runtime_admin_knowledge_sync_filters_test_residue():
    db = _sqlite_session()
    db.add(
        KnowledgeDocument(
            doc_uid="admin-smoke-residue",
            title="烟测儿童涂氟知识",
            category="health",
            source="接口烟测",
            tags_json='["儿童", "涂氟", "ASCII_RAG_TEST_123"]',
            content="ASCII_RAG_TEST_123：这条记录不应进入运行时检索。",
            active=True,
        )
    )
    db.commit()

    result = routes._sync_runtime_knowledge_from_db(db)
    hits = routes.store.retrieve("ASCII_RAG_TEST_123 儿童 涂氟", categories=["health"], top_k=5)

    assert result["admin_document_count"] == 0
    assert all(hit.document.id != "admin-smoke-residue" for hit in hits)


def test_due_notification_scan_marks_reminder_and_prevents_duplicates():
    db = _sqlite_session()
    due_at = datetime.utcnow() - timedelta(days=1)
    db.add(
        FollowUpReminder(
            user_external_id="patient-demo",
            reminder_type="routine_follow_up",
            due_at=due_at,
            status="pending",
            note="右下6 根管后到期复查",
        )
    )
    db.add(
        Notification(
            user_external_id="patient-demo",
            title="牙位维护提醒",
            content="左上6 到期维护",
            status="unread",
            scheduled_at=due_at,
        )
    )
    db.commit()

    first = routes._generate_due_notifications(db, "patient-demo")
    second = routes._generate_due_notifications(db, "patient-demo")

    reminder = db.query(FollowUpReminder).first()
    scheduled = db.query(Notification).filter(Notification.content == "左上6 到期维护").first()
    assert len(first) == 2
    assert len(second) == 0
    assert reminder.status == "notified"
    assert scheduled.sent_at is not None


def test_medication_review_exposes_clinical_context_and_handoff_tasks():
    settings.deepseek_enabled = False
    orchestrator = OralAgentOrchestrator()
    response = orchestrator.run(
        AgentContext(
            message="牙痛肿胀，想问阿莫西林吃几片。我青霉素过敏，体重60kg，肾功能不好。",
            requested_agent="medication",
            patient_profile=PatientProfileInput(age=70, allergies="青霉素过敏", conditions="肾功能不好"),
        )
    )

    check = response.structured_data["medication_check"]
    cross_review = response.structured_data["cross_agent_review"]
    assert check["dose_request_detected"] is True
    assert "clinical_review_items" in check
    assert any("肾功能" in item for item in check["contraindications"])
    assert cross_review["final_review_required"] is True
    assert cross_review["handoff_tasks"]


def test_tooth_record_plan_flags_risk_and_overdue():
    row = ToothRecord(
        user_id=1,
        user_external_id="patient-demo",
        tooth_position="右下6",
        status="根管后观察",
        diagnosis_text="根尖区不适",
        treatment_summary="根管治疗后待冠修复",
        maintenance_cycle_days=90,
        next_check_at=datetime.utcnow() - timedelta(days=1),
    )

    plan = routes._tooth_maintenance_plan(row)

    assert plan["risk_level"] == "high"
    assert plan["overdue"] is True
    assert any("根尖" in item or "冠修复" in item for item in plan["focus"])


def test_tooth_chart_normalizes_common_tooth_labels():
    rows = [
        ToothRecord(
            user_id=1,
            user_external_id="patient-demo",
            tooth_position="右下6 / 46",
            status="根管后观察",
            diagnosis_text="根尖区不适",
            treatment_summary="根管治疗后待冠修复",
            maintenance_cycle_days=90,
            next_check_at=datetime.utcnow() - timedelta(days=1),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    ]

    chart = routes._tooth_chart_payload(rows)
    tooth = next(item for item in chart["teeth"] if item["position"] == "46")

    assert tooth["has_record"] is True
    assert tooth["risk_level"] == "high"
    assert tooth["overdue"] is True
    assert chart["summary"]["record_count"] == 1


def test_patient_education_feed_uses_profile_and_records_for_recommendations():
    db = _sqlite_session()
    user = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        PatientProfile(
            user_external_id="patient-demo",
            age=8,
            conditions="糖尿病家族史",
            oral_history="换牙期，龋风险较高",
        )
    )
    db.add(
        ToothRecord(
            user_id=user.id,
            user_external_id="patient-demo",
            tooth_position="46",
            status="龋坏充填后观察",
            maintenance_cycle_days=90,
            next_check_at=datetime.utcnow() + timedelta(days=30),
        )
    )
    db.add(
        TreatmentRecord(
            user_id=user.id,
            user_external_id="patient-demo",
            tooth_position="46",
            diagnosis_text="龋坏",
            treatment_name="充填治疗",
        )
    )
    db.commit()

    feed = routes._education_feed_payload(
        db,
        CurrentUser(id=user.id, external_id="patient-demo", role="patient", display_name="患者 Demo"),
        limit=5,
    )
    created = routes._create_education_notifications(db, "patient-demo", feed["items"])
    created_again = routes._create_education_notifications(db, "patient-demo", feed["items"])

    assert "儿童" in feed["focus_terms"]
    assert "龋病预防" in feed["focus_terms"]
    assert feed["items"]
    assert all(item["source"] for item in feed["items"])
    assert len(created) > 0
    assert len(created_again) == 0


def test_data_export_payload_tracks_patient_business_records():
    db = _sqlite_session()
    user = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(PatientProfile(user_external_id="patient-demo", age=32, allergies="青霉素过敏"))
    db.add(
        Consultation(
            user_id=user.id,
            patient_external_id="patient-demo",
            agent_type="triage",
            input_text="牙痛",
            sanitized_input="牙痛",
            summary="牙痛预问诊摘要",
            risk_level="medium",
            sources_json="[]",
            result_json="{}",
            doctor_review_required=True,
        )
    )
    db.add(
        ToothRecord(
            user_id=user.id,
            user_external_id="patient-demo",
            tooth_position="46",
            status="根管后观察",
        )
    )
    db.add(
        DataAccessRequest(
            user_external_id="patient-demo",
            request_type="export",
            status="approved",
            data_scope="all",
        )
    )
    db.commit()
    request = db.query(DataAccessRequest).first()
    request.result_data = routes._generate_data_export(db, "patient-demo", "all")
    db.commit()

    payload = routes._data_access_request_payload(request, include_result=True)

    assert payload["result_summary"]["consultation_count"] == 1
    assert payload["result_summary"]["tooth_record_count"] == 1
    assert payload["result_data"]["patient_profile"]["age"] == 32


def test_admin_audit_endpoint_returns_real_audit_logs():
    db = _sqlite_session()
    db.add(
        AuditLog(
            actor_external_id="admin-demo",
            actor_role="admin",
            action="knowledge_document.create",
            resource_type="knowledge_document",
            resource_id="1",
            risk_level="medium",
            detail_json='{"title":"测试文档"}',
        )
    )
    db.commit()

    rows = routes.audit_logs(
        db=db,
        user=CurrentUser(id=1, external_id="admin-demo", role="admin", display_name="管理员"),
    )

    assert rows[0]["action"] == "knowledge_document.create"
    assert rows[0]["detail"]["title"] == "测试文档"


def test_admin_consultation_trace_exposes_retrieval_llm_and_review_state():
    db = _sqlite_session()
    user = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user)
    db.commit()
    db.refresh(user)
    consultation = Consultation(
        user_id=user.id,
        patient_external_id="patient-demo",
        agent_type="medication",
        input_text="阿莫西林怎么吃",
        sanitized_input="阿莫西林怎么吃",
        summary="安全边界：不提供具体剂量",
        risk_level="medium",
        sources_json="[]",
        result_json="{}",
        doctor_review_required=True,
        status="review_pending",
    )
    db.add(consultation)
    db.commit()
    db.refresh(consultation)
    db.add(
        RetrievalHit(
            consultation_id=consultation.id,
            document_uid="medication-antibiotic-001",
            title="抗菌药物规则",
            category="medication",
            source="测试规则",
            score=0.92,
            rank=1,
            excerpt="青霉素过敏需禁用阿莫西林。",
        )
    )
    db.add(
        LLMCallLog(
            consultation_id=consultation.id,
            provider="deepseek",
            model_name="deepseek-v4-pro",
            status="fallback_disabled",
            latency_ms=0,
            request_preview="request",
            response_preview="response",
        )
    )
    db.add(DoctorReview(consultation_id=consultation.id, status="pending"))
    db.commit()

    rows = routes.admin_consultation_trace(
        db=db,
        user=CurrentUser(id=2, external_id="admin-demo", role="admin", display_name="管理员"),
    )

    assert rows[0]["retrieval_hits"][0]["document_uid"] == "medication-antibiotic-001"
    assert rows[0]["llm_call"]["status"] == "fallback_disabled"
    assert rows[0]["review"]["status"] == "pending"


def test_persist_consultation_records_main_and_workflow_llm_calls():
    settings.deepseek_enabled = False
    db = _sqlite_session()
    user_row = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user_row)
    db.commit()
    db.refresh(user_row)

    orchestrator = OralAgentOrchestrator()
    response = orchestrator.run(
        AgentContext(
            message="医生建议根管治疗，想了解治疗方案后怎么护理。",
            requested_agent="treatment",
        )
    )
    consultation = routes._persist_consultation(
        db,
        CurrentUser(id=user_row.id, external_id="patient-demo", role="patient", display_name="患者 Demo"),
        "医生建议根管治疗，想了解治疗方案后怎么护理。",
        response,
    )

    logs = db.query(LLMCallLog).filter(LLMCallLog.consultation_id == consultation.id).all()
    previews = [row.request_preview for row in logs]

    assert len(logs) >= 2
    assert any(preview.startswith("[main_agent:treatment]") for preview in previews)
    assert any(preview.startswith("[workflow_agent:treatment]") for preview in previews)


def test_phase6_persisted_traceability_links_archive_rag_llm_workflow_and_review():
    settings.deepseek_enabled = False
    db = _sqlite_session()
    user_row = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user_row)
    db.commit()
    db.refresh(user_row)

    message = "牙痛三天，脸肿了，我能不能吃头孢？"
    orchestrator = OralAgentOrchestrator()
    response = orchestrator.run(AgentContext(message=message))
    consultation = routes._persist_consultation(
        db,
        CurrentUser(id=user_row.id, external_id="patient-demo", role="patient", display_name="患者 Demo"),
        message,
        response,
    )

    result_data = routes._json_loads(consultation.result_json, {})
    structured = result_data["structured_data"]
    archive = structured["archive_summary"]
    traceability = structured["traceability"]
    agent_run = db.query(AgentRun).filter(AgentRun.consultation_id == consultation.id).first()
    logs = db.query(LLMCallLog).filter(LLMCallLog.consultation_id == consultation.id).all()
    hits = db.query(RetrievalHit).filter(RetrievalHit.consultation_id == consultation.id).all()
    review = db.query(DoctorReview).filter(DoctorReview.consultation_id == consultation.id).first()

    assert archive["consultation_id"] == consultation.id
    assert archive["doctor_review_id"] == review.id
    assert archive["workflow_agent_count"] >= 2
    assert traceability["review"]["review_id"] == review.id
    assert traceability["llm"]["call_count"] == len(logs)
    assert traceability["rag"]["source_count"] == len(hits)
    assert traceability["persistence"]["doctor_review_table"] == "doctor_reviews"
    assert any(item["stage"] == "workflow_agent" for item in traceability["execution_timeline"])
    assert any("历史归档" in item for item in routes._json_loads(agent_run.trace_json, []))

    detail = routes.consultation_detail(
        consultation_id=consultation.id,
        db=db,
        user=CurrentUser(id=user_row.id, external_id="patient-demo", role="patient", display_name="患者 Demo"),
    )
    admin_rows = routes.admin_consultation_trace(
        db=db,
        user=CurrentUser(id=99, external_id="admin-demo", role="admin", display_name="管理员"),
    )

    assert detail["traceability"]["rag"]["persisted_hit_count"] == len(hits)
    assert detail["archive_summary"]["llm_call_count"] == len(logs)
    assert admin_rows[0]["traceability"]["llm"]["persisted_call_count"] == len(logs)
    assert admin_rows[0]["agent_run"]["agent_type"] == response.agent_type


def test_phase6_doctor_review_update_syncs_back_to_archived_traceability():
    settings.deepseek_enabled = False
    db = _sqlite_session()
    user_row = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user_row)
    db.commit()
    db.refresh(user_row)

    message = "牙痛肿胀，想问阿莫西林吃几片。我青霉素过敏，体重60kg，肾功能不好。"
    orchestrator = OralAgentOrchestrator()
    response = orchestrator.run(
        AgentContext(
            message=message,
            requested_agent="medication",
            patient_profile=PatientProfileInput(age=70, allergies="青霉素过敏", conditions="肾功能不好"),
        )
    )
    consultation = routes._persist_consultation(
        db,
        CurrentUser(id=user_row.id, external_id="patient-demo", role="patient", display_name="患者 Demo"),
        message,
        response,
    )
    review = db.query(DoctorReview).filter(DoctorReview.consultation_id == consultation.id).first()

    routes.update_review(
        review.id,
        ReviewUpdate(
            status="approved",
            note="医生已复核：禁止自行用药，需线下处理病因。",
            risk_assessment="青霉素过敏和肾功能异常，维持高风险。",
            treatment_decision="offline_visit",
            signature="doctor-demo",
            signature_title="口腔医生",
        ),
        db=db,
        user=CurrentUser(id=2, external_id="doctor-demo", role="doctor", display_name="医生 Demo"),
    )
    db.refresh(consultation)
    result_data = routes._json_loads(consultation.result_json, {})
    structured = result_data["structured_data"]

    assert consultation.status == "review_approved"
    assert structured["review_context"]["status"] == "approved"
    assert structured["review_context"]["reviewed_by"] == "doctor-demo"
    assert structured["archive_summary"]["review_status"] == "approved"
    assert structured["traceability"]["review"]["status"] == "approved"
    assert any(item["label"] == "医生复核状态更新" for item in structured["traceability"]["execution_timeline"])


def test_consultation_detail_payload_contains_archive_trace_sources_and_review():
    db = _sqlite_session()
    user = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user)
    db.commit()
    db.refresh(user)
    consultation = Consultation(
        user_id=user.id,
        patient_external_id="patient-demo",
        agent_type="triage",
        input_text="右下后牙痛",
        sanitized_input="右下后牙痛",
        summary="预问诊摘要",
        risk_level="medium",
        sources_json="[]",
        result_json='{"summary":"预问诊摘要"}',
        doctor_review_required=True,
        status="review_pending",
    )
    db.add(consultation)
    db.commit()
    db.refresh(consultation)
    db.add(
        RetrievalHit(
            consultation_id=consultation.id,
            document_uid="triage-caries-pulpitis-001",
            title="龋病与牙髓炎",
            category="triage",
            source="测试指南",
            score=0.9,
            rank=1,
            excerpt="夜间痛需排查牙髓炎。",
        )
    )
    db.add(DoctorReview(consultation_id=consultation.id, status="pending"))
    db.commit()

    payload = routes.consultation_detail(
        consultation_id=consultation.id,
        db=db,
        user=CurrentUser(id=user.id, external_id="patient-demo", role="patient", display_name="患者 Demo"),
    )

    assert payload["consultation"]["id"] == consultation.id
    assert payload["retrieval_hits"][0]["document_uid"] == "triage-caries-pulpitis-001"
    assert payload["review"]["status"] == "pending"
    assert "历史归档" in payload["disclaimer"]


def test_admin_alerts_include_overdue_review_and_pending_privacy_request():
    db = _sqlite_session()
    user = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user)
    db.commit()
    db.refresh(user)
    consultation = Consultation(
        user_id=user.id,
        patient_external_id="patient-demo",
        agent_type="medication",
        input_text="开药",
        sanitized_input="开药",
        summary="安全边界",
        risk_level="high",
        sources_json="[]",
        result_json="{}",
        doctor_review_required=True,
        status="review_pending",
    )
    db.add(consultation)
    db.commit()
    db.refresh(consultation)
    db.add(DoctorReview(consultation_id=consultation.id, status="pending", due_by=datetime.utcnow() - timedelta(hours=1)))
    db.add(DataAccessRequest(user_external_id="patient-demo", request_type="export", status="pending", data_scope="all"))
    db.commit()

    payload = routes._admin_alerts_payload(db)
    alert_types = {item["type"] for item in payload["alerts"]}

    assert "doctor_review_overdue" in alert_types
    assert "high_risk_consultation" in alert_types
    assert "privacy_request_pending" in alert_types
    assert payload["counts"]["total"] >= 3


def test_phase7_default_evaluation_cases_are_seeded_and_payload_ready():
    db = _sqlite_session()

    routes._ensure_default_evaluation_cases(db)
    rows = db.query(EvaluationCase).all()
    payload = routes.admin_evaluation_cases(
        db=db,
        user=CurrentUser(id=1, external_id="admin-demo", role="admin", display_name="管理员"),
    )

    case_ids = {row.case_id for row in rows}
    assert len(rows) == 10
    assert "demo-triage-toothache" in case_ids
    assert "safety-prescription-boundary" in case_ids
    assert "agent-composite-workflow" in case_ids
    assert {item["evaluation_type"] for item in payload} >= {"demo", "rag", "safety", "agent_quality"}
    assert all(item["expected_structured_keys"] is not None for item in payload)


def test_phase7_evaluation_run_persists_results_summary_and_audit_log():
    settings.deepseek_enabled = False
    db = _sqlite_session()
    admin = User(external_id="admin-demo", role="admin", display_name="管理员 Demo")
    db.add(admin)
    db.commit()
    db.refresh(admin)
    current = CurrentUser(id=admin.id, external_id="admin-demo", role="admin", display_name="管理员 Demo")

    payload = routes.create_evaluation_run(
        {"name": "pytest 验收评测", "case_types": ["rag", "safety"]},
        db=db,
        user=current,
    )

    assert payload["name"] == "pytest 验收评测"
    assert payload["status"] == "completed"
    assert payload["total_cases"] == 4
    assert payload["passed_cases"] == 4
    assert payload["failed_cases"] == 0
    assert payload["summary"]["acceptance_conclusion"] == "通过"
    assert payload["summary"]["by_type"]["rag"]["pass_rate"] == 1.0
    assert payload["summary"]["by_type"]["safety"]["pass_rate"] == 1.0
    assert len(payload["results"]) == 4
    assert db.query(EvaluationRun).count() == 1
    assert db.query(EvaluationResult).count() == 4
    assert db.query(AuditLog).filter(AuditLog.action == "evaluation.run").count() == 1
    assert any(
        item["case_id"] == "safety-prompt-injection"
        and item["response"]["refusal"] is True
        and "prompt_injection_attempt" in item["metrics"]["safety_flags"]
        for item in payload["results"]
    )


def test_phase7_evaluation_report_exposes_readiness_latest_run_and_rag_metrics():
    settings.deepseek_enabled = False
    db = _sqlite_session()
    admin = User(external_id="admin-demo", role="admin", display_name="管理员 Demo")
    db.add(admin)
    db.commit()
    db.refresh(admin)
    current = CurrentUser(id=admin.id, external_id="admin-demo", role="admin", display_name="管理员 Demo")

    before = routes.admin_evaluation_report(db=db, user=current)
    run = routes.create_evaluation_run({"name": "pytest 全量验收"}, db=db, user=current)
    after = routes.admin_evaluation_report(db=db, user=current)

    assert before["readiness"]["status"] == "not_run"
    assert after["module"] == "production-beta-evaluation"
    assert after["case_count"] == 10
    assert after["latest_run"]["run_id"] == run["run_id"]
    assert after["latest_run"]["summary"]["failed_case_ids"] == []
    assert after["readiness"]["status"] == "ready"
    assert after["readiness"]["ready"] is True
    assert after["rag_evaluation"]["hit_rate"] >= 0.8
    assert len(after["acceptance_scenarios"]) == 5


def test_phase7_agent_quality_case_tracks_workflow_sources_and_contract():
    settings.deepseek_enabled = False
    db = _sqlite_session()
    routes._ensure_default_evaluation_cases(db)
    case = db.query(EvaluationCase).filter(EvaluationCase.case_id == "agent-composite-workflow").first()

    result = routes._evaluate_case(case)

    assert result["passed"] is True
    assert result["metrics"]["workflow_agents"][:1] == ["triage"]
    assert "medication" in result["metrics"]["workflow_agents"]
    assert "medication-antibiotic-001" in result["metrics"]["source_ids"]
    assert "agent_contract" in result["metrics"]["structured_keys"]
    assert result["response"]["workflow"]["result_count"] >= 2


def test_sql_schema_tracks_orm_tables_and_review_columns():
    from pathlib import Path

    from scripts.check_schema_alignment import sql_table_columns

    sql = Path("sql/init_oralcare_agentic_rag.sql").read_text(encoding="utf-8")
    sql_tables = sql_table_columns(sql)
    orm_tables = {
        table.name: {column.name for column in table.columns}
        for table in Base.metadata.sorted_tables
    }

    # Every ORM table must exist in the SQL init script.
    assert sorted(set(orm_tables) - set(sql_tables)) == []

    # Column-level alignment for ALL tables: the SQL init script is the deploy-time
    # source of truth and must not drift from the ORM (entities.py). This guards
    # against the historical pattern of patching missing columns at runtime.
    drift = {}
    for table, orm_cols in orm_tables.items():
        missing = orm_cols - sql_tables.get(table, set())
        if missing:
            drift[table] = sorted(missing)
    assert drift == {}, f"ORM columns missing from SQL init script: {drift}"


def test_workflow_persistence_roundtrip_loads_into_orchestrator():
    db = _sqlite_session()
    workflow = MultiAgentWorkflow(KnowledgeStore(), LLMClient())
    workflow.update_graph(
        nodes=[
            {"node_id": "start", "agent_id": "start", "label": "开始"},
            {"node_id": "router", "agent_id": "router", "label": "路由"},
            {"node_id": "treatment", "agent_id": "treatment", "label": "方案"},
            {"node_id": "end", "agent_id": "end", "label": "结束"},
        ],
        edges=[
            {"source": "start", "target": "router", "label": "用户请求"},
            {"source": "router", "target": "treatment", "label": "方案"},
            {"source": "treatment", "target": "end", "label": "直接结束"},
        ],
    )
    workflow.save_graph_to_db(db)

    orchestrator = OralAgentOrchestrator(store=KnowledgeStore(), llm=LLMClient())
    orchestrator.load_workflow_from_db(db)

    assert '"treatment" -> "end"' in orchestrator.get_workflow_graph()


def _admin_user():
    return CurrentUser(id=1, external_id="admin-demo", role="admin", display_name="管理员")


def test_admin_delete_records_cascades_consultation_children():
    db = _sqlite_session()
    user = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user)
    db.commit()
    db.refresh(user)
    consultation = Consultation(
        user_id=user.id,
        patient_external_id="patient-demo",
        agent_type="medication",
        input_text="x",
        sanitized_input="x",
        summary="s",
        risk_level="high",
        sources_json="[]",
        result_json="{}",
    )
    db.add(consultation)
    db.commit()
    db.refresh(consultation)
    db.add_all([
        DoctorReview(consultation_id=consultation.id),
        AgentRun(consultation_id=consultation.id, agent_type="medication", agent_name="用药", risk_level="high"),
        RetrievalHit(consultation_id=consultation.id, document_uid="d1", title="t", category="health", source="s", excerpt="e"),
        LLMCallLog(consultation_id=consultation.id, model_name="deepseek", status="success", request_preview="p"),
        FollowUpReminder(consultation_id=consultation.id, user_external_id="patient-demo", reminder_type="review", note="n"),
    ])
    db.commit()

    result = routes.admin_delete_records(
        resource="consultation",
        payload={"ids": [consultation.id]},
        db=db,
        user=_admin_user(),
    )

    assert result["deleted"] == 1
    assert db.query(Consultation).count() == 0
    # No orphaned child rows remain.
    assert db.query(DoctorReview).count() == 0
    assert db.query(AgentRun).count() == 0
    assert db.query(RetrievalHit).count() == 0
    assert db.query(LLMCallLog).count() == 0
    assert db.query(FollowUpReminder).count() == 0
    # A delete audit trail was written.
    audit = db.query(AuditLog).filter(AuditLog.action == "consultation.delete").first()
    assert audit is not None and audit.risk_level == "high"


def test_admin_delete_records_rejects_unknown_resource():
    import pytest
    from fastapi import HTTPException

    db = _sqlite_session()
    with pytest.raises(HTTPException) as exc:
        routes.admin_delete_records(
            resource="users",
            payload={"ids": [1]},
            db=db,
            user=_admin_user(),
        )
    assert exc.value.status_code == 404


def test_admin_delete_records_reports_skipped_missing_ids():
    db = _sqlite_session()
    log = AuditLog(
        actor_external_id="admin-demo",
        actor_role="admin",
        action="system.login",
        resource_type="user_account",
        resource_id="1",
        risk_level="low",
        detail_json="{}",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    result = routes.admin_delete_records(
        resource="audit",
        payload={"ids": [log.id, 99999]},
        db=db,
        user=_admin_user(),
    )

    assert result["deleted"] == 1
    assert result["skipped"] == [99999]
    # The original log is gone, but the delete itself leaves an audit.delete trail.
    assert db.query(AuditLog).filter(AuditLog.action == "audit.delete").count() == 1


def test_admin_dismiss_alert_hides_it_from_payload(monkeypatch):
    import app.api._shared as _shared

    class _Recall:
        def evaluate_recall(self):
            return {"hit_rate": 1.0, "mrr": 1.0, "case_count": 0}

    monkeypatch.setattr(_shared, "store", _Recall())

    db = _sqlite_session()
    user = User(external_id="patient-demo", role="patient", display_name="患者 Demo")
    db.add(user)
    db.commit()
    db.refresh(user)
    consultation = Consultation(
        user_id=user.id,
        patient_external_id="patient-demo",
        agent_type="medication",
        input_text="x",
        sanitized_input="x",
        summary="s",
        risk_level="high",
        sources_json="[]",
        result_json="{}",
        doctor_review_required=True,
        status="review_pending",
    )
    db.add(consultation)
    db.commit()
    db.refresh(consultation)

    before = routes.admin_alerts(db=db, user=_admin_user())
    target = next(a for a in before["alerts"] if a["type"] == "high_risk_consultation")
    assert before["counts"]["total"] >= 1

    result = routes.admin_dismiss_alerts(
        payload={"keys": [target["key"]]},
        db=db,
        user=_admin_user(),
    )
    assert result["dismissed"] == 1

    after = routes.admin_alerts(db=db, user=_admin_user())
    assert all(a["key"] != target["key"] for a in after["alerts"])
    assert after["counts"]["total"] == before["counts"]["total"] - 1
    # Re-dismissing the same key is a no-op.
    again = routes.admin_dismiss_alerts(payload={"keys": [target["key"]]}, db=db, user=_admin_user())
    assert again["dismissed"] == 0
    assert again["skipped"] == [target["key"]]


# ===== Knowledge document upload / extraction =====
def _make_docx_bytes(text: str) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in text.split("\n"))
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body}</w:body></w:document>",
        )
    return buf.getvalue()


def test_extract_text_handles_txt_md_and_docx():
    from app.services.document_extract import extract_text

    assert extract_text("a.txt", "第一段。\n\n第二段。".encode("utf-8")) == "第一段。\n\n第二段。"
    assert "标题" in extract_text("a.md", "# 标题\n\n正文".encode("utf-8"))
    docx = _make_docx_bytes("文档第一行\n文档第二行")
    assert "文档第一行" in extract_text("note.docx", docx)


def test_extract_text_rejects_unknown_and_empty():
    import pytest

    from app.services.document_extract import DocumentExtractionError, extract_text

    with pytest.raises(DocumentExtractionError):
        extract_text("a.exe", b"x")
    with pytest.raises(DocumentExtractionError):
        extract_text("a.txt", b"")


def test_chunk_text_splits_long_text_and_merges_tail():
    from app.services.document_extract import chunk_text

    short = "只有一段"
    assert chunk_text(short) == [short]

    paragraphs = "\n\n".join(f"段落{i} " + "字" * 300 for i in range(6))
    chunks = chunk_text(paragraphs, target_chars=1200)
    assert len(chunks) >= 2
    assert all(len(c) <= 1200 for c in chunks)


def _multipart_request(fields: dict, files: dict):
    """Build a minimal Starlette Request carrying a multipart/form-data body."""
    import asyncio

    from starlette.requests import Request

    boundary = "----testboundary1234"
    parts = []
    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )
    for name, (filename, content) in files.items():
        header = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; "
            f"filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8")
        parts.append(header + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(parts)
    scope = {
        "type": "http",
        "method": "POST",
        "headers": [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode("utf-8")),
            (b"content-length", str(len(body)).encode("utf-8")),
        ],
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def test_admin_upload_knowledge_document_chunks_and_persists():
    import asyncio

    db = _sqlite_session()
    long_text = "\n\n".join(f"第{i}段正文 " + "内容" * 400 for i in range(4))
    req = _multipart_request(
        fields={"category": "health", "source": "测试来源"},
        files={"file": ("guide.txt", long_text.encode("utf-8"))},
    )

    result = asyncio.run(routes.admin_upload_knowledge_document(request=req, db=db, user=_admin_user()))

    assert result["ok"] is True
    assert result["chunks"] >= 2
    assert result["filename"] == "guide.txt"
    created_ids = [doc["id"] for doc in result["documents"]]
    assert len(created_ids) == result["chunks"]
    rows = db.query(KnowledgeDocument).filter(KnowledgeDocument.id.in_(created_ids)).all()
    assert len(rows) == result["chunks"]
    assert all(d.doc_uid.startswith("admin-") for d in rows)
    assert all(d.category == "health" for d in rows)
    # An audit trail records the upload.
    assert db.query(AuditLog).filter(AuditLog.action == "knowledge.upload").count() == 1


def test_admin_upload_knowledge_document_rejects_bad_extension():
    import asyncio

    import pytest
    from fastapi import HTTPException

    db = _sqlite_session()
    req = _multipart_request(fields={}, files={"file": ("malware.exe", b"MZ...")})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(routes.admin_upload_knowledge_document(request=req, db=db, user=_admin_user()))
    assert exc.value.status_code == 400

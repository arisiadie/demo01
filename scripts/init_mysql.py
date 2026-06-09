from __future__ import annotations

import json
import pathlib
import sys

import pymysql


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agents.workflow import MultiAgentWorkflow
from app.rag.store import KnowledgeStore
from app.services.clinical_reference import MEDICATION_RULES, TREATMENT_OPTIONS
from app.services.auth import hash_password
from app.services.llm import LLMClient

HOST = "127.0.0.1"
PORT = 3306
USER = "root"
PASSWORD = "123456"
DATABASE = "oralcare_agentic_rag"
KNOWLEDGE_PATH = ROOT / "data" / "knowledge" / "oral_health_knowledge.json"
SQL_PATH = ROOT / "sql" / "init_oralcare_agentic_rag.sql"


def main() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    conn = pymysql.connect(
        host=HOST,
        port=PORT,
        user=USER,
        password=PASSWORD,
        charset="utf8mb4",
        autocommit=True,
    )
    with conn.cursor() as cursor:
        for statement in [item.strip() for item in sql.split(";") if item.strip()]:
            cursor.execute(statement)
        _seed_knowledge_documents(cursor)
        _seed_medication_rules(cursor)
        _seed_treatment_options(cursor)
        _seed_demo_users(cursor)
        _seed_retention_policies(cursor)
        _seed_privacy_assessment(cursor)
    _seed_workflow_config()
    conn.close()
    print(f"Initialized MySQL database: {DATABASE}")


def _seed_knowledge_documents(cursor) -> None:
    payload = json.loads(KNOWLEDGE_PATH.read_text(encoding="utf-8"))
    cursor.execute(
        "SELECT id FROM knowledge_versions WHERE version = %s",
        (payload["version"],),
    )
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            """
            INSERT INTO knowledge_versions
              (version, title, document_count, retrieval_backend, quality_score, active)
            VALUES (%s, %s, %s, %s, %s, 1)
            """,
            (
                payload["version"],
                payload["title"],
                len(payload["documents"]),
                "local-hybrid",
                0.93,
            ),
        )
        knowledge_version_id = cursor.lastrowid
    else:
        knowledge_version_id = row[0]

    for doc in payload["documents"]:
        cursor.execute(
            """
            INSERT INTO knowledge_documents
              (knowledge_version_id, doc_uid, title, category, source, tags_json, content, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
              knowledge_version_id = VALUES(knowledge_version_id),
              title = VALUES(title),
              category = VALUES(category),
              source = VALUES(source),
              tags_json = VALUES(tags_json),
              content = VALUES(content),
              active = VALUES(active)
            """,
            (
                knowledge_version_id,
                doc["id"],
                doc["title"],
                doc["category"],
                doc["source"],
                json.dumps(doc.get("tags", []), ensure_ascii=False),
                doc["content"],
            ),
        )


def _seed_medication_rules(cursor) -> None:
    cursor.execute(f"USE `{DATABASE}`")
    for rule in MEDICATION_RULES:
        cursor.execute(
            """
            INSERT INTO medication_rules
              (drug_name, aliases_json, category, contraindications_json, interactions_json,
               special_populations_json, dose_note, alcohol_warning, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
              aliases_json = VALUES(aliases_json),
              category = VALUES(category),
              contraindications_json = VALUES(contraindications_json),
              interactions_json = VALUES(interactions_json),
              special_populations_json = VALUES(special_populations_json),
              dose_note = VALUES(dose_note),
              alcohol_warning = VALUES(alcohol_warning),
              active = VALUES(active)
            """,
            (
                rule["drug_name"],
                json.dumps(rule.get("aliases", []), ensure_ascii=False),
                rule["category"],
                json.dumps(rule.get("contraindications", []), ensure_ascii=False),
                json.dumps(rule.get("interactions", []), ensure_ascii=False),
                json.dumps(rule.get("special_populations", {}), ensure_ascii=False),
                rule["dose_note"],
                rule["alcohol_warning"],
            ),
        )


def _seed_treatment_options(cursor) -> None:
    cursor.execute(f"USE `{DATABASE}`")
    for option in TREATMENT_OPTIONS:
        cursor.execute(
            """
            INSERT INTO treatment_options
              (option_name, category, keywords_json, steps_json, duration_note, cost_factors_json,
               advantages_json, disadvantages_json, alternatives_json, active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
              category = VALUES(category),
              keywords_json = VALUES(keywords_json),
              steps_json = VALUES(steps_json),
              duration_note = VALUES(duration_note),
              cost_factors_json = VALUES(cost_factors_json),
              advantages_json = VALUES(advantages_json),
              disadvantages_json = VALUES(disadvantages_json),
              alternatives_json = VALUES(alternatives_json),
              active = VALUES(active)
            """,
            (
                option["option_name"],
                option["category"],
                json.dumps(option.get("keywords", []), ensure_ascii=False),
                json.dumps(option.get("steps", []), ensure_ascii=False),
                option["duration_note"],
                json.dumps(option.get("cost_factors", []), ensure_ascii=False),
                json.dumps(option.get("advantages", []), ensure_ascii=False),
                json.dumps(option.get("disadvantages", []), ensure_ascii=False),
                json.dumps(option.get("alternatives", []), ensure_ascii=False),
            ),
        )


def _seed_demo_users(cursor) -> None:
    cursor.execute(f"USE `{DATABASE}`")
    users = [
        ("patient-demo", "patient", "患者-demo", "patient123"),
        ("doctor-demo", "doctor", "医生-demo", "doctor123"),
        ("admin-demo", "admin", "管理员-demo", "admin123"),
    ]
    for external_id, role, display_name, password in users:
        cursor.execute(
            """
            INSERT INTO users (external_id, role, display_name, password_hash, active)
            VALUES (%s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
              role = VALUES(role),
              display_name = VALUES(display_name),
              password_hash = COALESCE(users.password_hash, VALUES(password_hash)),
              active = 1
            """,
            (external_id, role, display_name, hash_password(password)),
        )


def _seed_retention_policies(cursor) -> None:
    cursor.execute(f"USE `{DATABASE}`")
    policies = [
        ("consultations", 1095, "咨询记录、Agent输出、RAG来源和医生复核记录保留3年。"),
        ("patient_profiles", 1095, "患者档案随咨询服务保留，支持患者发起导出或删除申请。"),
        ("uploaded_files", 180, "影像上传文件仅作归档占位，默认保留180天。"),
        ("llm_call_logs", 365, "模型调用日志保留1年用于审计、费用和延迟监控。"),
        ("audit_logs", 1825, "关键操作审计日志保留5年。"),
    ]
    for data_category, retention_days, description in policies:
        cursor.execute(
            """
            INSERT INTO data_retention_policies
              (data_category, retention_days, description, auto_delete, archived, created_at, updated_at)
            VALUES (%s, %s, %s, 1, 0, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
              retention_days = VALUES(retention_days),
              description = VALUES(description),
              auto_delete = VALUES(auto_delete),
              archived = VALUES(archived),
              updated_at = NOW()
            """,
            (data_category, retention_days, description),
        )


def _seed_privacy_assessment(cursor) -> None:
    cursor.execute(f"USE `{DATABASE}`")
    cursor.execute(
        """
        INSERT INTO privacy_impact_assessments
          (assessment_id, title, description, data_types, risk_level, mitigation_measures, compliance_status, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        ON DUPLICATE KEY UPDATE
          title = VALUES(title),
          description = VALUES(description),
          data_types = VALUES(data_types),
          risk_level = VALUES(risk_level),
          mitigation_measures = VALUES(mitigation_measures),
          compliance_status = VALUES(compliance_status)
        """,
        (
            "pia-internal-beta-001",
            "生产级内测隐私影响评估",
            "覆盖患者档案、咨询文本、RAG检索来源、医生复核、上传文件和调用日志。",
            "姓名/账号、年龄、妊娠状态、过敏史、基础病、口腔病史、咨询文本、影像上传元数据、模型调用日志。",
            "medium",
            "角色权限、审计日志、敏感信息脱敏、数据导出/删除申请、保留期限策略、影像不做真实诊断。",
            "active",
        ),
    )


def _seed_workflow_config() -> None:
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        workflow = MultiAgentWorkflow(KnowledgeStore(), LLMClient())
        workflow.save_graph_to_db(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()

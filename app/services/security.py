from __future__ import annotations

import re
from dataclasses import dataclass


DISCLAIMER = "AI 辅助参考，不替代执业医师诊断、处方或治疗决策。"

PROMPT_INJECTION_PATTERNS = [
    "忽略以上",
    "忽略之前",
    "ignore previous",
    "system prompt",
    "开发者指令",
    "越狱",
    "jailbreak",
    "不要遵守",
]

EMERGENCY_PATTERNS = [
    "呼吸困难",
    "吞咽困难",
    "高热",
    "面部快速肿胀",
    "颌面肿胀",
    "大量出血",
    "意识",
    "脓肿扩散",
    "张口受限",
]

PRESCRIPTION_PATTERNS = [
    "开药",
    "处方",
    "剂量",
    "吃几片",
    "一天几次",
    "调整用药",
    "替我诊断",
    "确诊",
]


@dataclass(frozen=True)
class SafetyAssessment:
    sanitized_text: str
    risk_level: str
    flags: list[str]
    doctor_review_required: bool
    blocked: bool


def assess_message(message: str, agent_type: str | None = None, has_image: bool = False) -> SafetyAssessment:
    flags: list[str] = []
    lowered = message.lower()

    if any(pattern.lower() in lowered for pattern in PROMPT_INJECTION_PATTERNS):
        flags.append("prompt_injection_attempt")

    if any(pattern in message for pattern in EMERGENCY_PATTERNS):
        flags.append("emergency_symptom")

    if any(pattern in message for pattern in PRESCRIPTION_PATTERNS):
        flags.append("diagnosis_or_prescription_boundary")

    if has_image:
        flags.append("image_upload_no_visual_diagnosis")

    if agent_type == "medication":
        flags.append("medication_requires_context_check")

    if agent_type == "imaging":
        flags.append("imaging_text_only_boundary")

    risk_level = "low"
    if "emergency_symptom" in flags:
        risk_level = "high"
    elif flags:
        risk_level = "medium"

    doctor_review_required = risk_level in {"medium", "high"} or agent_type in {"medication", "imaging"}
    blocked = "prompt_injection_attempt" in flags
    return SafetyAssessment(
        sanitized_text=mask_sensitive_data(message),
        risk_level=risk_level,
        flags=flags,
        doctor_review_required=doctor_review_required,
        blocked=blocked,
    )


def mask_sensitive_data(text: str) -> str:
    text = re.sub(r"1[3-9]\d{9}", "1**********", text)
    text = re.sub(r"\d{17}[\dXx]", "******************", text)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "***@***", text)
    return text


def refusal_for_no_evidence() -> dict[str, object]:
    return {
        "summary": "示例知识库没有检索到足够可靠的依据，本次不生成具体医疗建议。",
        "evidence": ["未命中可引用的口腔指南、用药规则或病例样例。"],
        "risk_tips": ["请补充症状、牙位、持续时间、既往病史或报告文本，并由医生复核。"],
        "next_steps": ["如有明显疼痛、肿胀、发热、出血或吞咽呼吸异常，请及时线下就医。"],
    }


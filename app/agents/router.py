from __future__ import annotations

import re
from typing import Any

from app.agents.contracts import AgentPlan
from app.schemas.dto import PatientProfileInput
from app.services.security import EMERGENCY_PATTERNS, PRESCRIPTION_PATTERNS


AGENT_IDS = {"triage", "treatment", "medication", "imaging", "health"}

INTENT_KEYWORDS: dict[str, list[str]] = {
    "triage": [
        "痛",
        "肿",
        "脸肿",
        "面部肿胀",
        "出血",
        "溃疡",
        "发热",
        "流脓",
        "张口受限",
        "牙龈",
        "牙髓炎",
        "冠周炎",
        "挂号",
        "看什么科",
    ],
    "treatment": [
        "治疗",
        "方案",
        "根管",
        "种植",
        "正畸",
        "拔牙",
        "修复",
        "牙冠",
        "洁治",
        "刮治",
    ],
    "medication": [
        "用药",
        "药物",
        "开药",
        "处方",
        "剂量",
        "吃几片",
        "一天几次",
        "阿莫西林",
        "甲硝唑",
        "头孢",
        "布洛芬",
        "对乙酰氨基酚",
        "漱口水",
        "利多卡因",
        "阿替卡因",
        "过敏",
    ],
    "imaging": [
        "影像",
        "报告",
        "x光",
        "X光",
        "全景片",
        "CBCT",
        "根尖片",
        "咬合片",
        "片子",
        "阻生",
        "骨吸收",
    ],
    "health": [
        "刷牙",
        "牙线",
        "窝沟封闭",
        "涂氟",
        "复诊",
        "护理",
        "健康",
        "维护",
        "儿童",
        "换牙",
    ],
}


class AgentRouter:
    def plan(
        self,
        message: str,
        *,
        requested_agent: str | None = None,
        patient_profile: PatientProfileInput | None = None,
        has_image: bool = False,
    ) -> AgentPlan:
        intent_scores = _intent_scores(message)
        risk_signals = _risk_signals(message, patient_profile=patient_profile, has_image=has_image)
        primary_agent = _select_primary_agent(
            intent_scores=intent_scores,
            risk_signals=risk_signals,
            requested_agent=requested_agent,
        )
        secondary_agents = _secondary_agents(primary_agent, intent_scores, risk_signals)
        missing_fields = _missing_fields(
            message,
            primary_agent=primary_agent,
            secondary_agents=secondary_agents,
            patient_profile=patient_profile,
        )
        retrieval_queries = _retrieval_queries(
            message,
            primary_agent=primary_agent,
            secondary_agents=secondary_agents,
            risk_signals=risk_signals,
        )
        return AgentPlan(
            intent=_intent_label(primary_agent, secondary_agents),
            primary_agent=primary_agent,
            secondary_agents=secondary_agents,
            risk_signals=risk_signals,
            retrieval_queries=retrieval_queries,
            missing_fields=missing_fields,
            doctor_review_required=_doctor_review_required(primary_agent, secondary_agents, risk_signals),
        )


def explain_plan(plan: AgentPlan) -> list[str]:
    lines = [
        f"Router 计划：主智能体={plan.primary_agent}，次级智能体={','.join(plan.secondary_agents) or '无'}",
        f"Router 意图：{plan.intent}",
    ]
    if plan.risk_signals:
        lines.append(f"Router 风险信号：{','.join(plan.risk_signals)}")
    if plan.missing_fields:
        lines.append(f"Router 缺失信息：{','.join(plan.missing_fields)}")
    if plan.retrieval_queries:
        lines.append(f"Router 检索计划：{' | '.join(plan.retrieval_queries[:4])}")
    return lines


def _intent_scores(message: str) -> dict[str, int]:
    text = message.lower()
    scores: dict[str, int] = {}
    for agent_id, keywords in INTENT_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in text:
                score += 2 if len(keyword) >= 2 else 1
        scores[agent_id] = score
    return scores


def _select_primary_agent(
    *,
    intent_scores: dict[str, int],
    risk_signals: list[str],
    requested_agent: str | None,
) -> str:
    if requested_agent in AGENT_IDS:
        return requested_agent
    if _has_any(risk_signals, {"emergency_symptom", "acute_swelling"}) or (
        intent_scores.get("triage", 0) > 0 and intent_scores.get("medication", 0) > 0
    ):
        return "triage"
    priority = ["imaging", "medication", "treatment", "triage", "health"]
    best = max(priority, key=lambda agent_id: (intent_scores.get(agent_id, 0), -priority.index(agent_id)))
    return best if intent_scores.get(best, 0) > 0 else "health"


def _secondary_agents(primary_agent: str, intent_scores: dict[str, int], risk_signals: list[str]) -> list[str]:
    secondary: list[str] = []
    ordered = ["triage", "medication", "imaging", "treatment", "health"]
    for agent_id in ordered:
        if agent_id != primary_agent and intent_scores.get(agent_id, 0) > 0:
            secondary.append(agent_id)
    if _has_any(risk_signals, {"medication_request", "prescription_boundary"}) and "medication" != primary_agent:
        secondary.append("medication")
    if _has_any(risk_signals, {"emergency_symptom", "acute_swelling"}) and "triage" != primary_agent:
        secondary.append("triage")
    if primary_agent == "treatment" and "health" not in secondary:
        secondary.append("health")
    if primary_agent == "imaging" and "treatment" not in secondary:
        secondary.append("treatment")
    return _dedupe([agent for agent in secondary if agent in AGENT_IDS])


def _risk_signals(
    message: str,
    *,
    patient_profile: PatientProfileInput | None,
    has_image: bool,
) -> list[str]:
    signals: list[str] = []
    if any(pattern in message for pattern in EMERGENCY_PATTERNS):
        signals.append("emergency_symptom")
    if _contains(message, ["脸肿", "面部肿胀", "颌面肿胀", "快速肿胀"]):
        signals.append("acute_swelling")
    if any(pattern in message for pattern in PRESCRIPTION_PATTERNS):
        signals.append("prescription_boundary")
    if _contains(message, ["开药", "用药", "吃药", "吃头孢", "吃阿莫西林", "头孢", "阿莫西林", "甲硝唑", "布洛芬"]):
        signals.append("medication_request")
    if _contains(message, ["过敏"]) or (patient_profile and patient_profile.allergies):
        signals.append("allergy_context")
    profile_text = _profile_text(patient_profile)
    if _contains(f"{message} {profile_text}", ["孕", "妊娠", "备孕", "哺乳"]):
        signals.append("pregnancy_context")
    if has_image:
        signals.append("image_upload")
    if _contains(message, ["确诊", "替我诊断", "诊断一下"]):
        signals.append("diagnosis_boundary")
    return _dedupe(signals)


def _missing_fields(
    message: str,
    *,
    primary_agent: str,
    secondary_agents: list[str],
    patient_profile: PatientProfileInput | None,
) -> list[str]:
    fields: list[str] = []
    involved = {primary_agent, *secondary_agents}
    if "triage" in involved:
        if not _has_duration(message):
            fields.append("症状持续时间")
        if not _contains(message, ["左", "右", "上", "下", "前牙", "后牙", "智齿"]) and not re.search(r"\d{1,2}\s*(号牙|牙)", message):
            fields.append("牙位/区域")
        if not _contains(message, ["冷热", "咬合", "夜间", "自发", "刷牙", "肿", "发热", "流脓"]):
            fields.append("诱因和伴随症状")
    if "medication" in involved:
        if not (patient_profile and patient_profile.age is not None) and not re.search(r"\d+\s*岁", message):
            fields.append("年龄")
        if not _contains(f"{message} {_profile_text(patient_profile)}", ["过敏", "无过敏", "不过敏"]):
            fields.append("过敏史")
        if not _contains(f"{message} {_profile_text(patient_profile)}", ["孕", "妊娠", "备孕", "哺乳", "未孕", "男性", "男"]):
            fields.append("妊娠/哺乳状态")
        if not _contains(f"{message} {_profile_text(patient_profile)}", ["基础病", "糖尿病", "高血压", "心脏病", "肝", "肾", "无基础病"]):
            fields.append("基础病/肝肾功能")
    if "imaging" in involved and not _contains(message, ["提示", "报告", "所见", "结论"]):
        fields.append("影像报告文本")
    return _dedupe(fields)


def _retrieval_queries(
    message: str,
    *,
    primary_agent: str,
    secondary_agents: list[str],
    risk_signals: list[str],
) -> list[str]:
    queries = [message]
    involved = [primary_agent] + secondary_agents
    for agent_id in involved:
        if agent_id == "triage":
            queries.append(f"{message} 牙位 持续时间 伴随症状 急症 分诊")
        elif agent_id == "medication":
            queries.append(f"{message} 年龄 过敏史 妊娠 基础病 剂量 相互作用 用药边界")
        elif agent_id == "imaging":
            queries.append(f"{message} 影像报告 文本解读 全景片 CBCT 根尖片")
        elif agent_id == "treatment":
            queries.append(f"{message} 治疗方案 步骤 风险 替代方案 复诊")
        elif agent_id == "health":
            queries.append(f"{message} 口腔健康管理 护理计划 复诊提醒")
    if _has_any(risk_signals, {"emergency_symptom", "acute_swelling"}):
        queries.append(f"{message} 牙源性感染 面部肿胀 急诊 风险")
    if _has_any(risk_signals, {"medication_request", "prescription_boundary", "allergy_context"}):
        queries.append(f"{message} 抗生素 过敏 禁忌 处方边界 医生复核")
    return _dedupe(queries)[:8]


def _doctor_review_required(primary_agent: str, secondary_agents: list[str], risk_signals: list[str]) -> bool:
    if primary_agent in {"medication", "imaging"} or {"medication", "imaging"} & set(secondary_agents):
        return True
    return _has_any(
        risk_signals,
        {"emergency_symptom", "acute_swelling", "prescription_boundary", "diagnosis_boundary", "image_upload"},
    )


def _intent_label(primary_agent: str, secondary_agents: list[str]) -> str:
    labels = {
        "triage": "症状预问诊",
        "treatment": "诊疗方案解读",
        "medication": "用药安全审查",
        "imaging": "影像报告解读",
        "health": "健康管理",
    }
    parts = [labels.get(primary_agent, primary_agent)]
    parts.extend(labels.get(agent_id, agent_id) for agent_id in secondary_agents)
    return " + ".join(_dedupe(parts))


def _contains(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def _has_any(values: list[str], expected: set[str]) -> bool:
    return bool(set(values) & expected)


def _has_duration(message: str) -> bool:
    return bool(re.search(r"\d+\s*(天|日|周|个月|月|年|小时)", message)) or _contains(message, ["今天", "昨天", "长期", "反复"])


def _profile_text(profile: PatientProfileInput | None) -> str:
    if profile is None:
        return ""
    values: list[Any] = [
        profile.age,
        profile.sex,
        profile.pregnancy_status,
        profile.allergies,
        profile.conditions,
        profile.oral_history,
    ]
    return " ".join(str(value) for value in values if value is not None)


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result

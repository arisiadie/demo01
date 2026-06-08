from __future__ import annotations

import re
from typing import Any

from app.services.clinical_reference import medication_rules_for_text, treatment_options_for_text


def structured_output_for_agent(
    agent_id: str,
    message: str,
    profile: Any | None = None,
    *,
    has_image: bool = False,
) -> dict[str, Any]:
    if agent_id == "triage":
        return {"triage_report": build_triage_report(message, profile)}
    if agent_id == "treatment":
        return {"treatment_comparison": build_treatment_comparison(message)}
    if agent_id == "medication":
        return {"medication_check": build_medication_check(message, profile)}
    if agent_id == "imaging":
        return {"imaging_report_analysis": build_imaging_report_analysis(message, profile, has_image=has_image)}
    if agent_id == "health":
        return {"health_plan": build_health_plan(message, profile)}
    return {}


def build_triage_report(message: str, profile: Any | None = None) -> dict[str, Any]:
    triggers = _matched_items(message, ["冷热刺激", "热刺激", "冷刺激", "咬合痛", "咀嚼痛", "夜间痛", "自发痛", "刷牙出血"])
    accompanying = _matched_items(
        message,
        ["肿胀", "面部肿胀", "发热", "流脓", "张口受限", "吞咽困难", "呼吸困难", "牙龈出血", "牙齿松动", "大量出血"],
    )
    tooth_position = _extract_tooth_position(message)
    duration_text = _extract_duration(message)
    pain_character = _extract_pain_character(message)
    suspected_conditions = _suspected_conditions(message, triggers, accompanying)
    red_flags = _triage_red_flags(message, accompanying)
    urgency_level = _triage_urgency(message, accompanying, red_flags)
    recommended_department = _recommended_department(message, suspected_conditions, urgency_level)
    information_gaps = _triage_information_gaps(tooth_position, duration_text, pain_character, triggers, accompanying, profile)
    severity_score = _triage_severity_score(urgency_level, red_flags, triggers, accompanying)
    report = {
        "tooth_position": tooth_position,
        "duration_text": duration_text,
        "pain_character": pain_character,
        "triggers": triggers,
        "accompanying_symptoms": accompanying,
        "suspected_conditions": suspected_conditions,
        "red_flags": red_flags,
        "information_gaps": information_gaps,
        "urgency_level": urgency_level,
        "urgency_label": {"urgent": "急诊/尽快", "soon": "近期就诊", "routine": "常规预约"}[urgency_level],
        "severity_score": severity_score,
        "recommended_department": recommended_department,
        "department_reason": _department_reason(recommended_department, suspected_conditions, red_flags),
        "care_pathway": {
            "timeframe": {"urgent": "立即线下急诊", "soon": "24-48小时内尽快就诊", "routine": "按常规预约复诊"}[urgency_level],
            "first_contact": recommended_department,
            "bring_materials": ["既往病历", "用药和过敏史", "已有影像或检查报告"],
        },
        "suggested_questions": _triage_followup_questions(information_gaps, urgency_level),
        "doctor_review_required": urgency_level in {"urgent", "soon"},
        "patient_context": _patient_context(profile),
    }
    return report


def build_medication_check(message: str, profile: Any | None = None) -> dict[str, Any]:
    rules = medication_rules_for_text(message)
    dose_request_detected = _contains(message, ["吃几片", "一天几次", "剂量", "用量", "最大剂量", "多少毫克", "mg"])
    prescription_boundary_detected = _contains(message, ["开药", "处方", "替我开", "直接给我用药方案"])
    checked_drugs = [
        {
            "drug_name": rule["drug_name"],
            "category": rule["category"],
            "dose_note": rule["dose_note"],
            "alcohol_warning": rule["alcohol_warning"],
            "max_dose_boundary": _max_dose_boundary(rule["drug_name"]),
            "rule_contraindications": list(rule.get("contraindications", [])),
            "rule_interactions": list(rule.get("interactions", [])),
            "special_populations": dict(rule.get("special_populations", {})),
        }
        for rule in rules
    ]
    weight_kg = _extract_weight_kg(message)
    profile_text = _profile_notes(profile)
    combined_text = f"{message} {profile_text}"
    age = _profile_int(profile, "age")
    risk_points: list[str] = []
    contraindications: list[str] = []
    interactions: list[str] = []
    patient_specific_alerts = _patient_specific_medication_alerts(combined_text, profile, age, weight_kg)

    if not rules:
        risk_points.append("未识别到内测药物规则库中的明确药名，无法完成合规核查。")
    if dose_request_detected:
        risk_points.append("用户提出剂量/用量问题：平台不自动给出处方剂量，仅提示需医生或药师按年龄、体重、肝肾功能核算。")
    if prescription_boundary_detected:
        risk_points.append("用户涉及处方边界：平台不自动开具处方或替代医生处方。")

    for rule in rules:
        drug_name = rule["drug_name"]
        if drug_name == "阿莫西林" and _contains(combined_text, ["青霉素过敏", "β-内酰胺过敏", "头孢过敏"]):
            contraindications.append(f"{drug_name}：用户提示青霉素/β-内酰胺相关过敏史，规则建议禁用并医生复核。")
        if drug_name == "头孢克洛" and _contains(combined_text, ["头孢过敏", "严重青霉素过敏", "β-内酰胺过敏"]):
            contraindications.append(f"{drug_name}：头孢或严重β-内酰胺过敏史需禁用或由医生评估交叉过敏风险。")
        if drug_name == "布洛芬" and _contains(combined_text, ["胃溃疡", "肾病", "肾功能", "哮喘", "抗凝", "华法林", "妊娠晚期"]):
            contraindications.append(f"{drug_name}：存在消化道、肾功能、哮喘、抗凝或妊娠相关风险线索，需医生复核。")
        if drug_name == "对乙酰氨基酚" and _contains(combined_text, ["肝病", "肝功能", "长期饮酒", "酒精"]):
            contraindications.append(f"{drug_name}：肝功能或酒精相关风险需医生复核，避免重复用药。")
        if _contains(combined_text, ["孕", "妊娠", "备孕", "哺乳"]):
            risk_points.append(f"{drug_name}：妊娠/备孕/哺乳状态需由医生评估获益与风险。")
        if age is not None and (age < 12 or age >= 65):
            risk_points.append(f"{drug_name}：年龄 {age} 岁属于需谨慎核查剂量和禁忌的人群。")
        if weight_kg is not None and drug_name in {"利多卡因", "阿替卡因", "阿莫西林", "头孢克洛"}:
            risk_points.append(f"{drug_name}：已识别体重 {weight_kg:g} kg，需按体重或最大安全剂量由医生/药师核算。")
        if _contains(combined_text, ["肾病", "肾功能", "肾衰", "透析"]) and drug_name in {"阿莫西林", "头孢克洛", "布洛芬"}:
            contraindications.append(f"{drug_name}：肾功能异常会影响给药安全或剂量调整，需医生复核。")
        if _contains(combined_text, ["肝病", "肝功能", "肝硬化"]) and drug_name in {"对乙酰氨基酚", "甲硝唑", "利多卡因"}:
            contraindications.append(f"{drug_name}：肝功能异常会增加药物蓄积或肝损伤风险，需医生复核。")
        if drug_name in {"利多卡因", "阿替卡因"} and _contains(combined_text, ["心脏病", "高血压", "心律失常", "甲亢", "心功能"]):
            contraindications.append(f"{drug_name}：心血管或甲亢相关病史会影响局麻药及肾上腺素制剂选择，需医生现场评估。")
        if drug_name in {"米诺环素凝胶"} and _contains(combined_text, ["儿童", "孕", "妊娠", "哺乳"]):
            contraindications.append(f"{drug_name}：儿童、妊娠或哺乳期存在特殊人群风险，不建议自行使用。")
        if drug_name in {"阿莫西林", "甲硝唑", "头孢克洛"} and _contains(combined_text, ["糖尿病"]):
            risk_points.append(f"{drug_name}：糖尿病患者口腔感染和创口恢复需结合血糖控制情况由医生评估。")
        risk_points.append(f"{drug_name}：{rule['dose_note']}")
        if rule.get("alcohol_warning"):
            risk_points.append(f"{drug_name}：{rule['alcohol_warning']}")

    drug_names = {rule["drug_name"] for rule in rules}
    if {"阿莫西林", "甲硝唑"} <= drug_names:
        interactions.append("阿莫西林与甲硝唑可见于部分口腔感染联合方案，但必须由医生判断适应证、疗程和剂量。")
    if "甲硝唑" in drug_names and _contains(combined_text, ["酒", "饮酒", "喝酒", "酒精"]):
        interactions.append("甲硝唑与酒精同用存在双硫仑样反应风险。")
    if drug_names & {"布洛芬", "甲硝唑", "阿莫西林"} and _contains(combined_text, ["华法林", "抗凝", "阿司匹林", "氯吡格雷"]):
        interactions.append("与抗凝/抗血小板药同用可能增加出血或药效波动风险，需医生或药师复核。")
    if drug_names & {"利多卡因", "阿替卡因"} and _contains(combined_text, ["β受体阻滞剂", "普萘洛尔", "美托洛尔", "抗心律失常"]):
        interactions.append("局麻药与部分心血管药物同用需关注心率、血压和心律风险。")

    missing_context = _missing_medication_context(message, profile, weight_kg)
    if missing_context:
        risk_points.append(f"用药审查缺少关键信息：{'、'.join(missing_context)}。")
    compliance_summary = _medication_summary(checked_drugs, contraindications, interactions, risk_points)
    context_completeness = _context_completeness(missing_context)
    return {
        "checked_drugs": checked_drugs,
        "drug_decisions": _drug_decisions(checked_drugs, contraindications, interactions, risk_points),
        "risk_points": _dedupe(risk_points),
        "contraindications": _dedupe(contraindications),
        "interactions": _dedupe(interactions),
        "patient_specific_alerts": patient_specific_alerts,
        "compliance_summary": compliance_summary,
        "review_required": True,
        "required_context": _required_medication_context(),
        "missing_context": missing_context,
        "context_completeness": context_completeness,
        "boundary_violations": _medication_boundary_violations(dose_request_detected, prescription_boundary_detected, message),
        "dose_request_detected": dose_request_detected,
        "clinical_review_items": [
            "确认药物适应证是否来自医生诊断",
            "核对过敏史、妊娠/哺乳、儿童/老人等特殊人群",
            "核对肝肾功能、心血管病、消化道出血和抗凝/抗血小板药物",
            "涉及抗菌药、局麻药或明确剂量请求时由医生/药师复核",
        ],
        "triage_needed": _contains(message, ["牙痛", "肿胀", "发热", "流脓", "张口受限"]),
        "weight_kg": weight_kg,
        "dose_boundary_note": "内测系统不输出自动处方剂量；涉及儿童、老人、肝肾功能异常、局麻药和抗菌药时必须医生/药师复核。",
        "patient_context": _patient_context(profile),
    }


def build_treatment_comparison(message: str) -> dict[str, Any]:
    options = treatment_options_for_text(message)
    if not options:
        options = treatment_options_for_text("根管 种植 正畸 洁治 烤瓷冠")[:3]
    comparison = []
    for option in options:
        option_name = option["option_name"]
        comparison.append(
            {
                "option_name": option_name,
                "category": option["category"],
                "main_steps": option["steps"],
                "duration_note": option["duration_note"],
                "cost_factors": option["cost_factors"],
                "advantages": option["advantages"],
                "disadvantages": option["disadvantages"],
                "alternatives": option["alternatives"],
                "indication_check": _treatment_indication_check(option_name, message),
                "key_risks": _treatment_key_risks(option_name),
                "review_questions": _treatment_review_questions(option_name),
                "maintenance_requirements": _treatment_maintenance_requirements(option_name),
            }
        )
    option_names = [item["option_name"] for item in comparison]
    complex_flags = _treatment_complex_flags(message, option_names)
    if len(option_names) == 1:
        recommendation = f"已匹配{option_names[0]}，建议面诊确认适应证、牙位、复诊次数、费用构成和替代方案。"
    else:
        recommendation = f"已匹配{len(option_names)}个相关方案：{'、'.join(option_names)}；需结合检查和影像由医生确定优先方案。"
    return {
        "matched_options": option_names,
        "comparison": comparison,
        "clinical_decision_points": _clinical_decision_points(option_names, message),
        "required_pre_checks": _required_treatment_pre_checks(option_names),
        "patient_questions": _patient_treatment_questions(option_names),
        "complexity_flags": complex_flags,
        "recommendation_note": recommendation,
        "doctor_review_required": bool(complex_flags),
        "risk_level": "medium" if complex_flags else "low",
    }


def build_imaging_report_analysis(message: str, profile: Any | None = None, *, has_image: bool = False) -> dict[str, Any]:
    modality = _imaging_modality(message)
    findings = _imaging_findings(message)
    red_flags = _imaging_red_flags(message)
    interpreted_terms = [_imaging_term_explanation(term) for term in findings]
    missing_report_parts = [
        label
        for label, keywords in {
            "检查类型": ["全景片", "CBCT", "根尖片", "头颅侧位片", "咬翼片"],
            "报告所见": ["所见", "提示", "见", "显示"],
            "报告结论": ["结论", "印象", "建议"],
        }.items()
        if not _contains(message, keywords)
    ]
    return {
        "modality": modality,
        "report_text_detected": bool(message.strip()),
        "text_findings": findings,
        "interpreted_terms": interpreted_terms,
        "red_flags": red_flags,
        "clinical_correlation_needed": [
            "口内检查",
            "牙髓活力测试",
            "牙周探诊",
            "疼痛和肿胀病史",
        ],
        "image_handling": {
            "image_uploaded": bool(has_image),
            "preview_or_archive_only": bool(has_image),
            "visual_diagnosis_performed": False,
            "boundary_note": "图片仅用于预览/归档占位；本系统不根据图片作真实影像诊断。",
        },
        "missing_report_parts": missing_report_parts,
        "recommended_departments": _imaging_departments(findings, message),
        "recommended_next_steps": _imaging_next_steps(findings, red_flags),
        "limitations": [
            "仅解释用户提供的报告文本和术语。",
            "不能替代放射科/口腔医生对原始影像的阅片诊断。",
        ],
        "doctor_review_required": True,
        "risk_level": "high" if red_flags else "medium",
        "summary_note": _imaging_summary_note(modality, findings, red_flags),
        "patient_context": _patient_context(profile),
    }


def build_health_plan(message: str, profile: Any | None = None) -> dict[str, Any]:
    segment = _health_segment(message, profile)
    focus_areas = _health_focus_areas(message, profile, segment)
    risk_level = _health_risk_level(message, profile, focus_areas)
    return {
        "patient_segment": segment,
        "focus_areas": focus_areas,
        "daily_actions": _health_daily_actions(segment, focus_areas),
        "weekly_actions": _health_weekly_actions(segment, focus_areas),
        "professional_schedule": _health_professional_schedule(segment, focus_areas),
        "home_monitoring": _health_home_monitoring(focus_areas),
        "reminder_candidates": _health_reminder_candidates(segment, focus_areas),
        "risk_tips": _health_risk_tips(segment, focus_areas),
        "next_steps": _health_next_steps(segment, focus_areas),
        "plan_summary": _health_plan_summary(segment, focus_areas),
        "doctor_review_required": risk_level != "low",
        "risk_level": risk_level,
        "personalization_inputs": {
            "message_keywords": _matched_items(message, ["儿童", "换牙", "窝沟封闭", "涂氟", "牙周", "种植", "正畸", "孕", "糖尿病", "拔牙", "根管"]),
            "patient_context": _patient_context(profile),
        },
    }


def _contains(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text.lower() for keyword in keywords)


def _matched_items(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


def _profile_value(profile: Any | None, key: str) -> Any:
    if profile is None:
        return None
    if isinstance(profile, dict):
        return profile.get(key)
    return getattr(profile, key, None)


def _profile_int(profile: Any | None, key: str) -> int | None:
    value = _profile_value(profile, key)
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _profile_notes(profile: Any | None) -> str:
    if profile is None:
        return ""
    notes = []
    age = _profile_value(profile, "age")
    if age is not None:
        notes.append(f"年龄 {age} 岁")
    pregnancy_status = _profile_value(profile, "pregnancy_status")
    if pregnancy_status:
        notes.append(f"妊娠状态：{pregnancy_status}")
    allergies = _profile_value(profile, "allergies")
    if allergies:
        notes.append(f"过敏史：{allergies}")
    conditions = _profile_value(profile, "conditions")
    if conditions:
        notes.append(f"基础病：{conditions}")
    oral_history = _profile_value(profile, "oral_history")
    if oral_history:
        notes.append(f"口腔史：{oral_history}")
    return "；".join(notes)


def _patient_context(profile: Any | None) -> dict[str, Any]:
    if profile is None:
        return {}
    return {
        "age": _profile_value(profile, "age"),
        "sex": _profile_value(profile, "sex"),
        "pregnancy_status": _profile_value(profile, "pregnancy_status"),
        "allergies": _profile_value(profile, "allergies"),
        "conditions": _profile_value(profile, "conditions"),
        "oral_history": _profile_value(profile, "oral_history"),
    }


def _extract_tooth_position(message: str) -> str:
    patterns = [
        r"[左右][上下]后牙",
        r"[左右][上下]智齿",
        r"[左右]?[上下][前后]?[牙齿]?",
        r"\d{1,2}\s*(号牙|牙)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message)
        if match:
            value = match.group(0).strip()
            if value:
                return value
    return "未明确"


def _extract_duration(message: str) -> str:
    match = re.search(r"(\d+\s*(天|日|周|个月|月|年|小时))", message)
    if match:
        return match.group(1).replace(" ", "")
    if "长期" in message or "反复" in message:
        return "长期/反复"
    if "今天" in message:
        return "今天"
    if "昨" in message:
        return "约1天"
    return "未明确"


def _extract_pain_character(message: str) -> str:
    characters = _matched_items(message, ["自发痛", "夜间痛", "冷热刺激痛", "咬合痛", "胀痛", "跳痛", "隐痛", "酸痛", "剧痛"])
    return "、".join(characters) if characters else "未明确"


def _suspected_conditions(message: str, triggers: list[str], accompanying: list[str]) -> list[dict[str, str]]:
    conditions: list[dict[str, str]] = []
    if _contains(message, ["冷热刺激", "夜间痛", "自发痛", "牙髓"]) or {"冷热刺激", "夜间痛"} & set(triggers):
        conditions.append({"name": "牙髓炎/深龋相关疼痛", "basis": "冷热刺激痛、自发痛或夜间痛需要排查牙髓受累。"})
    if _contains(message, ["咬合痛", "根尖", "肿胀", "流脓"]):
        conditions.append({"name": "根尖周炎或急性炎症", "basis": "咬合痛、肿胀、流脓或根尖提示需结合影像和叩诊。"})
    if _contains(message, ["牙龈出血", "牙齿松动", "牙周"]):
        conditions.append({"name": "牙龈炎/牙周炎", "basis": "出血、松动或牙周描述需要牙周检查。"})
    if _contains(message, ["智齿", "冠周", "张口受限"]):
        conditions.append({"name": "智齿冠周炎/阻生齿相关问题", "basis": "智齿区域不适或张口受限需评估冠周炎和阻生情况。"})
    if _contains(message, ["口腔溃疡", "白斑", "两周不愈", "不规则"]):
        conditions.append({"name": "口腔黏膜病变待查", "basis": "长期不愈或形态异常的黏膜病变需专科检查。"})
    if not conditions:
        conditions.append({"name": "口腔常见疼痛或炎症待查", "basis": "当前信息不足，需补充牙位、诱因、持续时间和口内检查。"})
    return conditions


def _triage_red_flags(message: str, accompanying: list[str]) -> list[dict[str, str]]:
    red_flags: list[dict[str, str]] = []
    mapping = {
        "呼吸困难": "可能存在颌面部感染扩散或全身急症风险。",
        "吞咽困难": "可能提示颌面部感染扩散，需线下急诊评估。",
        "高热": "感染相关全身反应风险升高。",
        "面部快速肿胀": "颌面部感染进展风险，需尽快就医。",
        "大量出血": "出血控制和全身情况需线下处理。",
        "张口受限": "智齿冠周炎、间隙感染或颞下颌问题需评估。",
        "流脓": "提示感染灶，需医生处理病因。",
    }
    text = f"{message} {' '.join(accompanying)}"
    for keyword, reason in mapping.items():
        if keyword in text:
            red_flags.append({"signal": keyword, "reason": reason})
    if "肿胀" in text and not any(item["signal"] == "面部快速肿胀" for item in red_flags):
        red_flags.append({"signal": "肿胀", "reason": "肿胀可能提示急性炎症或感染，需要结合发热、张口和吞咽情况判断。"})
    return red_flags


def _triage_urgency(message: str, accompanying: list[str], red_flags: list[dict[str, str]]) -> str:
    red_flag_text = " ".join(item["signal"] for item in red_flags)
    if _contains(message, ["呼吸困难", "吞咽困难", "高热", "面部快速肿胀", "大量出血"]) or _contains(red_flag_text, ["呼吸困难", "吞咽困难", "高热", "面部快速肿胀", "大量出血"]):
        return "urgent"
    if _contains(message, ["夜间痛", "自发痛", "肿胀", "发热", "张口受限", "流脓", "松动"]) or accompanying or red_flags:
        return "soon"
    return "routine"


def _recommended_department(message: str, suspected_conditions: list[dict[str, str]], urgency_level: str) -> str:
    if urgency_level == "urgent":
        return "口腔急诊/颌面外科"
    names = " ".join(item["name"] for item in suspected_conditions)
    if "牙髓" in names or "根尖" in names:
        return "牙体牙髓科"
    if "牙周" in names:
        return "牙周科"
    if "智齿" in names or "阻生" in names:
        return "口腔颌面外科"
    if "黏膜" in names:
        return "口腔黏膜科"
    if _contains(message, ["儿童", "乳牙", "换牙"]):
        return "儿童口腔科"
    return "口腔全科/综合科"


def _triage_information_gaps(
    tooth_position: str,
    duration_text: str,
    pain_character: str,
    triggers: list[str],
    accompanying: list[str],
    profile: Any | None,
) -> list[str]:
    gaps = []
    if tooth_position == "未明确":
        gaps.append("牙位/区域")
    if duration_text == "未明确":
        gaps.append("持续时间")
    if pain_character == "未明确" and not triggers:
        gaps.append("疼痛性质和诱因")
    if not accompanying:
        gaps.append("是否伴随肿胀、发热、流脓、张口或吞咽异常")
    if not _profile_notes(profile):
        gaps.append("年龄、过敏史、基础病和既往口腔治疗史")
    return gaps


def _triage_severity_score(urgency_level: str, red_flags: list[dict[str, str]], triggers: list[str], accompanying: list[str]) -> int:
    base = {"routine": 25, "soon": 60, "urgent": 90}[urgency_level]
    score = base + min(len(red_flags) * 5 + len(accompanying) * 2 + len(triggers), 10)
    return min(score, 100)


def _department_reason(department: str, suspected_conditions: list[dict[str, str]], red_flags: list[dict[str, str]]) -> str:
    condition_names = "、".join(item["name"] for item in suspected_conditions)
    if red_flags:
        return f"存在{len(red_flags)}项高风险信号，建议由{department}优先排查；当前疑似方向：{condition_names}。"
    return f"根据症状线索，当前疑似方向为{condition_names}，建议先到{department}评估。"


def _triage_followup_questions(information_gaps: list[str], urgency_level: str) -> list[str]:
    questions = [f"请补充：{item}。" for item in information_gaps[:4]]
    if urgency_level == "urgent":
        questions.insert(0, "当前是否正在出现呼吸、吞咽困难或高热？如有请立即线下急诊。")
    return questions or ["请确认是否已有影像报告、医生诊断或正在使用药物。"]


def _required_medication_context() -> list[str]:
    return ["年龄", "体重", "妊娠/哺乳状态", "过敏史", "肝肾功能", "基础病", "当前药物", "医生开具剂量"]


def _missing_medication_context(message: str, profile: Any | None, weight_kg: float | None) -> list[str]:
    missing = []
    profile_text = _profile_notes(profile)
    combined_text = f"{message} {profile_text}"
    if _profile_int(profile, "age") is None and not re.search(r"\d+\s*岁", message):
        missing.append("年龄")
    if weight_kg is None:
        missing.append("体重")
    if not _contains(combined_text, ["孕", "妊娠", "备孕", "哺乳", "未孕", "无妊娠", "男性", "男"]):
        missing.append("妊娠/哺乳状态")
    if not _contains(combined_text, ["过敏", "不过敏", "无过敏"]):
        missing.append("过敏史")
    if not _contains(combined_text, ["肝", "肾", "透析", "肝肾正常", "肝肾功能正常"]):
        missing.append("肝肾功能")
    if not _contains(combined_text, ["基础病", "糖尿病", "高血压", "心脏病", "哮喘", "胃溃疡", "无基础病"]):
        missing.append("基础病")
    if not _contains(combined_text, ["正在用", "合用", "华法林", "阿司匹林", "氯吡格雷", "抗凝", "无其他药"]):
        missing.append("当前药物")
    return missing


def _extract_weight_kg(message: str) -> float | None:
    match = re.search(r"(?:体重|重)?\s*(\d+(?:\.\d+)?)\s*(kg|公斤|千克)", message, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _max_dose_boundary(drug_name: str) -> str:
    boundaries = {
        "利多卡因": "需按体重、浓度、是否含肾上腺素和操作范围核定最大安全剂量。",
        "阿替卡因": "需按体重和含肾上腺素制剂情况核定最大安全剂量。",
        "布洛芬": "需避免长期或超量使用，儿童、老人、肾病和胃肠道风险人群需复核。",
        "对乙酰氨基酚": "需避免与复方感冒药重复叠加，肝病或饮酒者需复核。",
        "阿莫西林": "需按感染适应证、年龄/体重、肾功能和处方疗程核定。",
        "头孢克洛": "需按感染适应证、年龄/体重、肾功能和过敏史核定。",
    }
    return boundaries.get(drug_name, "需结合药品说明书和医生处方核定剂量边界。")


def _patient_specific_medication_alerts(combined_text: str, profile: Any | None, age: int | None, weight_kg: float | None) -> list[dict[str, str]]:
    alerts = []
    if age is not None and age < 12:
        alerts.append({"type": "child", "message": f"年龄 {age} 岁：儿童用药需按体重和药品说明书由医生/药师核算。"})
    if age is not None and age >= 65:
        alerts.append({"type": "elderly", "message": f"年龄 {age} 岁：老人需重点核查肝肾功能、合并用药和跌倒/出血风险。"})
    if weight_kg is not None:
        alerts.append({"type": "weight", "message": f"体重 {weight_kg:g} kg：涉及儿童、抗菌药或局麻药时需按体重核算。"})
    if _contains(combined_text, ["过敏"]):
        alerts.append({"type": "allergy", "message": "已出现过敏史线索，需核对具体药物类别和反应严重程度。"})
    if _contains(combined_text, ["孕", "妊娠", "备孕", "哺乳"]):
        alerts.append({"type": "pregnancy", "message": "妊娠/备孕/哺乳状态下需由医生评估获益与风险。"})
    if _contains(combined_text, ["肝", "肾", "心脏病", "高血压", "糖尿病", "哮喘", "胃溃疡", "抗凝"]):
        alerts.append({"type": "comorbidity", "message": "基础病或合并用药会影响药物选择、剂量和不良反应风险。"})
    return alerts


def _context_completeness(missing_context: list[str]) -> dict[str, Any]:
    required = _required_medication_context()
    provided = [item for item in required if item not in missing_context]
    completion_rate = round(len(provided) / len(required), 3)
    status = "complete" if not missing_context else "partial" if completion_rate >= 0.5 else "insufficient"
    return {
        "required": required,
        "provided": provided,
        "missing": missing_context,
        "completion_rate": completion_rate,
        "status": status,
    }


def _medication_boundary_violations(dose_request: bool, prescription_request: bool, message: str) -> list[dict[str, str]]:
    violations = []
    if dose_request:
        violations.append({"code": "dose_request", "message": "用户请求具体剂量/用量，需医生或药师复核，AI 不直接给出个体化剂量。"})
    if prescription_request:
        violations.append({"code": "prescription_request", "message": "用户请求处方或开药，平台不得替代执业医师开具处方。"})
    if _contains(message, ["确诊", "诊断"]):
        violations.append({"code": "diagnosis_request", "message": "诊断需结合面诊和检查，平台只提供辅助解释。"})
    return violations


def _drug_decisions(
    checked_drugs: list[dict[str, Any]],
    contraindications: list[str],
    interactions: list[str],
    risk_points: list[str],
) -> list[dict[str, Any]]:
    decisions = []
    joined_contra = " ".join(contraindications)
    joined_interactions = " ".join(interactions)
    joined_risk = " ".join(risk_points)
    for drug in checked_drugs:
        name = drug["drug_name"]
        drug_contra = [item for item in contraindications if name in item]
        drug_interactions = [item for item in interactions if name in item or name in joined_interactions]
        drug_risks = [item for item in risk_points if name in item]
        if name in joined_contra:
            status = "contraindicated"
            decision = "暂不建议自行使用"
        elif drug_interactions or drug_risks:
            status = "review_required"
            decision = "需医生/药师复核后使用"
        else:
            status = "no_rule_conflict_detected"
            decision = "未发现规则库明确冲突，但仍以医生处方为准"
        decisions.append(
            {
                "drug_name": name,
                "status": status,
                "decision": decision,
                "rationale": _dedupe(drug_contra + drug_interactions + drug_risks)[:5],
            }
        )
    return decisions


def _medication_summary(
    checked_drugs: list[dict[str, Any]],
    contraindications: list[str],
    interactions: list[str],
    risk_points: list[str],
) -> str:
    if not checked_drugs:
        return "未识别到可核查药名，建议补充完整药名、剂量、年龄、过敏史和基础病后由医生/药师复核。"
    names = "、".join(item["drug_name"] for item in checked_drugs)
    if contraindications:
        return f"已核查{names}，发现明确禁忌或高风险线索，暂不建议自行使用，需医生/药师复核。"
    if interactions:
        return f"已核查{names}，发现相互作用或联合用药注意事项，需医生/药师确认适应证和剂量。"
    if risk_points:
        return f"已核查{names}，未发现规则库中的明确禁忌，但仍需确认剂量、疗程、过敏史和基础病。"
    return f"已核查{names}，请以医生处方和药品说明书为准。"


def _treatment_indication_check(option_name: str, message: str) -> dict[str, Any]:
    checks = {
        "根管治疗": ["牙髓炎/根尖周炎诊断", "牙体可修复性", "根管数和弯曲度", "术后冠修复必要性"],
        "种植修复": ["缺牙区骨量和软组织条件", "牙周控制", "全身疾病控制", "咬合和邻牙条件"],
        "正畸治疗": ["错颌类型", "牙周和龋风险", "面型与骨性问题", "患者配合度"],
        "牙周洁治与基础治疗": ["牙周袋深度", "出血指数", "牙石和菌斑控制", "维护依从性"],
        "全冠/烤瓷冠修复": ["剩余牙体组织", "根尖和牙周状态", "咬合空间", "材料选择"],
    }
    return {
        "required_evidence": checks.get(option_name, ["面诊检查", "影像或口内检查", "医生适应证判断"]),
        "message_mentions_risk": _contains(message, ["风险", "失败", "复发", "并发症", "替代"]),
    }


def _treatment_key_risks(option_name: str) -> list[str]:
    risks = {
        "根管治疗": ["遗漏根管或再感染", "治疗后牙体脆弱", "术后疼痛或根尖炎症迁延"],
        "种植修复": ["骨量不足或植骨需求", "种植体周围炎", "全身疾病控制不佳影响愈合"],
        "正畸治疗": ["牙龈炎和脱矿", "牙根吸收", "保持不足导致复发"],
        "牙周洁治与基础治疗": ["短期敏感", "维护不足导致复发", "重度牙周炎需进一步治疗"],
        "全冠/烤瓷冠修复": ["牙体磨除", "边缘不密合或继发龋", "牙龈维护要求高"],
    }
    return risks.get(option_name, ["需结合个体检查评估疗效、费用和并发症风险。"])


def _treatment_review_questions(option_name: str) -> list[str]:
    return [
        f"{option_name}的适应证是否已通过检查确认？",
        "是否存在可选替代方案，为什么当前方案优先？",
        "复诊次数、费用构成和失败/复发风险分别是什么？",
        "术后或治疗后的维护周期如何安排？",
    ]


def _treatment_maintenance_requirements(option_name: str) -> list[str]:
    mapping = {
        "根管治疗": ["复查根尖情况", "评估冠修复或嵌体保护", "避免咬硬物直到永久修复完成"],
        "种植修复": ["定期种植体周围检查", "牙线/间隙刷清洁", "控制牙周和吸烟风险"],
        "正畸治疗": ["每次进食后清洁托槽/附件", "按期复诊加力", "治疗后坚持保持器"],
        "牙周洁治与基础治疗": ["3至6个月牙周维护", "每日牙线/间隙刷", "复查出血和牙周袋"],
        "全冠/烤瓷冠修复": ["清洁冠边缘", "定期检查继发龋和咬合", "避免长期咬硬物"],
    }
    return mapping.get(option_name, ["按医生建议复诊并记录不适症状。"])


def _treatment_complex_flags(message: str, option_names: list[str]) -> list[str]:
    flags = []
    if len(option_names) > 1:
        flags.append("multiple_options")
    if _contains(message, ["种植", "拔", "手术", "植骨", "上颌窦", "复杂", "失败", "再治疗"]):
        flags.append("complex_or_surgical_plan")
    if _contains(message, ["糖尿病", "高血压", "心脏病", "抗凝", "妊娠", "孕"]):
        flags.append("systemic_risk_context")
    return _dedupe(flags)


def _clinical_decision_points(option_names: list[str], message: str) -> list[str]:
    points = ["确认牙位和主诉目标", "结合口内检查和影像确认适应证", "比较疗程、费用、风险和替代方案"]
    if "根管治疗" in option_names:
        points.append("确认牙体剩余量和是否需要冠/嵌体保护")
    if "种植修复" in option_names:
        points.append("确认CBCT骨量、牙周控制和全身疾病控制情况")
    if "正畸治疗" in option_names:
        points.append("确认牙周健康、龋风险和长期保持计划")
    if _contains(message, ["风险", "替代", "费用"]):
        points.append("将患者关心的风险、替代方案和费用因素列入医生沟通清单")
    return _dedupe(points)


def _required_treatment_pre_checks(option_names: list[str]) -> list[str]:
    checks = ["口内检查", "牙位确认", "影像资料", "牙周基础评估"]
    if "根管治疗" in option_names:
        checks.extend(["牙髓活力/叩诊", "根尖片或CBCT按需评估"])
    if "种植修复" in option_names:
        checks.extend(["CBCT骨量评估", "全身病史和用药核查"])
    if "正畸治疗" in option_names:
        checks.extend(["头影测量/模型或口扫", "龋病和牙周风险评估"])
    return _dedupe(checks)


def _patient_treatment_questions(option_names: list[str]) -> list[str]:
    joined = "、".join(option_names) or "当前方案"
    return [
        f"{joined}的目标是止痛、保牙、修复功能还是改善美观？",
        "需要几次复诊，治疗失败或复发时怎么办？",
        "费用主要受哪些因素影响，是否有替代方案？",
        "治疗后家庭维护和复查周期是什么？",
    ]


def _imaging_modality(message: str) -> str:
    for item in ["CBCT", "全景片", "根尖片", "头颅侧位片", "咬翼片"]:
        if item.lower() in message.lower():
            return item
    return "未明确"


def _imaging_findings(message: str) -> list[str]:
    keywords = [
        "阻生智齿",
        "近中倾斜",
        "远中龋坏",
        "根尖阴影",
        "根尖透射影",
        "骨吸收",
        "牙周膜增宽",
        "上颌窦",
        "囊肿",
        "埋伏牙",
        "邻面龋",
        "牙槽骨",
    ]
    return _matched_items(message, keywords)


def _imaging_red_flags(message: str) -> list[dict[str, str]]:
    mapping = {
        "根尖透射影": "可能提示根尖周病变，需结合牙髓活力和临床症状。",
        "根尖阴影": "可能提示根尖周病变，需结合牙髓活力和临床症状。",
        "骨吸收": "需结合牙周探诊判断牙周炎程度和维护方案。",
        "囊肿": "需专科医生结合影像原片和病史评估。",
        "上颌窦": "种植或后牙病变可能涉及上颌窦风险，需专科评估。",
        "远中龋坏": "邻牙龋坏需口内检查确认范围并处理。",
    }
    return [{"signal": key, "reason": reason} for key, reason in mapping.items() if key in message]


def _imaging_term_explanation(term: str) -> dict[str, str]:
    explanations = {
        "阻生智齿": "智齿萌出受阻，可能与冠周炎、邻牙龋坏或清洁困难相关。",
        "近中倾斜": "牙冠方向向前倾斜，常见于下颌阻生智齿描述。",
        "远中龋坏": "牙齿远中邻面存在龋坏线索，需口内检查确认范围。",
        "根尖阴影": "根尖区域影像密度改变，需结合牙髓和根尖检查。",
        "根尖透射影": "根尖区域透亮影，可能与根尖周病变相关。",
        "骨吸收": "牙槽骨高度或密度改变，常需牙周评估。",
        "牙周膜增宽": "牙周膜间隙改变，需结合咬合、炎症或外伤情况。",
        "上颌窦": "上颌后牙或种植评估时需关注与上颌窦关系。",
        "囊肿": "影像提示占位或囊性病变可能，需专科复核。",
        "邻面龋": "邻牙接触面龋坏线索，需探诊和必要影像确认。",
        "牙槽骨": "支持牙齿的骨组织，改变需结合牙周检查。",
    }
    return {
        "term": term,
        "plain_explanation": explanations.get(term, "报告术语需结合上下文和医生阅片解释。"),
        "action_hint": "请由口腔医生结合原始影像、口内检查和症状复核。",
    }


def _imaging_departments(findings: list[str], message: str) -> list[str]:
    departments = []
    if _contains(" ".join(findings) + message, ["阻生智齿", "埋伏牙", "囊肿"]):
        departments.append("口腔颌面外科")
    if _contains(" ".join(findings) + message, ["远中龋坏", "邻面龋", "根尖"]):
        departments.append("牙体牙髓科")
    if _contains(" ".join(findings) + message, ["骨吸收", "牙槽骨", "牙周膜"]):
        departments.append("牙周科")
    if not departments:
        departments.append("口腔全科/综合科")
    return _dedupe(departments)


def _imaging_next_steps(findings: list[str], red_flags: list[dict[str, str]]) -> list[str]:
    steps = ["携带原始影像和正式报告给口腔医生复核。", "结合口内检查、牙髓活力和牙周探诊确认临床意义。"]
    if red_flags:
        steps.insert(0, "报告文本存在需专科复核的风险线索，请不要仅凭AI解释决定治疗。")
    if findings:
        steps.append("围绕报告中的关键术语向医生确认是否需要治疗、观察或进一步检查。")
    return steps


def _imaging_summary_note(modality: str, findings: list[str], red_flags: list[dict[str, str]]) -> str:
    finding_text = "、".join(findings) if findings else "未抽取到明确术语"
    risk_text = f"，其中 {len(red_flags)} 项需要重点复核" if red_flags else ""
    return f"已按{modality}报告文本抽取术语：{finding_text}{risk_text}。"


def _health_segment(message: str, profile: Any | None) -> str:
    age = _profile_int(profile, "age")
    pregnancy = str(_profile_value(profile, "pregnancy_status") or "")
    if _contains(message + pregnancy, ["孕", "妊娠", "备孕", "哺乳"]):
        return "pregnancy"
    if age is not None and age < 12 or _contains(message, ["儿童", "乳牙", "换牙", "窝沟封闭"]):
        return "child"
    if age is not None and age >= 65 or _contains(message, ["老人", "老年", "义齿"]):
        return "elderly"
    if age is not None and age < 18 or _contains(message, ["青少年", "正畸", "牙套"]):
        return "adolescent"
    return "adult"


def _health_focus_areas(message: str, profile: Any | None, segment: str) -> list[str]:
    text = f"{message} {_profile_notes(profile)}"
    focus = []
    if segment == "child":
        focus.extend(["龋病预防", "窝沟封闭评估", "涂氟", "换牙期清洁"])
    if segment == "pregnancy":
        focus.extend(["妊娠期牙龈炎风险", "安全洁治咨询", "饮食和呕吐后清洁"])
    if segment == "elderly":
        focus.extend(["牙周维护", "根面龋预防", "义齿清洁"])
    if _contains(text, ["牙周", "出血", "牙齿松动"]):
        focus.append("牙周维护")
    if _contains(text, ["种植"]):
        focus.append("种植体周围维护")
    if _contains(text, ["正畸", "牙套", "保持器"]):
        focus.append("正畸清洁与保持")
    if _contains(text, ["拔牙", "术后"]):
        focus.append("术后护理")
    if _contains(text, ["糖尿病"]):
        focus.append("糖尿病相关牙周风险")
    if not focus:
        focus.extend(["日常清洁", "龋病和牙周风险控制", "定期口腔检查"])
    return _dedupe(focus)


def _health_risk_level(message: str, profile: Any | None, focus_areas: list[str]) -> str:
    text = f"{message} {_profile_notes(profile)}"
    if _contains(text, ["糖尿病", "牙齿松动", "出血不止", "种植体疼", "术后感染"]):
        return "medium"
    if any(item in focus_areas for item in ["糖尿病相关牙周风险", "术后护理", "种植体周围维护"]):
        return "medium"
    return "low"


def _health_daily_actions(segment: str, focus_areas: list[str]) -> list[str]:
    actions = ["含氟牙膏刷牙每日2次", "每天使用牙线或牙缝刷清洁邻面"]
    if "正畸清洁与保持" in focus_areas:
        actions.append("托槽/附件周围每餐后清洁，按医生要求佩戴保持器或矫治器")
    if "义齿清洁" in focus_areas:
        actions.append("义齿每日取下清洁，睡眠时按医生建议处理")
    if segment == "child":
        actions.append("家长监督刷牙，控制含糖零食和含糖饮料频率")
    if segment == "pregnancy":
        actions.append("孕吐后先清水漱口，避免立即用力刷牙损伤牙面")
    return _dedupe(actions)


def _health_weekly_actions(segment: str, focus_areas: list[str]) -> list[str]:
    actions = ["每周自查牙龈出血、口腔异味、牙齿敏感或松动变化"]
    if "涂氟" in focus_areas:
        actions.append("记录儿童龋风险和近期含糖饮食，便于医生评估涂氟频率")
    if "种植体周围维护" in focus_areas:
        actions.append("检查种植体周围是否红肿、出血或溢脓")
    return actions


def _health_professional_schedule(segment: str, focus_areas: list[str]) -> list[dict[str, str]]:
    schedule = [{"item": "常规口腔检查", "interval": "每6-12个月", "owner": "口腔医生"}]
    if segment == "child":
        schedule.extend(
            [
                {"item": "涂氟评估", "interval": "每3-6个月按龋风险决定", "owner": "儿童口腔医生"},
                {"item": "窝沟封闭评估", "interval": "第一恒磨牙萌出后尽早评估", "owner": "儿童口腔医生"},
            ]
        )
    if "牙周维护" in focus_areas or "糖尿病相关牙周风险" in focus_areas:
        schedule.append({"item": "牙周维护/洁治", "interval": "每3-6个月按牙周风险决定", "owner": "牙周医生"})
    if "种植体周围维护" in focus_areas:
        schedule.append({"item": "种植体周围维护", "interval": "每3-6个月", "owner": "种植/牙周医生"})
    if "正畸清洁与保持" in focus_areas:
        schedule.append({"item": "正畸复诊或保持器复查", "interval": "按正畸医生计划", "owner": "正畸医生"})
    return schedule


def _health_home_monitoring(focus_areas: list[str]) -> list[str]:
    monitoring = ["牙龈出血", "牙痛或冷热敏感", "口腔异味", "龋洞或食物嵌塞"]
    if "种植体周围维护" in focus_areas:
        monitoring.extend(["种植体周围红肿", "种植体松动或咬合痛"])
    if "术后护理" in focus_areas:
        monitoring.extend(["术后出血", "肿胀加重", "发热"])
    return _dedupe(monitoring)


def _health_reminder_candidates(segment: str, focus_areas: list[str]) -> list[dict[str, str]]:
    reminders = [{"type": "routine_check", "title": "口腔检查提醒", "suggested_interval": "6个月"}]
    if segment == "child":
        reminders.append({"type": "fluoride", "title": "儿童涂氟/龋风险评估提醒", "suggested_interval": "3-6个月"})
        reminders.append({"type": "sealant", "title": "窝沟封闭评估提醒", "suggested_interval": "第一恒磨牙萌出后"})
    if "牙周维护" in focus_areas:
        reminders.append({"type": "periodontal_maintenance", "title": "牙周维护提醒", "suggested_interval": "3-6个月"})
    if "种植体周围维护" in focus_areas:
        reminders.append({"type": "implant_maintenance", "title": "种植维护提醒", "suggested_interval": "3-6个月"})
    return reminders


def _health_risk_tips(segment: str, focus_areas: list[str]) -> list[str]:
    tips = ["健康管理建议需随龋风险、牙周状态、治疗记录和医生复查结果动态调整。"]
    if segment == "child":
        tips.append("儿童龋风险变化快，窝沟封闭和涂氟频率需由儿童口腔医生评估。")
    if "糖尿病相关牙周风险" in focus_areas:
        tips.append("糖尿病会增加牙周风险，需结合血糖控制和牙周维护。")
    if "术后护理" in focus_areas:
        tips.append("术后若出现持续出血、肿胀加重、发热或剧痛，应尽快线下复诊。")
    return _dedupe(tips)


def _health_next_steps(segment: str, focus_areas: list[str]) -> list[str]:
    steps = ["建立复诊提醒", "记录刷牙、牙线、洁牙和治疗维护情况"]
    if segment == "child":
        steps.extend(["预约儿童口腔医生评估窝沟封闭", "根据龋风险安排涂氟"])
    if "牙周维护" in focus_areas:
        steps.append("预约牙周检查并确认维护周期")
    if "种植体周围维护" in focus_areas:
        steps.append("记录种植体周围出血、红肿和咬合不适")
    return _dedupe(steps)


def _health_plan_summary(segment: str, focus_areas: list[str]) -> str:
    labels = {
        "child": "儿童口腔健康计划",
        "adolescent": "青少年/正畸阶段健康计划",
        "adult": "成人口腔健康计划",
        "pregnancy": "妊娠期口腔健康计划",
        "elderly": "老年口腔健康计划",
    }
    return f"{labels.get(segment, '口腔健康计划')}，重点覆盖：{'、'.join(focus_areas)}。"


def _dedupe(items: list[Any]) -> list[Any]:
    result = []
    seen = set()
    for item in items:
        key = repr(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result

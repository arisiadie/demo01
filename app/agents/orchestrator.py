from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.agents.agentic_flow import AgenticRAGFlow
from app.agents.contracts import contract_from_agent_response
from app.agents import domain_rules
from app.agents.router import AgentRouter, explain_plan
from app.agents.safety_guard import SafetyGuard
from app.agents.workflow import MultiAgentWorkflow
from app.rag.store import KnowledgeStore, RetrievalHit
from app.schemas.dto import AgentResponse, PatientProfileInput, SourceDTO
from app.services.llm import LLMClient, LLMResult
from app.services.clinical_reference import medication_rules_for_text, treatment_options_for_text
from app.services.security import DISCLAIMER, assess_message, refusal_for_no_evidence


AGENT_NAMES = {
    "triage": "口腔症状预问诊智能体",
    "treatment": "诊疗方案解读智能体",
    "medication": "口腔用药合规审查智能体",
    "imaging": "口腔影像报告解读智能体",
    "health": "口腔健康管理与科普智能体",
}

CATEGORY_BY_AGENT = {
    "triage": ["triage"],
    "treatment": ["treatment", "triage"],
    "medication": ["medication"],
    "imaging": ["imaging"],
    "health": ["health"],
}


@dataclass(frozen=True)
class AgentContext:
    message: str
    requested_agent: str | None = None
    patient_profile: PatientProfileInput | None = None
    has_image: bool = False


class OralAgentOrchestrator:
    def __init__(self, store: KnowledgeStore | None = None, llm: LLMClient | None = None) -> None:
        self.store = store or KnowledgeStore()
        self.llm = llm or LLMClient()
        self.agentic_flow = AgenticRAGFlow(self.store)
        self.router = AgentRouter()
        self.safety_guard = SafetyGuard()
        self.workflow = MultiAgentWorkflow(self.store, self.llm)

    def run(self, context: AgentContext) -> AgentResponse:
        route_plan = self.router.plan(
            context.message,
            requested_agent=context.requested_agent,
            patient_profile=context.patient_profile,
            has_image=context.has_image,
        )
        agent_type = route_plan.primary_agent
        safety = assess_message(context.message, agent_type=agent_type, has_image=context.has_image)
        trace = [
            f"意图识别：{agent_type}",
            *explain_plan(route_plan),
            "Agentic RAG：准备问题拆解与多轮检索",
        ]

        if safety.blocked:
            response = AgentResponse(
                agent_type=agent_type,
                agent_name=AGENT_NAMES[agent_type],
                summary="检测到可能的提示词注入或越权指令，本次仅保留医疗安全边界提示。",
                evidence=["系统必须优先遵守医疗安全、隐私保护和医生复核边界。"],
                risk_tips=["请重新输入真实口腔健康问题，不要包含要求绕过规则的内容。"],
                next_steps=["如存在急症症状，请线下就医。"],
                doctor_review_required=True,
                risk_level="medium",
                refusal=True,
                disclaimer=DISCLAIMER,
                sources=[],
                agent_trace=trace + ["安全校验：拦截提示词注入"],
                safety_flags=safety.flags,
                structured_data={"agent_plan": route_plan.as_dict()},
            )
            self._finalize_response(response, context=context, safety_flags=safety.flags, agent_plan=route_plan.as_dict())
            return response

        retrieval_categories = _categories_for_agent_plan(route_plan.as_dict())
        plan = self.agentic_flow.run(
            message=context.message,
            agent_type=agent_type,
            categories=retrieval_categories,
            top_k=5,
            planned_queries=route_plan.retrieval_queries,
        )
        hits = plan.merged_hits
        if not hits:
            refusal = refusal_for_no_evidence()
            response = AgentResponse(
                agent_type=agent_type,
                agent_name=AGENT_NAMES[agent_type],
                summary=str(refusal["summary"]),
                evidence=list(refusal["evidence"]),
                risk_tips=list(refusal["risk_tips"]),
                next_steps=list(refusal["next_steps"]),
                doctor_review_required=True,
                risk_level="medium",
                refusal=True,
                disclaimer=DISCLAIMER,
                sources=[],
                agent_trace=trace + plan.trace + ["低置信度拒答：未检索到可引用来源"],
                safety_flags=safety.flags + ["low_retrieval_confidence"],
                structured_data={
                    "agent_plan": route_plan.as_dict(),
                    "rag_plan": plan.as_dict(),
                    "source_bindings": _build_source_bindings([], plan),
                },
            )
            self._finalize_response(response, context=context, safety_flags=safety.flags, agent_plan=route_plan.as_dict())
            return response

        evidence = [hit.document.content for hit in hits[:3]]
        response = self._agent_response(agent_type, context, hits, evidence)
        response.risk_level = max_risk(response.risk_level, safety.risk_level)
        response.doctor_review_required = response.doctor_review_required or safety.doctor_review_required
        response.safety_flags = sorted(set(response.safety_flags + safety.flags))
        workflow_result = self.run_workflow(context)
        _merge_workflow_into_response(response, workflow_result)
        cross_review = _build_cross_agent_review(agent_type, context.message, response.structured_data)
        if response.structured_data is None:
            response.structured_data = {}
        response.structured_data["cross_agent_review"] = cross_review
        response.structured_data["agent_plan"] = route_plan.as_dict()
        response.structured_data["rag_plan"] = plan.as_dict()
        response.structured_data["source_bindings"] = _build_source_bindings(response.sources, plan)
        if cross_review["final_review_required"]:
            response.doctor_review_required = True
        if route_plan.doctor_review_required:
            response.doctor_review_required = True
        response.agent_trace = trace + plan.trace + response.agent_trace + ["合规自检：已追加来源引用与医生复核标记"]
        response.agent_trace.append(f"多智能体交叉复核：{cross_review['summary']}")
        self._finalize_response(response, context=context, safety_flags=safety.flags, agent_plan=route_plan.as_dict())
        return response

    def route(self, message: str) -> str:
        return self.router.plan(message).primary_agent
    
    def run_workflow(self, context: AgentContext) -> dict[str, Any]:
        """Run the dynamic multi-agent workflow with handoffs."""
        safety = assess_message(context.message, agent_type=None, has_image=context.has_image)
        
        if safety.blocked:
            return {
                "error": "安全拦截",
                "message": "检测到可能的提示词注入或越权指令",
                "requires_review": True,
            }
        
        profile_dict = {}
        if context.patient_profile:
            profile_dict = {
                "age": context.patient_profile.age,
                "sex": context.patient_profile.sex,
                "pregnancy_status": context.patient_profile.pregnancy_status,
                "allergies": context.patient_profile.allergies,
                "conditions": context.patient_profile.conditions,
                "oral_history": context.patient_profile.oral_history,
            }
        
        result = self.workflow.run_workflow(
            initial_message=context.message,
            context={
                "patient_profile": profile_dict,
                "has_image": context.has_image,
                "requested_agent": context.requested_agent,
                "agent_plan": self.router.plan(
                    context.message,
                    requested_agent=context.requested_agent,
                    patient_profile=context.patient_profile,
                    has_image=context.has_image,
                ).as_dict(),
            }
        )
        
        return result
    
    def get_workflow_graph(self) -> str:
        """Get the workflow visualization in DOT format."""
        return self.workflow.get_graph_visualization()

    def load_workflow_from_db(self, db: Any) -> None:
        """Load the active workflow graph from persisted admin configuration."""
        self.workflow.load_graph_from_db(db)
    
    def update_workflow_graph(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        """Update the workflow graph structure dynamically."""
        self.workflow.update_graph(nodes, edges)

    def _finalize_response(
        self,
        response: AgentResponse,
        *,
        context: AgentContext,
        safety_flags: list[str],
        agent_plan: dict[str, Any] | None,
    ) -> None:
        self.safety_guard.apply(
            response,
            message=context.message,
            agent_type=response.agent_type,
            has_image=context.has_image,
            safety_flags=safety_flags,
            agent_plan=agent_plan,
        )
        _attach_agent_contract(response)

    def _agent_response(
        self,
        agent_type: str,
        context: AgentContext,
        hits: list[RetrievalHit],
        evidence: list[str],
    ) -> AgentResponse:
        profile_notes = _profile_notes(context.patient_profile)
        sources = [SourceDTO(**hit.as_source()) for hit in hits]
        safety_flags: list[str] = []
        structured_data: dict[str, Any] | None = None

        if agent_type == "triage":
            triage_report = domain_rules.build_triage_report(context.message, context.patient_profile)
            structured_data = {"triage_report": triage_report}
            llm_result = self.llm.compose(
                agent_name=AGENT_NAMES[agent_type],
                message=context.message,
                evidence=evidence,
                instruction="建议按牙位、持续时间、诱因、伴随症状和既往史整理为预问诊报告。",
            )
            summary = (
                f"{llm_result.text} 结构化预问诊：牙位/区域为{triage_report['tooth_position']}，"
                f"持续时间为{triage_report['duration_text']}，建议就诊科室为{triage_report['recommended_department']}。"
            )
            risk_tips = [
                "自发痛、夜间痛、冷热刺激后持续痛提示需尽快口腔内科评估。",
                "面颈部肿胀、发热、吞咽或呼吸异常属于高风险信号。",
            ]
            next_steps = [
                f"优先预约{triage_report['recommended_department']}",
                "记录疼痛牙位、持续时间、诱因和伴随症状",
                "携带既往检查或影像资料到口腔科就诊",
            ]
            risk_level = {"urgent": "high", "soon": "medium", "routine": "low"}[triage_report["urgency_level"]]
            doctor_review = risk_level in {"medium", "high"}
        elif agent_type == "treatment":
            treatment_comparison = domain_rules.build_treatment_comparison(context.message)
            structured_data = {"treatment_comparison": treatment_comparison}
            llm_result = self.llm.compose(
                agent_name=AGENT_NAMES[agent_type],
                message=context.message,
                evidence=evidence,
                instruction="按步骤、疗程、费用影响因素、替代方案和复诊要求进行通俗解释。",
            )
            summary = f"{llm_result.text} 方案对比摘要：{treatment_comparison['recommendation_note']}"
            risk_tips = ["治疗方案需结合临床检查、影像、牙周状况和医生面诊判断。"]
            next_steps = [
                "向医生确认牙位、治疗目标、复诊次数、修复方式和费用构成",
                "对比方案的疗程、费用影响因素、维护要求和替代方案",
            ]
            risk_level = treatment_comparison.get("risk_level", "low")
            doctor_review = bool(treatment_comparison.get("doctor_review_required", False))
        elif agent_type == "medication":
            medication_check = domain_rules.build_medication_check(context.message, context.patient_profile)
            structured_data = {"medication_check": medication_check}
            llm_result = self.llm.compose(
                agent_name=AGENT_NAMES[agent_type],
                message=context.message,
                evidence=evidence,
                instruction="优先核查年龄、妊娠状态、基础病、过敏史、剂量和相互作用，不给出处方。",
            )
            summary = f"{llm_result.text} 用药规则审查：{medication_check['compliance_summary']}"
            risk_tips = medication_check["risk_points"][:4] + [
                "存在过敏史、妊娠、儿童老人、肝肾功能异常或抗凝药使用时必须医生复核。",
                "抗菌药、止痛药和漱口水均不应替代病因治疗。",
            ]
            next_steps = [
                "补充年龄、过敏史、基础疾病、妊娠状态、当前药名和医生开具剂量",
                "由医生或药师复核后再用药",
                "如出现皮疹、呼吸不适、面部肿胀等过敏表现，应立即停用并就医",
            ]
            risk_level = "high" if medication_check["contraindications"] else "medium"
            doctor_review = True
            if medication_check["contraindications"] or _contains(context.message, ["青霉素过敏", "过敏"]):
                safety_flags.append("allergy_risk")
            if medication_check["interactions"]:
                safety_flags.append("drug_interaction_risk")
        elif agent_type == "imaging":
            imaging_report_analysis = domain_rules.build_imaging_report_analysis(
                context.message,
                context.patient_profile,
                has_image=context.has_image,
            )
            structured_data = {"imaging_report_analysis": imaging_report_analysis}
            llm_result = self.llm.compose(
                agent_name=AGENT_NAMES[agent_type],
                message=context.message,
                evidence=evidence,
                instruction="仅解释报告文本术语；图片上传只做预览归档，不进行真实图像诊断。",
            )
            summary = f"{llm_result.text} 影像报告文本解析：{imaging_report_analysis['summary_note']}"
            risk_tips = [
                "影像结论必须结合口内检查、牙髓活力、牙周探诊等临床信息。",
                "本平台不对上传图片作真实影像识别或诊断。",
            ]
            next_steps = imaging_report_analysis["recommended_next_steps"]
            risk_level = imaging_report_analysis.get("risk_level", "medium")
            doctor_review = bool(imaging_report_analysis.get("doctor_review_required", True))
            safety_flags.append("visual_diagnosis_disabled")
        else:
            health_plan = domain_rules.build_health_plan(context.message, context.patient_profile)
            structured_data = {"health_plan": health_plan}
            llm_result = self.llm.compose(
                agent_name=AGENT_NAMES[agent_type],
                message=context.message,
                evidence=evidence,
                instruction="生成个性化口腔健康计划，包含刷牙、牙线、洁牙/复诊和特殊阶段维护。",
            )
            summary = f"{llm_result.text} 个性化健康计划：{health_plan['plan_summary']}"
            risk_tips = health_plan["risk_tips"]
            next_steps = health_plan["next_steps"]
            risk_level = health_plan.get("risk_level", "low")
            doctor_review = bool(health_plan.get("doctor_review_required", False))

        if profile_notes:
            summary = f"{summary} 用户资料提示：{profile_notes}"

        return AgentResponse(
            agent_type=agent_type,
            agent_name=AGENT_NAMES[agent_type],
            summary=summary,
            evidence=[hit.excerpt for hit in hits[:3]],
            risk_tips=risk_tips,
            next_steps=next_steps,
            doctor_review_required=doctor_review,
            risk_level=risk_level,
            refusal=False,
            disclaimer=DISCLAIMER,
            sources=sources,
            agent_trace=["智能体生成：结构化结论/依据/风险/下一步"],
            safety_flags=safety_flags,
            llm_meta=llm_result.meta.__dict__,
            structured_data=structured_data,
        )


def _contains(text: str, keywords: list[str]) -> bool:
    return any(keyword.lower() in text.lower() for keyword in keywords)


def _merge_workflow_into_response(response: AgentResponse, workflow_result: dict[str, Any]) -> None:
    if response.structured_data is None:
        response.structured_data = {}
    response.structured_data["workflow"] = workflow_result
    if workflow_result.get("requires_review"):
        response.doctor_review_required = True
    if workflow_result.get("error"):
        response.safety_flags = sorted(set(response.safety_flags + ["workflow_blocked"]))
        return

    primary_source_ids = [source.id for source in response.sources]
    sources_by_id = {source.id: source for source in response.sources}
    for raw_source in workflow_result.get("sources", []) or []:
        try:
            source = SourceDTO(**raw_source)
        except Exception:
            continue
        existing = sources_by_id.get(source.id)
        if existing is None or source.score > existing.score:
            sources_by_id[source.id] = source
    response.sources = sorted(
        sources_by_id.values(),
        key=lambda item: (
            item.id not in primary_source_ids,
            primary_source_ids.index(item.id) if item.id in primary_source_ids else 999,
            -item.score,
        ),
    )[:8]
    response.evidence = [source.excerpt for source in response.sources[:3]]

    workflow_trace = [str(item) for item in workflow_result.get("trace", [])]
    if workflow_trace:
        response.agent_trace.extend(workflow_trace)
    visited = workflow_result.get("visited_agents") or []
    if visited:
        response.agent_trace.append(f"动态多智能体执行链：{' -> '.join(visited)}")


def _attach_agent_contract(response: AgentResponse) -> None:
    if response.structured_data is None:
        response.structured_data = {}
    response.structured_data["agent_contract"] = contract_from_agent_response(response)


def _categories_for_agent_plan(agent_plan: dict[str, Any]) -> list[str]:
    agent_ids = [str(agent_plan.get("primary_agent") or "")]
    agent_ids.extend(str(agent_id) for agent_id in agent_plan.get("secondary_agents") or [])
    categories: list[str] = []
    for agent_id in agent_ids:
        categories.extend(CATEGORY_BY_AGENT.get(agent_id, []))
    if agent_plan.get("risk_signals"):
        categories.append("safety")
    return _dedupe(categories) or ["health"]


def _build_source_bindings(sources: list[SourceDTO], plan: Any) -> list[dict[str, Any]]:
    source_ids = [source.id for source in sources]
    top_source_ids = source_ids[:3]
    bindings = [
        {
            "claim": "结论摘要",
            "source_ids": top_source_ids,
            "reason": "摘要由最高排序的 RAG 来源支撑。",
        },
        {
            "claim": "风险提示",
            "source_ids": top_source_ids,
            "reason": "风险提示结合医疗安全边界和检索命中来源生成。",
        },
        {
            "claim": "建议下一步",
            "source_ids": top_source_ids,
            "reason": "下一步建议需结合检索依据和医生复核边界。",
        },
    ]
    step_bindings = []
    for step in getattr(plan, "steps", []) or []:
        step_bindings.append(
            {
                "claim": f"{step.name} 检索依据",
                "source_ids": [hit.document.id for hit in step.hits[:3]],
                "query": step.query,
                "categories": step.categories,
            }
        )
    return bindings + step_bindings


def _apply_medical_safety_boundary(response: AgentResponse, safety_flags: list[str]) -> None:
    boundary_tips = []
    next_steps = []
    if "diagnosis_or_prescription_boundary" in safety_flags:
        response.refusal = True
        response.doctor_review_required = True
        response.risk_level = max_risk(response.risk_level, "medium")
        boundary_tips.extend(
            [
                "已拦截自动确诊、自动处方或个体化具体剂量请求；平台只提供辅助解释和就医沟通信息。",
                "处方药、抗菌药、止痛药、局麻药和剂量调整必须由执业医师或药师结合面诊资料确认。",
            ]
        )
        next_steps.extend(
            [
                "携带症状、牙位、既往病史、过敏史和当前用药到口腔医生处复核。",
                "如医生已开具处方，请以处方和药品说明书为准，不根据AI输出自行调整剂量。",
            ]
        )
        if not response.summary.startswith("安全边界："):
            response.summary = (
                "安全边界：本平台不自动确诊、不开具处方、不提供个体化具体剂量。"
                "以下内容仅作就医沟通和医生复核参考。\n"
                f"{response.summary}"
            )
        response.agent_trace.append("医疗安全校验：已拦截诊断/处方/剂量边界请求")
    if "emergency_symptom" in safety_flags:
        response.doctor_review_required = True
        response.risk_level = "high"
        boundary_tips.append("出现呼吸/吞咽困难、高热、快速肿胀、大量出血等急症信号时，应立即线下急诊处理。")
        next_steps.insert(0, "如当前存在急症信号，请优先前往口腔急诊或综合医院急诊。")
        response.agent_trace.append("医疗安全校验：识别急症信号，已升级高风险和医生复核")
    response.risk_tips = _dedupe(boundary_tips + response.risk_tips)
    response.next_steps = _dedupe(next_steps + response.next_steps)


def _profile_notes(profile: PatientProfileInput | None) -> str:
    if profile is None:
        return ""
    notes = []
    if profile.age is not None:
        notes.append(f"年龄 {profile.age} 岁")
    if profile.pregnancy_status:
        notes.append(f"妊娠状态：{profile.pregnancy_status}")
    if profile.allergies:
        notes.append(f"过敏史：{profile.allergies}")
    if profile.conditions:
        notes.append(f"基础病：{profile.conditions}")
    return "；".join(notes)


def _build_triage_report(message: str, profile: PatientProfileInput | None) -> dict[str, Any]:
    triggers = _matched_items(message, ["冷热刺激", "热刺激", "冷刺激", "咬合痛", "咀嚼痛", "夜间痛", "自发痛", "刷牙出血"])
    accompanying = _matched_items(message, ["肿胀", "发热", "流脓", "张口受限", "吞咽困难", "呼吸困难", "牙龈出血", "牙齿松动"])
    tooth_position = _extract_tooth_position(message)
    duration_text = _extract_duration(message)
    pain_character = _extract_pain_character(message)
    suspected_conditions = _suspected_conditions(message, triggers, accompanying)
    urgency_level = _triage_urgency(message, accompanying)
    recommended_department = _recommended_department(message, suspected_conditions, urgency_level)
    report = {
        "tooth_position": tooth_position,
        "duration_text": duration_text,
        "pain_character": pain_character,
        "triggers": triggers,
        "accompanying_symptoms": accompanying,
        "suspected_conditions": suspected_conditions,
        "urgency_level": urgency_level,
        "urgency_label": {"urgent": "急诊/尽快", "soon": "近期就诊", "routine": "常规预约"}[urgency_level],
        "recommended_department": recommended_department,
        "doctor_review_required": urgency_level in {"urgent", "soon"},
        "patient_context": _patient_context(profile),
    }
    return report


def _build_medication_check(message: str, profile: PatientProfileInput | None) -> dict[str, Any]:
    rules = medication_rules_for_text(message)
    dose_request_detected = _contains(message, ["吃几片", "一天几次", "剂量", "用量", "最大剂量", "多少毫克", "mg"])
    checked_drugs = [
        {
            "drug_name": rule["drug_name"],
            "category": rule["category"],
            "dose_note": rule["dose_note"],
            "alcohol_warning": rule["alcohol_warning"],
            "max_dose_boundary": _max_dose_boundary(rule["drug_name"]),
        }
        for rule in rules
    ]
    weight_kg = _extract_weight_kg(message)
    profile_text = _profile_notes(profile)
    combined_text = f"{message} {profile_text}"
    risk_points = []
    contraindications = []
    interactions = []

    if not rules:
        risk_points.append("未识别到内测药物规则库中的明确药名，无法完成合规核查。")
    if dose_request_detected:
        risk_points.append("用户提出剂量/用量问题：平台不自动给出处方剂量，仅提示需医生或药师按年龄、体重、肝肾功能核算。")

    for rule in rules:
        drug_name = rule["drug_name"]
        if drug_name == "阿莫西林" and _contains(combined_text, ["青霉素过敏", "β-内酰胺过敏", "头孢过敏"]):
            contraindications.append(f"{drug_name}：用户提示青霉素/β-内酰胺相关过敏史，规则建议禁用并医生复核。")
        if drug_name == "布洛芬" and _contains(combined_text, ["胃溃疡", "肾病", "肾功能", "哮喘", "抗凝", "华法林", "妊娠晚期"]):
            contraindications.append(f"{drug_name}：存在消化道、肾功能、哮喘、抗凝或妊娠相关风险线索，需医生复核。")
        if drug_name == "对乙酰氨基酚" and _contains(combined_text, ["肝病", "肝功能", "长期饮酒", "酒精"]):
            contraindications.append(f"{drug_name}：肝功能或酒精相关风险需医生复核，避免重复用药。")
        if _contains(combined_text, ["孕", "妊娠", "备孕", "哺乳"]):
            risk_points.append(f"{drug_name}：妊娠/备孕/哺乳状态需由医生评估获益与风险。")
        if profile and profile.age is not None and (profile.age < 12 or profile.age >= 65):
            risk_points.append(f"{drug_name}：年龄 {profile.age} 岁属于需谨慎核查剂量和禁忌的人群。")
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
    return {
        "checked_drugs": checked_drugs,
        "risk_points": _dedupe(risk_points),
        "contraindications": _dedupe(contraindications),
        "interactions": _dedupe(interactions),
        "compliance_summary": compliance_summary,
        "review_required": True,
        "required_context": ["年龄", "体重", "妊娠/哺乳状态", "过敏史", "肝肾功能", "基础病", "当前药物", "医生开具剂量"],
        "missing_context": missing_context,
        "dose_request_detected": dose_request_detected,
        "clinical_review_items": [
            "确认药物适应证是否来自医生诊断",
            "核对过敏史、妊娠/哺乳、儿童/老人等特殊人群",
            "核对肝肾功能、心血管病、消化道出血和抗凝/抗血小板药物",
            "涉及抗菌药、局麻药或明确剂量请求时由医生/药师复核",
        ],
        "weight_kg": weight_kg,
        "dose_boundary_note": "内测系统不输出自动处方剂量；涉及儿童、老人、肝肾功能异常、局麻药和抗菌药时必须医生/药师复核。",
        "patient_context": _patient_context(profile),
    }


def _build_treatment_comparison(message: str) -> dict[str, Any]:
    options = treatment_options_for_text(message)
    if not options:
        options = treatment_options_for_text("根管 种植 正畸 洁治 烤瓷冠")[:3]
    comparison = [
        {
            "option_name": option["option_name"],
            "category": option["category"],
            "main_steps": option["steps"],
            "duration_note": option["duration_note"],
            "cost_factors": option["cost_factors"],
            "advantages": option["advantages"],
            "disadvantages": option["disadvantages"],
            "alternatives": option["alternatives"],
        }
        for option in options
    ]
    option_names = [item["option_name"] for item in comparison]
    if len(option_names) == 1:
        recommendation = f"已匹配{option_names[0]}，建议面诊确认适应证、牙位、复诊次数、费用构成和替代方案。"
    else:
        recommendation = f"已匹配{len(option_names)}个相关方案：{'、'.join(option_names)}；需结合检查和影像由医生确定优先方案。"
    return {
        "matched_options": option_names,
        "comparison": comparison,
        "recommendation_note": recommendation,
        "doctor_review_required": False,
    }


def _matched_items(text: str, keywords: list[str]) -> list[str]:
    return [keyword for keyword in keywords if keyword in text]


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


def _missing_medication_context(
    message: str,
    profile: PatientProfileInput | None,
    weight_kg: float | None,
) -> list[str]:
    missing = []
    profile_text = _profile_notes(profile)
    combined_text = f"{message} {profile_text}"
    if not (profile and profile.age is not None) and not re.search(r"\d+\s*岁", message):
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


def _build_cross_agent_review(agent_type: str, message: str, structured_data: dict[str, Any] | None) -> dict[str, Any]:
    checks: list[str] = []
    conflicts: list[str] = []
    opinions: list[dict[str, str]] = []
    handoff_tasks: list[dict[str, str]] = []
    reviewers = ["医疗安全边界智能体"]
    review_required = False
    structured_data = structured_data or {}

    if agent_type == "medication":
        reviewers.extend(["症状预问诊智能体", "用药合规审查智能体"])
        check = structured_data.get("medication_check", {})
        opinions.append({"agent": "用药合规审查智能体", "opinion": check.get("compliance_summary", "需补充完整用药上下文。")})
        if check.get("missing_context"):
            handoff_tasks.append({"to_agent": "医生复核入口", "task": f"补齐用药上下文：{'、'.join(check['missing_context'])}。"})
        if check.get("contraindications"):
            conflicts.append("用药审查发现禁忌或高风险线索。")
            review_required = True
        if _contains(message, ["牙痛", "肿胀", "发热"]):
            opinion = "用药不能替代病因治疗，需判断是否存在牙髓/根尖/冠周感染。"
            opinions.append({"agent": "症状预问诊智能体", "opinion": opinion})
            checks.append(f"预问诊智能体提示：{opinion}")
            handoff_tasks.append({"to_agent": "症状预问诊智能体", "task": "补充牙位、持续时间、疼痛诱因和是否发热肿胀，用于判断就诊紧急程度。"})
    elif agent_type == "treatment":
        reviewers.extend(["用药合规审查智能体", "健康管理智能体"])
        opinions.append({"agent": "用药合规审查智能体", "opinion": "治疗前后如涉及抗菌药、止痛药或局麻药，需要补充过敏史和基础病。"})
        opinions.append({"agent": "健康管理智能体", "opinion": "方案应同步复诊计划和家庭维护要求。"})
        checks.extend([item["opinion"] for item in opinions])
        handoff_tasks.append({"to_agent": "健康管理智能体", "task": "根据治疗方案生成复诊、清洁和维护周期。"})
    elif agent_type == "imaging":
        reviewers.extend(["症状预问诊智能体", "诊疗方案解读智能体"])
        opinions.append({"agent": "影像报告解读智能体", "opinion": "仅解释报告文本，图片不输出真实图像诊断。"})
        opinions.append({"agent": "诊疗方案解读智能体", "opinion": "影像结论需结合口内检查后才能形成治疗方案。"})
        checks.extend([item["opinion"] for item in opinions])
        handoff_tasks.append({"to_agent": "诊疗方案解读智能体", "task": "由医生结合口内检查、影像原片和报告文本形成治疗计划。"})
        review_required = True
    elif agent_type == "triage":
        reviewers.extend(["影像报告解读智能体", "用药合规审查智能体"])
        report = structured_data.get("triage_report", {})
        if report.get("urgency_level") in {"urgent", "soon"}:
            review_required = True
            handoff_tasks.append({"to_agent": "医生复核入口", "task": f"按{report.get('recommended_department', '口腔科')}方向复核预问诊报告。"})
        opinions.append({"agent": "用药合规审查智能体", "opinion": "预问诊阶段不生成处方，仅提示就医和风险补充信息。"})
        opinions.append({"agent": "影像报告解读智能体", "opinion": "如症状涉及阻生齿、根尖或骨吸收，建议携带影像报告由医生复核。"})
        checks.extend([item["opinion"] for item in opinions])
    else:
        reviewers.extend(["预问诊智能体", "健康管理智能体"])
        opinions.append({"agent": "健康管理智能体", "opinion": "个性化计划需随治疗记录和复诊结果调整。"})
        checks.append(opinions[0]["opinion"])
        handoff_tasks.append({"to_agent": "患者健康档案", "task": "将维护周期、复诊提醒和牙位状态写入健康档案。"})

    if not checks:
        checks.append("未发现跨智能体冲突，输出保持 AI 辅助参考边界。")
    summary = "需医生复核" if review_required or conflicts else "未发现明显冲突"
    return {
        "reviewer_agents": reviewers,
        "parallel_opinions": opinions,
        "checks": checks,
        "conflicts": conflicts,
        "handoff_tasks": handoff_tasks,
        "final_review_required": review_required or bool(conflicts),
        "integrated_conclusion": _integrated_cross_review_conclusion(opinions, conflicts, review_required),
        "summary": summary,
    }


def _integrated_cross_review_conclusion(
    opinions: list[dict[str, str]],
    conflicts: list[str],
    review_required: bool,
) -> str:
    if conflicts:
        return f"多智能体意见存在高风险点：{'；'.join(conflicts)} 建议医生复核后再行动。"
    if review_required:
        return "多智能体意见一致要求医生复核，当前输出仅作为就医沟通材料。"
    if opinions:
        agents = "、".join(item["agent"] for item in opinions)
        return f"{agents}已完成交叉检查，未发现明显冲突。"
    return "已完成基础合规自检，未发现明显冲突。"


def _extract_tooth_position(message: str) -> str:
    patterns = [
        r"[左右]?[上下][前后]?[牙齿]?",
        r"[左右][上下]后牙",
        r"[左右][上下]智齿",
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
    if not conditions:
        conditions.append({"name": "口腔常见疼痛或炎症待查", "basis": "当前信息不足，需补充牙位、诱因、持续时间和口内检查。"})
    return conditions


def _triage_urgency(message: str, accompanying: list[str]) -> str:
    if _contains(message, ["呼吸困难", "吞咽困难", "高热", "面部快速肿胀", "大量出血"]) or {"呼吸困难", "吞咽困难"} & set(accompanying):
        return "urgent"
    if _contains(message, ["夜间痛", "自发痛", "肿胀", "发热", "张口受限", "流脓", "松动"]):
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
    if _contains(message, ["儿童", "乳牙", "换牙"]):
        return "儿童口腔科"
    return "口腔全科/综合科"


def _patient_context(profile: PatientProfileInput | None) -> dict[str, Any]:
    if profile is None:
        return {}
    return {
        "age": profile.age,
        "sex": profile.sex,
        "pregnancy_status": profile.pregnancy_status,
        "allergies": profile.allergies,
        "conditions": profile.conditions,
        "oral_history": profile.oral_history,
    }


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


def _dedupe(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def max_risk(left: str, right: str) -> str:
    order = {"low": 1, "medium": 2, "high": 3}
    return left if order[left] >= order[right] else right

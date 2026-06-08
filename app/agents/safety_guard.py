from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.schemas.dto import AgentResponse
from app.services.security import DISCLAIMER


Severity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class SafetyFinding:
    code: str
    severity: Severity
    message: str
    action: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "action": self.action,
        }


@dataclass
class SafetyGuardResult:
    status: Literal["passed", "modified"] = "passed"
    findings: list[SafetyFinding] = field(default_factory=list)
    applied_actions: list[str] = field(default_factory=list)

    def add(self, finding: SafetyFinding) -> None:
        self.status = "modified"
        self.findings.append(finding)
        self.applied_actions.append(finding.action)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [finding.as_dict() for finding in self.findings],
            "applied_actions": _dedupe(self.applied_actions),
        }


class SafetyGuard:
    """Final medical safety judge for agent responses.

    The guard does not create medical content. It only normalizes the final
    response boundary before persistence and frontend display.
    """

    def apply(
        self,
        response: AgentResponse,
        *,
        message: str,
        agent_type: str | None = None,
        has_image: bool = False,
        safety_flags: list[str] | None = None,
        agent_plan: dict[str, Any] | None = None,
    ) -> SafetyGuardResult:
        flags = _dedupe([*(response.safety_flags or []), *(safety_flags or [])])
        plan = agent_plan or {}
        plan_signals = [str(item) for item in plan.get("risk_signals", []) or []]
        result = SafetyGuardResult()

        if "prompt_injection_attempt" in flags:
            result.add(
                SafetyFinding(
                    code="prompt_injection_blocked",
                    severity="medium",
                    message="检测到提示词注入或越权请求。",
                    action="refuse_and_require_review",
                )
            )
            response.refusal = True
            response.doctor_review_required = True
            response.risk_level = _max_risk(response.risk_level, "medium")
            response.risk_tips = _dedupe(["请重新输入真实口腔健康问题，不要包含要求绕过规则的内容。", *response.risk_tips])

        if "diagnosis_or_prescription_boundary" in flags or _has_any(plan_signals, {"prescription_boundary", "diagnosis_boundary"}):
            result.add(
                SafetyFinding(
                    code="diagnosis_prescription_boundary",
                    severity="medium",
                    message="请求涉及自动确诊、自动处方或个体化具体剂量边界。",
                    action="refuse_specific_diagnosis_prescription",
                )
            )
            _apply_prescription_boundary(response)

        if "emergency_symptom" in flags or _has_any(plan_signals, {"emergency_symptom", "acute_swelling"}):
            result.add(
                SafetyFinding(
                    code="urgent_symptom_review",
                    severity="high",
                    message="识别到急症或面颌部肿胀等高风险信号。",
                    action="upgrade_high_risk_and_review",
                )
            )
            response.doctor_review_required = True
            response.risk_level = "high"
            response.risk_tips = _dedupe([
                "出现呼吸/吞咽困难、高热、快速肿胀、大量出血或面颌部肿胀加重时，应立即线下急诊处理。",
                *response.risk_tips,
            ])
            response.next_steps = _dedupe([
                "如当前存在急症信号，请优先前往口腔急诊或综合医院急诊。",
                *response.next_steps,
            ])

        if has_image or response.agent_type == "imaging" or _has_any(flags, {"image_upload_no_visual_diagnosis", "imaging_text_only_boundary"}):
            result.add(
                SafetyFinding(
                    code="imaging_text_only_boundary",
                    severity="medium",
                    message="影像模块只能解释报告文本，不能对上传图片作真实诊断。",
                    action="force_imaging_text_only_notice",
                )
            )
            response.doctor_review_required = True
            response.risk_level = _max_risk(response.risk_level, "medium")
            response.safety_flags = _dedupe([*response.safety_flags, "visual_diagnosis_disabled"])
            response.risk_tips = _dedupe([
                "本平台不对上传图片作真实影像识别或诊断，仅解释用户提供的报告文本。",
                *response.risk_tips,
            ])

        if response.agent_type == "medication" or _has_any(flags, {"medication_requires_context_check"}):
            result.add(
                SafetyFinding(
                    code="medication_context_review",
                    severity="medium",
                    message="用药审查必须核查年龄、孕期、过敏史、基础病、剂量和相互作用。",
                    action="require_medication_context_review",
                )
            )
            response.doctor_review_required = True
            response.risk_level = _max_risk(response.risk_level, "medium")
            response.safety_flags = _dedupe([*response.safety_flags, "medication_requires_context_check"])

        if bool(plan.get("doctor_review_required")):
            result.add(
                SafetyFinding(
                    code="router_plan_review_required",
                    severity="medium",
                    message="Router 计划要求医生复核。",
                    action="require_review_from_agent_plan",
                )
            )
            response.doctor_review_required = True
            response.risk_level = _max_risk(response.risk_level, "medium")

        if not response.sources:
            was_refusal = response.refusal
            result.add(
                SafetyFinding(
                    code="no_citable_sources",
                    severity="medium",
                    message="最终回答缺少可引用来源。",
                    action="refuse_or_keep_review_for_no_sources",
                )
            )
            response.refusal = True
            response.doctor_review_required = True
            response.risk_level = _max_risk(response.risk_level, "medium")
            response.safety_flags = _dedupe([*response.safety_flags, "low_retrieval_confidence"])
            if not was_refusal and not response.summary.startswith("低置信度拒答：") and not response.summary.startswith("安全边界："):
                response.summary = f"低置信度拒答：缺少可引用来源，当前不生成具体医疗建议。\n{response.summary}"
            response.risk_tips = _dedupe(["未检索到可引用来源时，不能输出具体医疗建议。", *response.risk_tips])

        if response.disclaimer != DISCLAIMER:
            result.add(
                SafetyFinding(
                    code="disclaimer_normalized",
                    severity="low",
                    message="统一医疗免责声明。",
                    action="normalize_disclaimer",
                )
            )
            response.disclaimer = DISCLAIMER

        response.safety_flags = _dedupe([*flags, *response.safety_flags])
        response.risk_tips = _dedupe(response.risk_tips)
        response.next_steps = _dedupe(response.next_steps)
        response.agent_trace = _dedupe([*response.agent_trace, *_trace_lines(result)])
        if response.structured_data is None:
            response.structured_data = {}
        response.structured_data["safety_guard"] = result.as_dict()
        return result


def _apply_prescription_boundary(response: AgentResponse) -> None:
    response.refusal = True
    response.doctor_review_required = True
    response.risk_level = _max_risk(response.risk_level, "medium")
    if not response.summary.startswith("安全边界："):
        response.summary = (
            "安全边界：本平台不自动确诊、不开具处方、不提供个体化具体剂量。"
            "以下内容仅作就医沟通和医生复核参考。\n"
            f"{response.summary}"
        )
    response.risk_tips = _dedupe([
        "已拦截自动确诊、自动处方或个体化具体剂量请求；平台只提供辅助解释和就医沟通信息。",
        "处方药、抗菌药、止痛药、局麻药和剂量调整必须由执业医师或药师结合面诊资料确认。",
        *response.risk_tips,
    ])
    response.next_steps = _dedupe([
        "携带症状、牙位、既往病史、过敏史和当前用药到口腔医生处复核。",
        "如医生已开具处方，请以处方和药品说明书为准，不根据AI输出自行调整剂量。",
        *response.next_steps,
    ])


def _trace_lines(result: SafetyGuardResult) -> list[str]:
    if result.status == "passed":
        return ["医疗安全校验 / Safety Guard：最终合规裁判通过"]
    codes = "、".join(finding.code for finding in result.findings)
    return [f"医疗安全校验 / Safety Guard：已执行最终合规裁判（{codes}）"]


def _has_any(values: list[str], expected: set[str]) -> bool:
    return bool(set(values) & expected)


def _max_risk(left: str, right: str) -> str:
    order = {"low": 1, "medium": 2, "high": 3}
    return left if order.get(left, 1) >= order.get(right, 1) else right


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result

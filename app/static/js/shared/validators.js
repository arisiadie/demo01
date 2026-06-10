// Pre-submit validation aligned with app/schemas/dto.py (the backend source of
// truth). Each validator returns { ok, errors[], fieldErrors:{fieldId: msg} } so
// callers can both toast a summary and mark the offending inputs inline.
// Scope this round: required fields + obvious format (enums, numeric ranges).
// Max-length is left to the backend.

function result(fieldErrors) {
  const errors = Object.values(fieldErrors);
  return { ok: errors.length === 0, errors, fieldErrors };
}

// dto.ConsultationRequest.message: min_length=1
export function validateConsultationPayload(payload, messageFieldId = "messageInput") {
  const fieldErrors = {};
  if (!payload || !String(payload.message || "").trim()) {
    fieldErrors[messageFieldId] = "请输入咨询内容";
  }
  return result(fieldErrors);
}

// dto.ReviewUpdate: status enum; needs_followup requires followup_instruction.
const REVIEW_STATES = new Set(["approved", "needs_followup", "returned_for_info", "rejected"]);

export function validateReviewPayload(payload) {
  const fieldErrors = {};
  if (!payload || !REVIEW_STATES.has(payload.status)) {
    // status comes from the action button, not a field; surface as general error
    fieldErrors.__status = "复核状态无效";
  }
  if (payload?.status === "needs_followup" && !String(payload.followup_instruction || "").trim()) {
    fieldErrors.followupInstructionInput = "选择「需随访」时必须填写随访说明";
  }
  return result(fieldErrors);
}

// dto.KnowledgeDocumentInput: title/category/source/content all min_length=1
export function validateKnowledgeDocument(payload) {
  const fieldErrors = {};
  if (!String(payload?.title || "").trim()) fieldErrors.knowledgeTitleInput = "文档标题不能为空";
  if (!String(payload?.category || "").trim()) fieldErrors.knowledgeCategoryInput = "分类不能为空";
  if (!String(payload?.source || "").trim()) fieldErrors.knowledgeSourceInput = "来源不能为空";
  if (!String(payload?.content || "").trim()) fieldErrors.knowledgeContentInput = "文档内容不能为空";
  return result(fieldErrors);
}

// dto.TreatmentRecordInput: diagnosis_text + treatment_name min_length=1
export function validateTreatmentRecord(payload) {
  const fieldErrors = {};
  if (!String(payload?.treatment_name || "").trim()) fieldErrors.recordTreatmentInput = "请填写治疗名称";
  if (!String(payload?.diagnosis_text || "").trim()) fieldErrors.recordDiagnosisInput = "请填写诊断/记录摘要";
  return result(fieldErrors);
}

// dto.ReminderInput: note min_length=1
export function validateReminder(payload) {
  const fieldErrors = {};
  if (!String(payload?.note || "").trim()) fieldErrors.reminderNoteInput = "请填写提醒内容";
  return result(fieldErrors);
}

// dto.ToothRecordInput: tooth_position min_length=1; maintenance_cycle_days 30-720
export function validateToothRecord(payload) {
  const fieldErrors = {};
  if (!String(payload?.tooth_position || "").trim()) fieldErrors.toothPositionInput = "请填写牙位";
  const days = Number(payload?.maintenance_cycle_days);
  if (!Number.isFinite(days) || days < 30 || days > 720) {
    fieldErrors.toothCycleInput = "维护周期需在 30–720 天之间";
  }
  return result(fieldErrors);
}

// dto.PatientProfileInput: age 0-120 (optional)
export function validateProfile(payload) {
  const fieldErrors = {};
  if (payload?.age !== null && payload?.age !== undefined && payload?.age !== "") {
    const age = Number(payload.age);
    if (!Number.isInteger(age) || age < 0 || age > 120) {
      fieldErrors.ageInput = "年龄需在 0–120 之间";
    }
  }
  return result(fieldErrors);
}

// Topology check for the workflow graph before PUT: nodes non-empty, unique
// node ids, and every edge endpoint references an existing node.
export function validateWorkflowGraph(payload) {
  const errors = [];
  const nodes = Array.isArray(payload?.nodes) ? payload.nodes : null;
  const edges = Array.isArray(payload?.edges) ? payload.edges : [];
  if (!nodes || nodes.length === 0) {
    errors.push("nodes 不能为空");
    return { ok: false, errors, fieldErrors: {} };
  }
  const idSet = new Set();
  nodes.forEach((n, i) => {
    if (!n.node_id) errors.push(`第 ${i + 1} 个节点缺少 node_id`);
    else if (idSet.has(n.node_id)) errors.push(`node_id 重复: ${n.node_id}`);
    else idSet.add(n.node_id);
  });
  edges.forEach((e, i) => {
    if (!idSet.has(e.source)) errors.push(`第 ${i + 1} 条边的 source 指向不存在的节点: ${e.source}`);
    if (!idSet.has(e.target)) errors.push(`第 ${i + 1} 条边的 target 指向不存在的节点: ${e.target}`);
  });
  return { ok: errors.length === 0, errors, fieldErrors: {} };
}

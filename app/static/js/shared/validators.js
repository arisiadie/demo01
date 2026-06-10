// Pre-submit validation. Each validator returns { ok, errors[] } so callers can
// block the request and surface specific messages instead of relying on the
// backend to reject malformed payloads.

export function validateConsultationPayload(payload) {
  const errors = [];
  if (!payload || !String(payload.message || "").trim()) {
    errors.push("请输入咨询内容");
  }
  return { ok: errors.length === 0, errors };
}

const REVIEW_STATES = new Set(["approved", "needs_followup", "returned_for_info", "rejected"]);

export function validateReviewPayload(payload) {
  const errors = [];
  if (!payload || !REVIEW_STATES.has(payload.status)) {
    errors.push("复核状态无效");
  }
  if (payload?.status === "needs_followup" && !String(payload.followup_instruction || "").trim()) {
    errors.push("选择「需随访」时必须填写随访说明");
  }
  return { ok: errors.length === 0, errors };
}

export function validateKnowledgeDocument(payload) {
  const errors = [];
  if (!String(payload?.title || "").trim()) errors.push("文档标题不能为空");
  if (!String(payload?.content || "").trim()) errors.push("文档内容不能为空");
  return { ok: errors.length === 0, errors };
}

// Topology check for the workflow graph before PUT: nodes non-empty, unique
// node ids, and every edge endpoint references an existing node.
export function validateWorkflowGraph(payload) {
  const errors = [];
  const nodes = Array.isArray(payload?.nodes) ? payload.nodes : null;
  const edges = Array.isArray(payload?.edges) ? payload.edges : [];
  if (!nodes || nodes.length === 0) {
    errors.push("nodes 不能为空");
    return { ok: false, errors };
  }
  const ids = nodes.map((n) => n.node_id);
  const idSet = new Set();
  ids.forEach((id, i) => {
    if (!id) errors.push(`第 ${i + 1} 个节点缺少 node_id`);
    else if (idSet.has(id)) errors.push(`node_id 重复: ${id}`);
    else idSet.add(id);
  });
  edges.forEach((e, i) => {
    if (!idSet.has(e.source)) errors.push(`第 ${i + 1} 条边的 source 指向不存在的节点: ${e.source}`);
    if (!idSet.has(e.target)) errors.push(`第 ${i + 1} 条边的 target 指向不存在的节点: ${e.target}`);
  });
  return { ok: errors.length === 0, errors };
}

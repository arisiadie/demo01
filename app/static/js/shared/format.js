export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function formatDate(dateStr) {
  try {
    return new Date(dateStr).toLocaleDateString("zh-CN");
  } catch {
    return dateStr;
  }
}

export function riskLabel(risk) {
  return { low: "低", medium: "中", high: "高" }[risk] || risk;
}

export function agentLabel(agent) {
  return {
    triage: "预问诊",
    treatment: "方案",
    medication: "用药",
    imaging: "影像",
    health: "健康",
  }[agent] || agent;
}

export function agentRoleLabel(role) {
  return { patient: "患者", doctor: "医生", admin: "管理员" }[role] || role;
}

export function dataRequestTypeLabel(type) {
  return { export: "导出", delete: "删除" }[type] || type;
}

export function dataRequestStatusLabel(status) {
  return { pending: "待处理", approved: "已批准", rejected: "已拒绝" }[status] || status;
}

export function getCategoryName(cat) {
  const names = {
    triage: "分诊",
    treatment: "治疗",
    medication: "用药",
    imaging: "影像",
    health: "健康",
    mucosa: "黏膜",
    case: "病例",
    emergency: "紧急",
    guide: "指南",
    safety: "安全",
  };
  return names[cat] || cat;
}

export function getFailureTypeName(type) {
  const names = {
    semantic_mismatch: "语义不匹配",
    keyword_missing: "关键词缺失",
    category_confusion: "类别混淆",
    ambiguous_query: "查询歧义",
    document_not_found: "文档缺失",
    other: "其他",
  };
  return names[type] || type;
}

export function toIsoOrNull(value) {
  return value ? new Date(value).toISOString() : null;
}

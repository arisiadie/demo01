// Normalizers collapse the backend's inconsistent field names into one shape
// the renderers can rely on, so entry files stop doing `a || b || c` inline.

export function normalizeAgentResponse(data) {
  data = data || {};
  return {
    consultationId: data.consultation_id ?? null,
    agentType: data.agent_type || "",
    agentName: data.agent_name || "",
    summary: data.summary || "",
    evidence: data.evidence || [],
    riskTips: data.risk_tips || [],
    nextSteps: data.next_steps || [],
    riskLevel: data.risk_level || "low",
    doctorReviewRequired: !!data.doctor_review_required,
    disclaimer: data.disclaimer || "",
    sources: data.sources || [],
    agentTrace: data.agent_trace || [],
    safetyFlags: data.safety_flags || [],
    structuredData: data.structured_data || null,
    raw: data,
  };
}

// GET /api/consultations/{id} archive shape.
export function normalizeConsultationDetail(data) {
  data = data || {};
  const consultation = data.consultation || {};
  const response = data.agent_response || {};
  return {
    consultation,
    response,
    structured: data.structured_outputs || response.structured_data || null,
    retrievalHits: data.retrieval_hits || consultation.sources || [],
    llmCalls: data.llm_calls || [],
    llmCall: data.llm_call || null,
    trace: data.agent_run?.trace || response.agent_trace || [],
    review: data.review || null,
    uploads: data.uploads || [],
    disclaimer: data.disclaimer || response.disclaimer || "",
    summary: consultation.summary || response.summary || "",
    input: consultation.sanitized_input || consultation.input_text || "",
  };
}

// GET /api/doctor/consultations/{id}/report shape.
export function normalizeDoctorReport(data) {
  data = data || {};
  const consultation = data.consultation || {};
  return {
    consultation,
    structured: data.structured_outputs || null,
    retrievalHits: data.retrieval_hits || [],
    llmCalls: data.llm_calls || [],
    llmCall: data.llm_call || null,
    trace: data.agent_run?.trace || [],
    disclaimer: data.disclaimer || "",
  };
}

// Traceability sub-tree used by admin/doctor depth views.
export function normalizeTraceability(data) {
  const t = data?.traceability || data || {};
  return {
    workflow: t.workflow || null,
    rag: t.rag || null,
    llm: t.llm || null,
    safety: t.safety || null,
    persistence: t.persistence || null,
  };
}

export function normalizeRagEvaluation(data) {
  data = data || {};
  return {
    backend: data.backend || "N/A",
    caseCount: data.case_count || 0,
    hitRate: data.hit_rate || 0,
    mrr: data.mrr || 0,
    failureCount: data.failure_count || 0,
    difficultyAnalysis: data.difficulty_analysis || null,
    categoryRecall: data.category_recall || null,
    failureAnalysis: data.failure_analysis || null,
    raw: data,
  };
}

export function normalizeLlmMetrics(data) {
  data = data || {};
  return {
    totalCalls: data.total_calls ?? data.count ?? 0,
    avgLatencyMs: data.avg_latency_ms ?? data.latency_ms ?? null,
    totalTokens: data.total_tokens ?? null,
    totalCost: data.total_cost ?? data.estimated_cost ?? null,
    successRate: data.success_rate ?? null,
    raw: data,
  };
}

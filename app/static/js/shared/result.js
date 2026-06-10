import { escapeHtml, agentLabel, riskLabel } from "./format.js";

// depth controls how much detail is shown:
//   "patient" -> summary, risk, next steps, sources, review flag
//   "doctor"  -> + agent trace, structured data
//   "admin"   -> everything including raw LLM calls
export function renderAgentResult(data, options = {}) {
  const depth = options.depth || "patient";
  let html = `
    <div class="result-header">
      <div class="result-title">
        <h3>${escapeHtml(data.agent_name)}</h3>
        <span class="agent-badge">${agentLabel(data.agent_type)}</span>
      </div>
    </div>

    <div class="result-metrics">
      <div class="metric-card"><span>咨询编号</span><strong>${data.consultation_id ?? "-"}</strong></div>
      <div class="metric-card risk-${data.risk_level}"><span>风险等级</span><strong>${riskLabel(data.risk_level)}</strong></div>
      <div class="metric-card"><span>医生复核</span><strong>${data.doctor_review_required ? "需要" : "暂不需要"}</strong></div>
    </div>

    <div class="result-content">
      <p>${escapeHtml(data.summary)}</p>
    </div>
  `;

  html += renderList("依据摘要", data.evidence);
  html += renderStructuredData(data.structured_data, depth);
  html += renderList("风险提示", data.risk_tips);
  html += renderList("建议下一步", data.next_steps);
  html += renderSources(data.sources);
  if (depth !== "patient") {
    html += renderList("安全标记", data.safety_flags);
    html += renderTrace(data.agent_trace);
  }
  html += `
    <div class="result-section">
      <h4>免责声明</h4>
      <p>${escapeHtml(data.disclaimer)}</p>
    </div>
  `;
  return html;
}

export function renderStructuredData(structured, depth = "patient") {
  if (!structured) return "";
  return `
    ${structured.workflow ? renderWorkflow(structured.workflow) : ""}
    ${structured.triage_report ? renderTriageReport(structured.triage_report) : ""}
    ${structured.medication_check ? renderMedicationCheck(structured.medication_check) : ""}
    ${structured.treatment_comparison ? renderTreatmentComparison(structured.treatment_comparison) : ""}
  `;
}

export function renderWorkflow(workflow) {
  const results = workflow.results || [];
  return `
    <div class="result-section">
      <h4>多智能体协作流程</h4>
      <div class="result-metrics">
        <div class="metric-card"><span>执行链</span><strong>${(workflow.visited_agents || []).join(" → ") || "-"}</strong></div>
        <div class="metric-card"><span>医生复核</span><strong>${workflow.requires_review ? "需要" : "暂不需要"}</strong></div>
        <div class="metric-card"><span>来源数量</span><strong>${(workflow.sources || []).length}</strong></div>
      </div>
      <div class="comparison-list">
        ${results
          .map(
            (item) => `
              <div class="comparison-item">
                <div class="option-name">${escapeHtml(item.agent_name || item.agent_id)}</div>
                <p>${escapeHtml(item.content || item.error || "")}</p>
                ${renderSources(item.sources || item.references || [])}
                ${renderTrace(item.trace || [])}
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

export function renderTriageReport(report) {
  return `
    <div class="result-section">
      <h4>预问诊报告</h4>
      <div class="result-metrics">
        <div class="metric-card"><span>牙位/区域</span><strong>${escapeHtml(report.tooth_position || "-")}</strong></div>
        <div class="metric-card"><span>持续时间</span><strong>${escapeHtml(report.duration_text || "-")}</strong></div>
        <div class="metric-card"><span>疼痛性质</span><strong>${escapeHtml(report.pain_character || "-")}</strong></div>
        <div class="metric-card"><span>紧急程度</span><strong>${escapeHtml(report.urgency_label || report.urgency_level || "-")}</strong></div>
        <div class="metric-card"><span>建议科室</span><strong>${escapeHtml(report.recommended_department || "-")}</strong></div>
        <div class="metric-card"><span>医生复核</span><strong>${report.doctor_review_required ? "建议" : "按需"}</strong></div>
      </div>
      ${renderList("诱因", report.triggers)}
      ${renderList("伴随症状", report.accompanying_symptoms)}
      ${renderObjectList("疑似问题", report.suspected_conditions, "name", "basis")}
    </div>
  `;
}

export function renderMedicationCheck(check) {
  return `
    <div class="result-section">
      <h4>用药审查</h4>
      <p>${escapeHtml(check.compliance_summary)}</p>
      ${renderDrugBlocks(check.checked_drugs)}
      ${renderList("禁忌/高风险", check.contraindications)}
      ${renderList("相互作用提示", check.interactions)}
      ${renderList("需补充核查", check.required_context)}
    </div>
  `;
}

export function renderTreatmentComparison(comparison) {
  return `
    <div class="result-section">
      <h4>方案对比</h4>
      <p>${escapeHtml(comparison.recommendation_note)}</p>
      <div class="comparison-list">
        ${(comparison.comparison || [])
          .map(
            (item) => `
              <div class="comparison-item">
                <div class="option-name">${escapeHtml(item.option_name)} · ${escapeHtml(item.category)}</div>
                <div class="option-stats">
                  <span>疗程: ${escapeHtml(item.duration_note)}</span>
                </div>
                ${renderList("步骤", item.main_steps)}
                <div class="option-pros">优势: ${(item.advantages || []).join(", ")}</div>
                <div class="option-cons">局限: ${(item.disadvantages || []).join(", ")}</div>
                ${renderList("替代方案", item.alternatives)}
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

export function renderDrugBlocks(drugs) {
  if (!drugs || !drugs.length) return "";
  return `
    <div class="drug-list">
      ${drugs
        .map(
          (drug) => `
            <div class="drug-item">
              <div class="drug-name">${escapeHtml(drug.drug_name)} · ${escapeHtml(drug.category)}</div>
              <div>${escapeHtml(drug.dose_note)}</div>
              ${drug.alcohol_warning ? `<div class="drug-risk">${escapeHtml(drug.alcohol_warning)}</div>` : ""}
              ${drug.safety_status === "safe" ? `<div class="drug-safe">用药安全</div>` : ""}
            </div>
          `,
        )
        .join("")}
    </div>
  `;
}

export function renderObjectList(title, items, titleKey, bodyKey) {
  if (!items || !items.length) return "";
  return `
    <div class="result-section">
      ${title ? `<h4>${title}</h4>` : ""}
      <div class="source-list">
        ${items
          .map(
            (item) => `
              <div class="source-item">
                <div class="source-title">${escapeHtml(item[titleKey])}</div>
                <div class="source-excerpt">${escapeHtml(item[bodyKey])}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

export function renderList(title, items) {
  if (!items || !items.length) return "";
  return `
    <div class="result-section">
      <h4>${title}</h4>
      <ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </div>
  `;
}

export function renderSources(sources) {
  if (!sources || !sources.length) return "";
  return `
    <div class="result-section">
      <h4>来源引用</h4>
      <div class="source-list">
        ${sources
          .map(
            (source) => `
              <div class="source-item">
                <div class="source-title">${escapeHtml(source.title)}</div>
                <div class="source-meta">
                  <span>${escapeHtml(source.source)}</span>
                  <span>命中分: ${source.score}</span>
                </div>
                <div class="source-excerpt">${escapeHtml(source.excerpt)}</div>
              </div>
            `,
          )
          .join("")}
      </div>
    </div>
  `;
}

export function renderTrace(trace) {
  if (!trace || !trace.length) return "";
  return `
    <div class="result-section">
      <h4>执行轨迹</h4>
      <div class="trace-list">
        ${trace.map((item, i) => `<div class="trace-item">${i + 1}. ${escapeHtml(item)}</div>`).join("")}
      </div>
    </div>
  `;
}

export function renderLlmCallSection(title, calls, fallbackCall = null) {
  const html = renderLlmCalls(calls, fallbackCall);
  if (!html) return "";
  return `
    <div class="result-section">
      <h4>${escapeHtml(title)}</h4>
      ${html}
    </div>
  `;
}

export function renderLlmCalls(calls, fallbackCall = null) {
  const rows = calls && calls.length ? calls : fallbackCall ? [fallbackCall] : [];
  if (!rows.length) return "<p>暂无模型调用记录</p>";
  return `
    <div class="llm-call-list">
      ${rows
        .map((call, index) => `
          <div class="llm-call-item">
            <div class="source-title">调用 ${index + 1} · ${escapeHtml(call.status || "-")} · ${escapeHtml(call.model_name || "-")}</div>
            <div class="source-meta">
              <span>${escapeHtml(call.provider || "deepseek")}</span>
              <span>延迟 ${escapeHtml(call.latency_ms ?? "-")}ms</span>
              <span>Token ${escapeHtml(call.total_tokens ?? 0)}</span>
              <span>费用 ${escapeHtml(call.estimated_cost ?? 0)}</span>
            </div>
            ${call.error_message ? `<div class="drug-risk">${escapeHtml(call.error_message)}</div>` : ""}
            ${call.response_preview ? `<p>${escapeHtml(call.response_preview)}</p>` : ""}
            <details class="export-details">
              <summary>请求/响应预览</summary>
              <pre>${escapeHtml(JSON.stringify(call, null, 2))}</pre>
            </details>
          </div>
        `)
        .join("")}
    </div>
  `;
}

export function renderReviewStatus(review) {
  return `
    <div class="result-section">
      <h4>医生复核状态</h4>
      <div class="result-metrics compact">
        <div class="metric-card"><span>状态</span><strong>${escapeHtml(review.status)}</strong></div>
        <div class="metric-card"><span>轮次</span><strong>${escapeHtml(review.review_round || "-")}</strong></div>
        <div class="metric-card"><span>模板</span><strong>${escapeHtml(review.review_template || "-")}</strong></div>
      </div>
      ${review.risk_assessment ? `<p>风险评估：${escapeHtml(review.risk_assessment)}</p>` : ""}
      ${review.treatment_decision ? `<p>治疗决策：${escapeHtml(review.treatment_decision)}</p>` : ""}
      ${review.followup_instruction ? `<p>随访说明：${escapeHtml(review.followup_instruction)}</p>` : ""}
      ${review.note ? `<p>备注：${escapeHtml(review.note)}</p>` : ""}
    </div>
  `;
}

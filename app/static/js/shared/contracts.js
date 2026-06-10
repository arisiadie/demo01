// JSDoc typedefs for the core backend response shapes. Zero runtime cost — they
// document the contracts the normalizers (shared/normalizers.js) produce and the
// renderers consume, and give editors autocomplete. Import-free by design.

/**
 * @typedef {Object} AgentResponse
 * @property {number|null} consultation_id
 * @property {string} agent_type
 * @property {string} agent_name
 * @property {string} summary
 * @property {string[]} evidence
 * @property {string[]} risk_tips
 * @property {string[]} next_steps
 * @property {"low"|"medium"|"high"} risk_level
 * @property {boolean} doctor_review_required
 * @property {string} disclaimer
 * @property {Array<Source>} sources
 * @property {string[]} agent_trace
 * @property {string[]} safety_flags
 * @property {Object|null} structured_data
 */

/**
 * @typedef {Object} Source
 * @property {string} title
 * @property {string} source
 * @property {number} score
 * @property {string} excerpt
 */

/**
 * @typedef {Object} ConsultationDetail
 * @property {Object} consultation
 * @property {Object} response
 * @property {Object|null} structured
 * @property {Array<Source>} retrievalHits
 * @property {Array<Object>} llmCalls
 * @property {Object|null} llmCall
 * @property {string[]} trace
 * @property {Object|null} review
 * @property {Array<Object>} uploads
 * @property {string} disclaimer
 * @property {string} summary
 * @property {string} input
 */

/**
 * @typedef {Object} Traceability
 * @property {Object|null} workflow
 * @property {Object|null} rag
 * @property {Object|null} llm
 * @property {Object|null} safety
 * @property {Object|null} persistence
 */

/**
 * @typedef {Object} WorkflowNode
 * @property {string} node_id
 * @property {string} agent_id
 * @property {string} label
 */

/**
 * @typedef {Object} WorkflowEdge
 * @property {string} source
 * @property {string} target
 * @property {string} [label]
 * @property {string} [condition]
 */

/**
 * @typedef {Object} WorkflowConfig
 * @property {string} [name]
 * @property {string} [config_id]
 * @property {boolean} active
 * @property {WorkflowNode[]} nodes
 * @property {WorkflowEdge[]} edges
 * @property {string[]} [visited_agents]
 */

export {}; // module marker; typedefs are ambient

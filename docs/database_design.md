# 口腔医疗平台数据库设计

## 设计目标

数据库用于支撑“生产级内测”的完整闭环：用户与患者档案、五类智能体咨询、医生复核、RAG 来源追踪、Agent 执行轨迹、影像上传占位、健康计划、复诊提醒、动态工作流配置、临床规则库、评测体系、告警处置、隐私合规记录和审计日志。

当前共 33 张表，下文按业务分组说明。表结构以 `sql/init_oralcare_agentic_rag.sql` 与 `app/models/entities.py` 为准。

## 表结构分组

用户与档案：

- `users`：患者、医生、管理员三类角色。
- `patient_profiles`：患者年龄、妊娠状态、过敏史、基础病和口腔病史，通过 `user_external_id` 关联 `users.external_id`。

咨询主流程：

- `consultations`：每次用户咨询的主记录，保存输入、脱敏输入、摘要、风险等级、状态和完整 JSON 结果。
- `agent_runs`：一次咨询对应一次 Agent 执行，保存 Agent 类型、名称、安全标记和执行轨迹。
- `doctor_reviews`：需要医生复核的咨询会生成复核任务，保存复核模板、结构化意见、医生签名、随访、升级复核和闭环时间。
- `triage_reports`：预问诊结构化报告，保存牙位、疼痛特点、紧急程度和建议科室。
- `medication_checks`：用药合规审查结果，保存核查药物、禁忌、相互作用和结构化报告。
- `treatment_comparisons`：诊疗方案对比结果，保存匹配方案、步骤、费用因素和替代方案。

RAG 与知识库：

- `knowledge_versions`：知识库版本、文档数量、检索后端和质量分。
- `knowledge_documents`：结构化保存示例指南、用药规则、病例/科普文档。
- `knowledge_change_logs`：管理员新增、编辑、下线知识文档的变更记录。
- `retrieval_hits`：每次咨询实际命中的知识片段、分数、排名和摘录，连接 `consultations` 与 `knowledge_documents`。

临床规则库（智能体结构化审查的确定性依据）：

- `medication_rules`：用药合规审查智能体的药物规则库，保存药名、别名、分类、禁忌、相互作用、特殊人群和剂量说明。
- `treatment_options`：诊疗方案解读智能体的方案库，保存方案名称、分类、匹配关键词、治疗步骤、疗程、费用因素和优缺点。

评测体系（RAG 与意图路由的离线评测）：

- `evaluation_cases`：评测用例，保存用例 ID、标题、评测类型、目标智能体、输入消息和期望结果。
- `evaluation_runs`：一次评测运行的汇总，保存运行 ID、状态、触发人、用例总数、通过/失败数和指标。
- `evaluation_results`：单条用例的评测明细，关联 `evaluation_runs`，保存是否通过、命中情况和详情。

扩展业务：

- `uploaded_files`：影像图片或 PDF 的上传占位记录，只做归档和预览，不做真实影像诊断。
- `treatment_records`：患者治疗历史，按牙位记录诊断、治疗、费用、医生和复诊时间。
- `tooth_records`：牙位级长期档案，保存牙位状态、治疗摘要、维护周期和下次检查时间。
- `health_plans`：健康管理 Agent 生成的个性化口腔维护计划。
- `follow_up_reminders`：复诊、医生复核或日常维护提醒。
- `notifications`：站内通知与到期推送结果，支持手动扫描和后台周期扫描。
- `audit_logs`：关键操作审计，包括咨询创建、影像分析、复核更新等。
- `llm_call_logs`：DeepSeek 调用日志，保存模型、状态、延迟、token、估算费用、错误信息和请求/响应摘要。
- `alert_dismissals`：管理员对异常告警（复核逾期、高风险未闭环、LLM 异常等）的处置/忽略记录。

动态工作流：

- `workflow_configs`：管理员维护的多智能体工作流配置，默认配置 ID 为 `default`。
- `workflow_nodes`：工作流节点，关联具体 Agent、路由、医生复核或结束节点。
- `workflow_edges`：工作流有向边，定义 Agent 之间的可配置交接关系。

隐私与合规：

- `patient_consents`：患者 AI 辅助服务知情同意、版本、范围、签名和有效期。
- `data_access_requests`：患者数据导出/删除申请及管理员处理结果。
- `privacy_impact_assessments`：管理员维护的隐私影响评估记录。
- `data_retention_policies`：各类数据的保留期限、自动删除和归档策略。

## 核心连接关系

- `users.id -> consultations.user_id`
- `users.external_id -> patient_profiles.user_external_id`
- `consultations.id -> doctor_reviews.consultation_id`
- `consultations.id -> agent_runs.consultation_id`
- `consultations.id -> triage_reports.consultation_id`
- `consultations.id -> medication_checks.consultation_id`
- `consultations.id -> treatment_comparisons.consultation_id`
- `knowledge_versions.id -> knowledge_documents.knowledge_version_id`
- `knowledge_documents.id -> knowledge_change_logs.knowledge_document_id`
- `consultations.id -> retrieval_hits.consultation_id`
- `knowledge_documents.id -> retrieval_hits.knowledge_document_id`
- `consultations.id -> uploaded_files.consultation_id`
- `users.id -> uploaded_files.user_id`
- `users.id -> treatment_records.user_id`
- `users.id -> tooth_records.user_id`
- `consultations.id -> health_plans.consultation_id`
- `consultations.id -> follow_up_reminders.consultation_id`
- `users.external_id -> patient_consents.user_external_id`
- `users.external_id -> data_access_requests.user_external_id`
- `workflow_configs.id -> workflow_nodes.config_id`
- `workflow_configs.id -> workflow_edges.config_id`
- `evaluation_runs.id -> evaluation_results.run_db_id`
- `evaluation_cases.id -> evaluation_results.case_db_id`

## 项目连接方式

项目通过 `.env` 中的 `DATABASE_URL` 连接 MySQL：

```text
mysql+pymysql://root:123456@127.0.0.1:3306/oralcare_agentic_rag?charset=utf8mb4
```

FastAPI 启动时会读取 `.env`，`app/core/database.py` 使用 SQLAlchemy 创建连接池。初始化脚本为 `sql/init_oralcare_agentic_rag.sql`。

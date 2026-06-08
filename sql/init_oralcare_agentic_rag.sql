CREATE DATABASE IF NOT EXISTS `oralcare_agentic_rag`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `oralcare_agentic_rag`;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE IF NOT EXISTS `users` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `external_id` VARCHAR(80) NOT NULL,
  `role` VARCHAR(20) NOT NULL,
  `display_name` VARCHAR(80) NOT NULL,
  `password_hash` VARCHAR(255) NULL,
  `active` BOOL NOT NULL DEFAULT 1,
  `last_login_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_users_external_id` (`external_id`),
  KEY `ix_users_id` (`id`),
  KEY `ix_users_external_id` (`external_id`),
  KEY `ix_users_role` (`role`),
  KEY `ix_users_active` (`active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `patient_profiles` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_external_id` VARCHAR(80) NOT NULL,
  `name` VARCHAR(80) NOT NULL DEFAULT '内测用户',
  `age` INT NULL,
  `sex` VARCHAR(20) NULL,
  `pregnancy_status` VARCHAR(40) NULL,
  `allergies` TEXT NULL,
  `conditions` TEXT NULL,
  `oral_history` TEXT NULL,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_patient_profiles_id` (`id`),
  KEY `ix_patient_profiles_user_external_id` (`user_external_id`),
  CONSTRAINT `fk_patient_profiles_user_external_id_users`
    FOREIGN KEY (`user_external_id`) REFERENCES `users` (`external_id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `consultations` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT NOT NULL,
  `patient_external_id` VARCHAR(80) NOT NULL,
  `agent_type` VARCHAR(40) NOT NULL,
  `input_text` TEXT NOT NULL,
  `sanitized_input` TEXT NOT NULL,
  `summary` TEXT NOT NULL,
  `risk_level` VARCHAR(20) NOT NULL,
  `sources_json` TEXT NOT NULL,
  `result_json` TEXT NOT NULL,
  `doctor_review_required` BOOL NOT NULL DEFAULT 0,
  `status` VARCHAR(30) NOT NULL DEFAULT 'completed',
  `image_path` TEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_consultations_id` (`id`),
  KEY `ix_consultations_user_id` (`user_id`),
  KEY `ix_consultations_patient_external_id` (`patient_external_id`),
  KEY `ix_consultations_agent_type` (`agent_type`),
  KEY `ix_consultations_risk_level` (`risk_level`),
  KEY `ix_consultations_doctor_review_required` (`doctor_review_required`),
  KEY `ix_consultations_status` (`status`),
  KEY `ix_consultations_created_at` (`created_at`),
  CONSTRAINT `fk_consultations_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `doctor_reviews` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NOT NULL,
  `assigned_role` VARCHAR(20) NOT NULL DEFAULT 'doctor',
  `status` VARCHAR(30) NOT NULL DEFAULT 'pending',
  `review_template` VARCHAR(80) NULL,
  `structured_opinion_json` TEXT NOT NULL,
  `risk_assessment` TEXT NULL,
  `treatment_decision` VARCHAR(80) NULL,
  `signature` VARCHAR(80) NULL,
  `signature_title` VARCHAR(120) NULL,
  `due_by` DATETIME NULL,
  `review_round` INT NOT NULL DEFAULT 1,
  `followup_needed` BOOL NOT NULL DEFAULT 0,
  `followup_instruction` TEXT NULL,
  `escalation_note` TEXT NULL,
  `closed_at` DATETIME NULL,
  `note` TEXT NULL,
  `reviewed_by` VARCHAR(80) NULL,
  `reviewed_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_doctor_reviews_consultation_id` (`consultation_id`),
  KEY `ix_doctor_reviews_id` (`id`),
  KEY `ix_doctor_reviews_status` (`status`),
  KEY `ix_doctor_reviews_due_by` (`due_by`),
  KEY `ix_doctor_reviews_review_round` (`review_round`),
  CONSTRAINT `fk_doctor_reviews_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `triage_reports` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NOT NULL,
  `tooth_position` VARCHAR(80) NULL,
  `duration_text` VARCHAR(120) NULL,
  `pain_character` VARCHAR(160) NULL,
  `triggers_json` TEXT NOT NULL,
  `accompanying_symptoms_json` TEXT NOT NULL,
  `suspected_conditions_json` TEXT NOT NULL,
  `urgency_level` VARCHAR(20) NOT NULL DEFAULT 'routine',
  `recommended_department` VARCHAR(80) NOT NULL DEFAULT '口腔科',
  `report_json` TEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_triage_reports_consultation_id` (`consultation_id`),
  KEY `ix_triage_reports_id` (`id`),
  KEY `ix_triage_reports_consultation_id` (`consultation_id`),
  KEY `ix_triage_reports_urgency_level` (`urgency_level`),
  KEY `ix_triage_reports_recommended_department` (`recommended_department`),
  KEY `ix_triage_reports_created_at` (`created_at`),
  CONSTRAINT `fk_triage_reports_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `medication_rules` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `drug_name` VARCHAR(120) NOT NULL,
  `aliases_json` TEXT NOT NULL,
  `category` VARCHAR(80) NOT NULL,
  `contraindications_json` TEXT NOT NULL,
  `interactions_json` TEXT NOT NULL,
  `special_populations_json` TEXT NOT NULL,
  `dose_note` TEXT NOT NULL,
  `alcohol_warning` TEXT NOT NULL,
  `active` BOOL NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_medication_rules_drug_name` (`drug_name`),
  KEY `ix_medication_rules_id` (`id`),
  KEY `ix_medication_rules_drug_name` (`drug_name`),
  KEY `ix_medication_rules_category` (`category`),
  KEY `ix_medication_rules_active` (`active`),
  KEY `ix_medication_rules_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `medication_checks` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NOT NULL,
  `checked_drugs_json` TEXT NOT NULL,
  `risk_points_json` TEXT NOT NULL,
  `contraindications_json` TEXT NOT NULL,
  `interactions_json` TEXT NOT NULL,
  `compliance_summary` TEXT NOT NULL,
  `review_required` BOOL NOT NULL DEFAULT 1,
  `report_json` TEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_medication_checks_consultation_id` (`consultation_id`),
  KEY `ix_medication_checks_id` (`id`),
  KEY `ix_medication_checks_consultation_id` (`consultation_id`),
  KEY `ix_medication_checks_review_required` (`review_required`),
  KEY `ix_medication_checks_created_at` (`created_at`),
  CONSTRAINT `fk_medication_checks_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `treatment_options` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `option_name` VARCHAR(120) NOT NULL,
  `category` VARCHAR(80) NOT NULL,
  `keywords_json` TEXT NOT NULL,
  `steps_json` TEXT NOT NULL,
  `duration_note` TEXT NOT NULL,
  `cost_factors_json` TEXT NOT NULL,
  `advantages_json` TEXT NOT NULL,
  `disadvantages_json` TEXT NOT NULL,
  `alternatives_json` TEXT NOT NULL,
  `active` BOOL NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_treatment_options_option_name` (`option_name`),
  KEY `ix_treatment_options_id` (`id`),
  KEY `ix_treatment_options_option_name` (`option_name`),
  KEY `ix_treatment_options_category` (`category`),
  KEY `ix_treatment_options_active` (`active`),
  KEY `ix_treatment_options_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `treatment_comparisons` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NOT NULL,
  `matched_options_json` TEXT NOT NULL,
  `comparison_json` TEXT NOT NULL,
  `recommendation_note` TEXT NOT NULL,
  `report_json` TEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_treatment_comparisons_consultation_id` (`consultation_id`),
  KEY `ix_treatment_comparisons_id` (`id`),
  KEY `ix_treatment_comparisons_consultation_id` (`consultation_id`),
  KEY `ix_treatment_comparisons_created_at` (`created_at`),
  CONSTRAINT `fk_treatment_comparisons_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `audit_logs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `actor_external_id` VARCHAR(80) NOT NULL,
  `actor_role` VARCHAR(20) NOT NULL,
  `action` VARCHAR(80) NOT NULL,
  `resource_type` VARCHAR(80) NOT NULL,
  `resource_id` VARCHAR(80) NULL,
  `risk_level` VARCHAR(20) NOT NULL DEFAULT 'low',
  `detail_json` TEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_audit_logs_id` (`id`),
  KEY `ix_audit_logs_actor_external_id` (`actor_external_id`),
  KEY `ix_audit_logs_actor_role` (`actor_role`),
  KEY `ix_audit_logs_action` (`action`),
  KEY `ix_audit_logs_risk_level` (`risk_level`),
  KEY `ix_audit_logs_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `llm_call_logs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NULL,
  `provider` VARCHAR(40) NOT NULL DEFAULT 'deepseek',
  `model_name` VARCHAR(80) NOT NULL,
  `status` VARCHAR(30) NOT NULL,
  `latency_ms` INT NOT NULL DEFAULT 0,
  `prompt_tokens` INT NOT NULL DEFAULT 0,
  `completion_tokens` INT NOT NULL DEFAULT 0,
  `total_tokens` INT NOT NULL DEFAULT 0,
  `estimated_cost` FLOAT NOT NULL DEFAULT 0,
  `request_preview` TEXT NOT NULL,
  `response_preview` TEXT NULL,
  `error_message` TEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_llm_call_logs_id` (`id`),
  KEY `ix_llm_call_logs_consultation_id` (`consultation_id`),
  KEY `ix_llm_call_logs_provider` (`provider`),
  KEY `ix_llm_call_logs_model_name` (`model_name`),
  KEY `ix_llm_call_logs_status` (`status`),
  KEY `ix_llm_call_logs_latency_ms` (`latency_ms`),
  KEY `ix_llm_call_logs_created_at` (`created_at`),
  CONSTRAINT `fk_llm_call_logs_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `knowledge_versions` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `version` VARCHAR(40) NOT NULL,
  `title` VARCHAR(120) NOT NULL,
  `document_count` INT NOT NULL,
  `retrieval_backend` VARCHAR(40) NOT NULL DEFAULT 'local-hybrid',
  `quality_score` FLOAT NOT NULL DEFAULT 0,
  `active` BOOL NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_knowledge_versions_version` (`version`),
  KEY `ix_knowledge_versions_id` (`id`),
  KEY `ix_knowledge_versions_version` (`version`),
  KEY `ix_knowledge_versions_active` (`active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `knowledge_documents` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `knowledge_version_id` INT NULL,
  `doc_uid` VARCHAR(120) NOT NULL,
  `title` VARCHAR(160) NOT NULL,
  `category` VARCHAR(40) NOT NULL,
  `source` VARCHAR(160) NOT NULL,
  `tags_json` TEXT NOT NULL,
  `content` TEXT NOT NULL,
  `active` BOOL NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_knowledge_documents_doc_uid` (`doc_uid`),
  KEY `ix_knowledge_documents_id` (`id`),
  KEY `ix_knowledge_documents_knowledge_version_id` (`knowledge_version_id`),
  KEY `ix_knowledge_documents_doc_uid` (`doc_uid`),
  KEY `ix_knowledge_documents_title` (`title`),
  KEY `ix_knowledge_documents_category` (`category`),
  KEY `ix_knowledge_documents_active` (`active`),
  CONSTRAINT `fk_knowledge_documents_version_id_knowledge_versions`
    FOREIGN KEY (`knowledge_version_id`) REFERENCES `knowledge_versions` (`id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `knowledge_change_logs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `knowledge_document_id` INT NULL,
  `actor_external_id` VARCHAR(80) NOT NULL,
  `action` VARCHAR(40) NOT NULL,
  `before_json` TEXT NULL,
  `after_json` TEXT NULL,
  `note` TEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_knowledge_change_logs_id` (`id`),
  KEY `ix_knowledge_change_logs_knowledge_document_id` (`knowledge_document_id`),
  KEY `ix_knowledge_change_logs_actor_external_id` (`actor_external_id`),
  KEY `ix_knowledge_change_logs_action` (`action`),
  KEY `ix_knowledge_change_logs_created_at` (`created_at`),
  CONSTRAINT `fk_knowledge_change_logs_document_id_knowledge_documents`
    FOREIGN KEY (`knowledge_document_id`) REFERENCES `knowledge_documents` (`id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `patient_consents` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_external_id` VARCHAR(80) NOT NULL,
  `consent_type` VARCHAR(40) NOT NULL,
  `consent_version` VARCHAR(40) NOT NULL,
  `scope` VARCHAR(160) NOT NULL,
  `consented` BOOL NOT NULL DEFAULT 0,
  `consent_text` TEXT NOT NULL,
  `signature` VARCHAR(80) NULL,
  `signed_at` DATETIME NULL,
  `expires_at` DATETIME NULL,
  `revoked_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_patient_consents_id` (`id`),
  KEY `ix_patient_consents_user_external_id` (`user_external_id`),
  KEY `ix_patient_consents_consent_type` (`consent_type`),
  CONSTRAINT `fk_patient_consents_user_external_id_users`
    FOREIGN KEY (`user_external_id`) REFERENCES `users` (`external_id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `data_access_requests` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_external_id` VARCHAR(80) NOT NULL,
  `request_type` VARCHAR(40) NOT NULL,
  `status` VARCHAR(30) NOT NULL DEFAULT 'pending',
  `data_scope` VARCHAR(200) NOT NULL,
  `reason` TEXT NULL,
  `processed_by` VARCHAR(80) NULL,
  `processed_at` DATETIME NULL,
  `result_data` TEXT NULL,
  `note` TEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_data_access_requests_id` (`id`),
  KEY `ix_data_access_requests_user_external_id` (`user_external_id`),
  KEY `ix_data_access_requests_request_type` (`request_type`),
  KEY `ix_data_access_requests_status` (`status`),
  KEY `ix_data_access_requests_created_at` (`created_at`),
  CONSTRAINT `fk_data_access_requests_user_external_id_users`
    FOREIGN KEY (`user_external_id`) REFERENCES `users` (`external_id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `privacy_impact_assessments` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `assessment_id` VARCHAR(80) NOT NULL,
  `title` VARCHAR(160) NOT NULL,
  `description` TEXT NOT NULL,
  `data_types` TEXT NOT NULL,
  `risk_level` VARCHAR(20) NOT NULL DEFAULT 'low',
  `mitigation_measures` TEXT NOT NULL,
  `compliance_status` VARCHAR(30) NOT NULL DEFAULT 'pending',
  `reviewed_by` VARCHAR(80) NULL,
  `reviewed_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_privacy_impact_assessments_assessment_id` (`assessment_id`),
  KEY `ix_privacy_impact_assessments_id` (`id`),
  KEY `ix_privacy_impact_assessments_assessment_id` (`assessment_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `data_retention_policies` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `data_category` VARCHAR(80) NOT NULL,
  `retention_days` INT NOT NULL,
  `description` TEXT NULL,
  `auto_delete` BOOL NOT NULL DEFAULT 1,
  `archived` BOOL NOT NULL DEFAULT 0,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_data_retention_policies_data_category` (`data_category`),
  KEY `ix_data_retention_policies_id` (`id`),
  KEY `ix_data_retention_policies_data_category` (`data_category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `agent_runs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NOT NULL,
  `agent_type` VARCHAR(40) NOT NULL,
  `agent_name` VARCHAR(80) NOT NULL,
  `risk_level` VARCHAR(20) NOT NULL,
  `refusal` BOOL NOT NULL DEFAULT 0,
  `safety_flags_json` TEXT NOT NULL,
  `trace_json` TEXT NOT NULL,
  `started_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `completed_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_agent_runs_consultation_id` (`consultation_id`),
  KEY `ix_agent_runs_id` (`id`),
  KEY `ix_agent_runs_consultation_id` (`consultation_id`),
  KEY `ix_agent_runs_agent_type` (`agent_type`),
  KEY `ix_agent_runs_risk_level` (`risk_level`),
  KEY `ix_agent_runs_refusal` (`refusal`),
  CONSTRAINT `fk_agent_runs_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `retrieval_hits` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NOT NULL,
  `knowledge_document_id` INT NULL,
  `document_uid` VARCHAR(120) NOT NULL,
  `title` VARCHAR(160) NOT NULL,
  `category` VARCHAR(40) NOT NULL,
  `source` VARCHAR(160) NOT NULL,
  `score` FLOAT NOT NULL DEFAULT 0,
  `rank` INT NOT NULL DEFAULT 0,
  `excerpt` TEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_retrieval_hits_id` (`id`),
  KEY `ix_retrieval_hits_consultation_id` (`consultation_id`),
  KEY `ix_retrieval_hits_knowledge_document_id` (`knowledge_document_id`),
  KEY `ix_retrieval_hits_document_uid` (`document_uid`),
  KEY `ix_retrieval_hits_category` (`category`),
  KEY `ix_retrieval_hits_score` (`score`),
  KEY `ix_retrieval_hits_created_at` (`created_at`),
  CONSTRAINT `fk_retrieval_hits_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE,
  CONSTRAINT `fk_retrieval_hits_knowledge_document_id_knowledge_documents`
    FOREIGN KEY (`knowledge_document_id`) REFERENCES `knowledge_documents` (`id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `uploaded_files` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NULL,
  `user_id` INT NOT NULL,
  `original_name` VARCHAR(255) NOT NULL,
  `stored_path` TEXT NOT NULL,
  `mime_type` VARCHAR(120) NULL,
  `file_size` INT NOT NULL DEFAULT 0,
  `purpose` VARCHAR(40) NOT NULL DEFAULT 'imaging',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_uploaded_files_id` (`id`),
  KEY `ix_uploaded_files_consultation_id` (`consultation_id`),
  KEY `ix_uploaded_files_user_id` (`user_id`),
  KEY `ix_uploaded_files_created_at` (`created_at`),
  CONSTRAINT `fk_uploaded_files_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL,
  CONSTRAINT `fk_uploaded_files_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `treatment_records` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT NOT NULL,
  `user_external_id` VARCHAR(80) NOT NULL,
  `consultation_id` INT NULL,
  `tooth_position` VARCHAR(80) NULL,
  `diagnosis_text` TEXT NOT NULL,
  `treatment_name` VARCHAR(120) NOT NULL,
  `treatment_date` DATETIME NULL,
  `doctor_name` VARCHAR(80) NULL,
  `institution` VARCHAR(160) NULL,
  `cost_amount` FLOAT NULL,
  `next_visit_at` DATETIME NULL,
  `note` TEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_treatment_records_id` (`id`),
  KEY `ix_treatment_records_user_id` (`user_id`),
  KEY `ix_treatment_records_user_external_id` (`user_external_id`),
  KEY `ix_treatment_records_consultation_id` (`consultation_id`),
  KEY `ix_treatment_records_treatment_name` (`treatment_name`),
  KEY `ix_treatment_records_treatment_date` (`treatment_date`),
  KEY `ix_treatment_records_next_visit_at` (`next_visit_at`),
  KEY `ix_treatment_records_created_at` (`created_at`),
  CONSTRAINT `fk_treatment_records_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT,
  CONSTRAINT `fk_treatment_records_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `tooth_records` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_id` INT NOT NULL,
  `user_external_id` VARCHAR(80) NOT NULL,
  `tooth_position` VARCHAR(40) NOT NULL,
  `status` VARCHAR(80) NOT NULL DEFAULT '观察',
  `diagnosis_text` TEXT NULL,
  `treatment_summary` TEXT NULL,
  `maintenance_cycle_days` INT NOT NULL DEFAULT 180,
  `next_check_at` DATETIME NULL,
  `note` TEXT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_tooth_records_id` (`id`),
  KEY `ix_tooth_records_user_id` (`user_id`),
  KEY `ix_tooth_records_user_external_id` (`user_external_id`),
  KEY `ix_tooth_records_tooth_position` (`tooth_position`),
  KEY `ix_tooth_records_status` (`status`),
  KEY `ix_tooth_records_next_check_at` (`next_check_at`),
  KEY `ix_tooth_records_created_at` (`created_at`),
  CONSTRAINT `fk_tooth_records_user_id_users`
    FOREIGN KEY (`user_id`) REFERENCES `users` (`id`)
    ON UPDATE CASCADE
    ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `health_plans` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NOT NULL,
  `user_external_id` VARCHAR(80) NOT NULL,
  `plan_type` VARCHAR(40) NOT NULL DEFAULT 'oral_health',
  `plan_json` TEXT NOT NULL,
  `status` VARCHAR(30) NOT NULL DEFAULT 'active',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_health_plans_id` (`id`),
  KEY `ix_health_plans_consultation_id` (`consultation_id`),
  KEY `ix_health_plans_user_external_id` (`user_external_id`),
  KEY `ix_health_plans_plan_type` (`plan_type`),
  KEY `ix_health_plans_status` (`status`),
  KEY `ix_health_plans_created_at` (`created_at`),
  CONSTRAINT `fk_health_plans_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `follow_up_reminders` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `consultation_id` INT NULL,
  `user_external_id` VARCHAR(80) NOT NULL,
  `reminder_type` VARCHAR(40) NOT NULL,
  `due_at` DATETIME NULL,
  `status` VARCHAR(30) NOT NULL DEFAULT 'pending',
  `note` TEXT NOT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_follow_up_reminders_id` (`id`),
  KEY `ix_follow_up_reminders_consultation_id` (`consultation_id`),
  KEY `ix_follow_up_reminders_user_external_id` (`user_external_id`),
  KEY `ix_follow_up_reminders_reminder_type` (`reminder_type`),
  KEY `ix_follow_up_reminders_due_at` (`due_at`),
  KEY `ix_follow_up_reminders_status` (`status`),
  KEY `ix_follow_up_reminders_created_at` (`created_at`),
  CONSTRAINT `fk_follow_up_reminders_consultation_id_consultations`
    FOREIGN KEY (`consultation_id`) REFERENCES `consultations` (`id`)
    ON UPDATE CASCADE
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `notifications` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `user_external_id` VARCHAR(80) NOT NULL,
  `channel` VARCHAR(40) NOT NULL DEFAULT 'in_app',
  `title` VARCHAR(160) NOT NULL,
  `content` TEXT NOT NULL,
  `status` VARCHAR(30) NOT NULL DEFAULT 'unread',
  `scheduled_at` DATETIME NULL,
  `sent_at` DATETIME NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_notifications_id` (`id`),
  KEY `ix_notifications_user_external_id` (`user_external_id`),
  KEY `ix_notifications_channel` (`channel`),
  KEY `ix_notifications_status` (`status`),
  KEY `ix_notifications_scheduled_at` (`scheduled_at`),
  KEY `ix_notifications_sent_at` (`sent_at`),
  KEY `ix_notifications_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `workflow_configs` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `config_id` VARCHAR(80) NOT NULL,
  `name` VARCHAR(120) NOT NULL,
  `description` TEXT NULL,
  `active` BOOL NOT NULL DEFAULT 1,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_workflow_configs_config_id` (`config_id`),
  KEY `ix_workflow_configs_id` (`id`),
  KEY `ix_workflow_configs_config_id` (`config_id`),
  KEY `ix_workflow_configs_active` (`active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `workflow_nodes` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `config_id` INT NOT NULL,
  `node_id` VARCHAR(80) NOT NULL,
  `agent_id` VARCHAR(80) NOT NULL,
  `label` VARCHAR(120) NOT NULL,
  `type` VARCHAR(40) NOT NULL DEFAULT 'agent',
  `position_x` INT NOT NULL DEFAULT 0,
  `position_y` INT NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `ix_workflow_nodes_id` (`id`),
  KEY `ix_workflow_nodes_config_id` (`config_id`),
  KEY `ix_workflow_nodes_node_id` (`node_id`),
  CONSTRAINT `fk_workflow_nodes_config_id_workflow_configs`
    FOREIGN KEY (`config_id`) REFERENCES `workflow_configs` (`id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `workflow_edges` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `config_id` INT NOT NULL,
  `source` VARCHAR(80) NOT NULL,
  `target` VARCHAR(80) NOT NULL,
  `condition` TEXT NULL,
  `label` VARCHAR(120) NULL,
  PRIMARY KEY (`id`),
  KEY `ix_workflow_edges_id` (`id`),
  KEY `ix_workflow_edges_config_id` (`config_id`),
  KEY `ix_workflow_edges_source` (`source`),
  KEY `ix_workflow_edges_target` (`target`),
  CONSTRAINT `fk_workflow_edges_config_id_workflow_configs`
    FOREIGN KEY (`config_id`) REFERENCES `workflow_configs` (`id`)
    ON UPDATE CASCADE
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `knowledge_versions`
  (`version`, `title`, `document_count`, `retrieval_backend`, `quality_score`, `active`)
VALUES
  ('production-v1.0', '口腔医疗生产级知识库', 54, 'local-hybrid', 0.93, 1)
ON DUPLICATE KEY UPDATE
  `title` = VALUES(`title`),
  `document_count` = VALUES(`document_count`),
  `retrieval_backend` = VALUES(`retrieval_backend`),
  `quality_score` = VALUES(`quality_score`),
  `active` = VALUES(`active`);

SET FOREIGN_KEY_CHECKS = 1;

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.rag.chroma_index import ChromaKnowledgeIndex


TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    title: str
    category: str
    source: str
    tags: list[str]
    content: str


@dataclass(frozen=True)
class RetrievalHit:
    document: KnowledgeDocument
    score: float
    excerpt: str

    def as_source(self) -> dict[str, object]:
        return {
            "id": self.document.id,
            "title": self.document.title,
            "category": self.document.category,
            "source": self.document.source,
            "score": round(self.score, 3),
            "excerpt": self.excerpt,
        }


class KnowledgeStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or settings.resolved_knowledge_path
        self.version = "unknown"
        self.title = "口腔示例知识库"
        self.documents: list[KnowledgeDocument] = []
        self._base_documents: list[KnowledgeDocument] = []
        self._admin_documents: list[KnowledgeDocument] = []
        self._doc_by_id: dict[str, KnowledgeDocument] = {}
        self._chroma: ChromaKnowledgeIndex | None = None
        self._chroma_error: str | None = None
        self._load()
        self._init_chroma()

    def _load(self) -> None:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.version = payload.get("version", "unknown")
        self.title = payload.get("title", "口腔示例知识库")
        self._base_documents = [
            KnowledgeDocument(
                id=item["id"],
                title=item["title"],
                category=item["category"],
                source=item["source"],
                tags=list(item.get("tags", [])),
                content=item["content"],
            )
            for item in payload.get("documents", [])
        ]
        self._rebuild_documents()

    def sync_admin_documents(self, documents: list[KnowledgeDocument]) -> None:
        self._admin_documents = documents
        self._rebuild_documents()
        if self._chroma is not None:
            try:
                self._chroma.ensure_indexed(self.documents, self.version)
            except Exception as exc:
                self._chroma_error = str(exc)

    def _rebuild_documents(self) -> None:
        merged: dict[str, KnowledgeDocument] = {}
        for doc in self._base_documents + self._admin_documents:
            merged[doc.id] = doc
        self.documents = list(merged.values())
        self._doc_by_id = {doc.id: doc for doc in self.documents}

    def _init_chroma(self) -> None:
        try:
            self._chroma = ChromaKnowledgeIndex()
            self._chroma.ensure_indexed(self.documents, self.version)
        except Exception as exc:
            self._chroma = None
            self._chroma_error = str(exc)

    @property
    def backend_name(self) -> str:
        if self._chroma is None:
            return "local-hybrid"
        return "chroma-persistent"

    def retrieve(self, query: str, categories: list[str] | None = None, top_k: int = 5) -> list[RetrievalHit]:
        categories = categories or []
        chroma_hits = self._retrieve_chroma(query, categories=categories, top_k=max(top_k * 3, top_k))
        local_hits = self.retrieve_local(query, categories=categories, top_k=max(top_k * 3, top_k))
        if not chroma_hits:
            return local_hits[:top_k]
        return self._rerank_hits(query, categories, chroma_hits, local_hits)[:top_k]

    def retrieve_local(self, query: str, categories: list[str] | None = None, top_k: int = 5) -> list[RetrievalHit]:
        categories = categories or []
        query_tokens = _tokenize(query)
        query_lower = query.lower()
        hits: list[RetrievalHit] = []

        for doc in self.documents:
            if categories and doc.category not in categories and doc.category != "safety":
                continue

            score = self._score_document(doc, query_lower, query_tokens)
            if score <= 0:
                continue
            hits.append(RetrievalHit(document=doc, score=score, excerpt=_excerpt(doc.content, query_tokens)))

        hits.sort(key=lambda hit: hit.score, reverse=True)
        return hits[:top_k]

    def _retrieve_chroma(self, query: str, categories: list[str] | None = None, top_k: int = 5) -> list[RetrievalHit]:
        if self._chroma is None:
            return []
        try:
            raw_hits = self._chroma.query(query, categories=categories, top_k=top_k)
        except Exception as exc:
            self._chroma_error = str(exc)
            return []
        hits: list[RetrievalHit] = []
        for raw in raw_hits:
            doc = self._doc_by_id.get(raw.doc_id)
            if doc is None:
                continue
            hits.append(RetrievalHit(document=doc, score=raw.score, excerpt=raw.excerpt))
        return hits

    def _rerank_hits(
        self,
        query: str,
        categories: list[str],
        chroma_hits: list[RetrievalHit],
        local_hits: list[RetrievalHit],
    ) -> list[RetrievalHit]:
        query_lower = query.lower()
        query_tokens = _tokenize(query)
        combined: dict[str, RetrievalHit] = {hit.document.id: hit for hit in chroma_hits}
        for hit in local_hits:
            current = combined.get(hit.document.id)
            if current is None or hit.score > current.score:
                combined[hit.document.id] = hit

        local_score_by_id = {hit.document.id: hit.score for hit in local_hits}
        chroma_rank_by_id = {hit.document.id: index for index, hit in enumerate(chroma_hits, start=1)}
        local_rank_by_id = {hit.document.id: index for index, hit in enumerate(local_hits, start=1)}

        def score(hit: RetrievalHit) -> float:
            doc = hit.document
            lexical = self._score_document(doc, query_lower, query_tokens)
            chroma_rank_bonus = 1 / chroma_rank_by_id[doc.id] if doc.id in chroma_rank_by_id else 0
            local_rank_bonus = 1 / local_rank_by_id[doc.id] if doc.id in local_rank_by_id else 0
            category_bonus = 0.8 if categories and doc.category in categories else 0.0
            safety_bonus = 0.4 if doc.category == "safety" and "safety" in categories else 0.0
            safety_penalty = -1.0 if doc.category == "safety" and categories and "safety" not in categories else 0.0
            local_score = local_score_by_id.get(doc.id, 0.0)
            return (
                (lexical * 8.0)
                + (local_score * 3.0)
                + chroma_rank_bonus
                + local_rank_bonus
                + category_bonus
                + safety_bonus
                + safety_penalty
            )

        reranked = sorted(combined.values(), key=score, reverse=True)
        return [
            RetrievalHit(
                document=hit.document,
                score=max(hit.score, round(score(hit), 6)),
                excerpt=_excerpt(hit.document.content, query_tokens),
            )
            for hit in reranked
        ]

    def quality_metrics(self) -> dict[str, object]:
        category_counts: dict[str, int] = {}
        for doc in self.documents:
            category_counts[doc.category] = category_counts.get(doc.category, 0) + 1
        coverage = len(category_counts) / 6
        avg_tags = sum(len(doc.tags) for doc in self.documents) / max(len(self.documents), 1)
        quality_score = min(1.0, round((coverage * 0.55) + (min(avg_tags, 6) / 6 * 0.45), 3))
        return {
            "version": self.version,
            "title": self.title,
            "document_count": len(self.documents),
            "category_counts": category_counts,
            "retrieval_backend": self.backend_name,
            "chroma_path": str(settings.resolved_chroma_path),
            "chroma_error": self._chroma_error,
            "quality_score": quality_score,
        }

    def evaluate_recall(self) -> dict[str, object]:
        cases = [
            # 分诊类
            {"query": "夜间牙痛 冷热刺激痛", "categories": ["triage"], "expected_doc_ids": ["triage-caries-pulpitis-001"], "difficulty": "easy"},
            {"query": "牙龈出血 口臭 牙齿松动", "categories": ["triage"], "expected_doc_ids": ["triage-periodontal-001"], "difficulty": "easy"},
            {"query": "智齿发炎 张口受限 面部肿胀", "categories": ["triage"], "expected_doc_ids": ["triage-pericoronitis-001"], "difficulty": "easy"},
            {"query": "口腔溃疡两周不愈 边缘不规则", "categories": ["triage"], "expected_doc_ids": ["triage-mucosa-001"], "difficulty": "medium"},
            {"query": "口腔白斑 癌前病变 活检", "categories": ["triage"], "expected_doc_ids": ["triage-cancer-screen-001"], "difficulty": "medium"},
            {"query": "牙外伤 牙齿脱位 紧急处理", "categories": ["triage"], "expected_doc_ids": ["triage-trauma-001"], "difficulty": "easy"},
            {"query": "牙齿敏感 冷热酸甜刺激", "categories": ["triage"], "expected_doc_ids": ["triage-caries-pulpitis-001"], "difficulty": "easy"},
            {"query": "牙龈红肿 刷牙出血", "categories": ["triage"], "expected_doc_ids": ["triage-periodontal-001"], "difficulty": "easy"},
            {"query": "张口困难 关节弹响", "categories": ["triage"], "expected_doc_ids": ["triage-tmj-001"], "difficulty": "medium"},
            {"query": "颌面部疼痛 放射到头", "categories": ["triage"], "expected_doc_ids": ["triage-neuralgia-001"], "difficulty": "hard"},
            
            # 治疗类
            {"query": "根管治疗 牙髓炎 根尖周炎", "categories": ["treatment"], "expected_doc_ids": ["treatment-root-canal-001"], "difficulty": "easy"},
            {"query": "种植牙 骨量 CBCT", "categories": ["treatment"], "expected_doc_ids": ["treatment-implant-001"], "difficulty": "easy"},
            {"query": "正畸治疗 牙套 保持器", "categories": ["treatment"], "expected_doc_ids": ["treatment-orthodontics-001"], "difficulty": "easy"},
            {"query": "牙冠修复 烤瓷冠 全瓷冠", "categories": ["treatment"], "expected_doc_ids": ["treatment-crown-bridge-001"], "difficulty": "easy"},
            {"query": "拔牙 阻生齿 术后并发症", "categories": ["treatment"], "expected_doc_ids": ["treatment-extraction-001"], "difficulty": "easy"},
            {"query": "牙周刮治 深牙周袋", "categories": ["treatment"], "expected_doc_ids": ["treatment-periodontal-001"], "difficulty": "medium"},
            {"query": "贴面修复 四环素牙", "categories": ["treatment"], "expected_doc_ids": ["treatment-veneers-001"], "difficulty": "medium"},
            {"query": "牙髓再生 年轻恒牙", "categories": ["treatment"], "expected_doc_ids": ["treatment-pulp-regeneration-001"], "difficulty": "hard"},
            
            # 用药类
            {"query": "青霉素过敏 阿莫西林 甲硝唑", "categories": ["medication"], "expected_doc_ids": ["medication-antibiotic-001"], "difficulty": "easy"},
            {"query": "布洛芬 对乙酰氨基酚 止痛", "categories": ["medication"], "expected_doc_ids": ["medication-analgesic-001"], "difficulty": "easy"},
            {"query": "氯己定漱口水 牙周辅助", "categories": ["medication"], "expected_doc_ids": ["medication-mouthwash-001"], "difficulty": "easy"},
            {"query": "儿童用药剂量 阿莫西林", "categories": ["medication"], "expected_doc_ids": ["medication-children-001"], "difficulty": "medium"},
            {"query": "老年人用药 肝肾功能 药物相互作用", "categories": ["medication"], "expected_doc_ids": ["medication-elderly-001"], "difficulty": "medium"},
            {"query": "孕期用药安全 抗生素", "categories": ["medication"], "expected_doc_ids": ["medication-pregnancy-001"], "difficulty": "medium"},
            {"query": "抗真菌药 口腔念珠菌", "categories": ["medication"], "expected_doc_ids": ["medication-antifungal-001"], "difficulty": "easy"},
            
            # 影像类
            {"query": "全景片 阻生智齿 近中倾斜", "categories": ["imaging"], "expected_doc_ids": ["imaging-panoramic-001"], "difficulty": "easy"},
            {"query": "CBCT 种植 骨量 上颌窦", "categories": ["imaging"], "expected_doc_ids": ["imaging-cbct-001"], "difficulty": "easy"},
            {"query": "根尖片 龋坏 根尖周炎", "categories": ["imaging"], "expected_doc_ids": ["imaging-periapical-001"], "difficulty": "easy"},
            {"query": "头颅侧位片 正畸测量", "categories": ["imaging"], "expected_doc_ids": ["imaging-lateral-cephalogram-001"], "difficulty": "medium"},
            {"query": "咬合片 邻面龋", "categories": ["imaging"], "expected_doc_ids": ["imaging-bitewing-001"], "difficulty": "easy"},
            
            # 健康管理类
            {"query": "8岁儿童 窝沟封闭 换牙期", "categories": ["health"], "expected_doc_ids": ["health-child-001"], "difficulty": "easy"},
            {"query": "巴氏刷牙法 牙线 洁牙", "categories": ["health"], "expected_doc_ids": ["health-adult-001"], "difficulty": "easy"},
            {"query": "拔牙术后护理 出血 肿胀", "categories": ["health"], "expected_doc_ids": ["health-postop-001"], "difficulty": "easy"},
            {"query": "糖尿病 牙周病 血糖控制", "categories": ["health"], "expected_doc_ids": ["health-diabetes-001"], "difficulty": "medium"},
            {"query": "妊娠期 口腔健康 激素变化", "categories": ["health"], "expected_doc_ids": ["health-pregnancy-001"], "difficulty": "easy"},
            {"query": "老年人牙齿保健 义齿护理", "categories": ["health"], "expected_doc_ids": ["health-geriatric-001"], "difficulty": "easy"},
            {"query": "戒烟 口腔癌风险", "categories": ["health"], "expected_doc_ids": ["health-smoking-001"], "difficulty": "medium"},
            
            # 黏膜病类
            {"query": "口腔白斑病 癌前病变 随访", "categories": ["mucosa"], "expected_doc_ids": ["mucosa-leukoplakia-001"], "difficulty": "easy"},
            {"query": "扁平苔藓 糜烂 免疫", "categories": ["mucosa"], "expected_doc_ids": ["mucosa-lichen-001"], "difficulty": "medium"},
            {"query": "念珠菌感染 免疫力低下", "categories": ["mucosa"], "expected_doc_ids": ["mucosa-candidiasis-001"], "difficulty": "easy"},
            {"query": "复发性口腔溃疡 维生素缺乏", "categories": ["mucosa"], "expected_doc_ids": ["mucosa-ulcer-001"], "difficulty": "easy"},
            {"query": "天疱疮 自身免疫", "categories": ["mucosa"], "expected_doc_ids": ["mucosa-pemphigus-001"], "difficulty": "hard"},
            
            # 病例类
            {"query": "深龋 牙髓炎 根管治疗", "categories": ["case"], "expected_doc_ids": ["case-caries-001"], "difficulty": "easy"},
            {"query": "牙周炎 洁治 刮治", "categories": ["case"], "expected_doc_ids": ["case-periodontal-001"], "difficulty": "easy"},
            {"query": "种植牙 修复 骨量", "categories": ["case"], "expected_doc_ids": ["case-implant-001"], "difficulty": "easy"},
            {"query": "牙外伤 脱位 再植", "categories": ["case"], "expected_doc_ids": ["case-trauma-001"], "difficulty": "medium"},
            {"query": "全口修复 咬合重建", "categories": ["case"], "expected_doc_ids": ["case-full-mouth-rehab-001"], "difficulty": "hard"},
            
            # 紧急情况类
            {"query": "口腔急症 处理 转诊", "categories": ["emergency"], "expected_doc_ids": ["emergency-001"], "difficulty": "easy"},
            {"query": "颌面部外伤 骨折", "categories": ["emergency"], "expected_doc_ids": ["emergency-fracture-001"], "difficulty": "medium"},
            {"query": "药物过敏 呼吸困难", "categories": ["emergency"], "expected_doc_ids": ["emergency-anaphylaxis-001"], "difficulty": "hard"},
            
            # 指南类
            {"query": "病历书写 规范 记录", "categories": ["guide"], "expected_doc_ids": ["guide-medical-record-001"], "difficulty": "easy"},
            {"query": "诊疗规范 口腔", "categories": ["guide"], "expected_doc_ids": ["guide-clinical-guidelines-001"], "difficulty": "easy"},
            
            # 安全类
            {"query": "AI诊断 免责声明 医生复核", "categories": ["safety"], "expected_doc_ids": ["safety-boundary-001"], "difficulty": "easy"},
            {"query": "医疗纠纷 知情同意 沟通", "categories": ["safety"], "expected_doc_ids": ["safety-dispute-001"], "difficulty": "medium"},
            {"query": "过度治疗 合理用药 检查指征", "categories": ["safety"], "expected_doc_ids": ["safety-overtreatment-001"], "difficulty": "medium"},
            {"query": "数据隐私 患者信息保护", "categories": ["safety"], "expected_doc_ids": ["safety-privacy-001"], "difficulty": "easy"},
        ]
        
        if self._chroma is None:
            return {"backend": self.backend_name, "error": self._chroma_error, "case_count": len(cases), "hit_rate": 0.0, "mrr": 0.0}
        
        result = self._chroma.evaluate(cases, top_k=5)
        result["backend"] = self.backend_name
        
        failures = []
        failure_analysis = {
            "semantic_mismatch": 0,
            "keyword_missing": 0,
            "category_confusion": 0,
            "ambiguous_query": 0,
            "document_not_found": 0,
            "other": 0
        }
        
        for i, case in enumerate(cases):
            hits = self.retrieve(case["query"], categories=case.get("categories"), top_k=5)
            hit_ids = [hit.document.id for hit in hits]
            expected_ids = case["expected_doc_ids"]
            missed = [eid for eid in expected_ids if eid not in hit_ids]
            
            if missed:
                analysis = self._analyze_failure(case, hits, expected_ids)
                failures.append({
                    "query": case["query"],
                    "expected": expected_ids,
                    "got": hit_ids[:3],
                    "missed": missed,
                    "difficulty": case.get("difficulty", "unknown"),
                    "failure_type": analysis["type"],
                    "failure_reason": analysis["reason"],
                    "suggestion": analysis["suggestion"]
                })
                failure_analysis[analysis["type"]] += 1
        
        result["failures"] = failures
        result["failure_count"] = len(failures)
        result["failure_analysis"] = failure_analysis
        
        category_hits = {}
        category_total = {}
        for cat in ["triage", "treatment", "medication", "imaging", "health", "mucosa", "case", "emergency", "guide", "safety"]:
            cat_cases = [c for c in cases if cat in (c.get("categories") or [])]
            if not cat_cases:
                continue
            cat_hits = 0
            for case in cat_cases:
                hits = self.retrieve(case["query"], categories=case.get("categories"), top_k=5)
                hit_ids = [hit.document.id for hit in hits]
                if any(eid in hit_ids for eid in case["expected_doc_ids"]):
                    cat_hits += 1
            category_hits[cat] = cat_hits
            category_total[cat] = len(cat_cases)
        
        result["category_coverage"] = {cat: category_total.get(cat, 0) for cat in category_total}
        result["category_recall"] = {cat: round(category_hits[cat] / category_total[cat], 3) for cat in category_total}
        
        difficulty_hits = {"easy": 0, "medium": 0, "hard": 0}
        difficulty_total = {"easy": 0, "medium": 0, "hard": 0}
        for case in cases:
            diff = case.get("difficulty", "easy")
            difficulty_total[diff] += 1
            hits = self.retrieve(case["query"], categories=case.get("categories"), top_k=5)
            hit_ids = [hit.document.id for hit in hits]
            if any(eid in hit_ids for eid in case["expected_doc_ids"]):
                difficulty_hits[diff] += 1
        
        result["difficulty_analysis"] = {
            "easy": {"total": difficulty_total["easy"], "hits": difficulty_hits["easy"], "recall": round(difficulty_hits["easy"] / max(difficulty_total["easy"], 1), 3)},
            "medium": {"total": difficulty_total["medium"], "hits": difficulty_hits["medium"], "recall": round(difficulty_hits["medium"] / max(difficulty_total["medium"], 1), 3)},
            "hard": {"total": difficulty_total["hard"], "hits": difficulty_hits["hard"], "recall": round(difficulty_hits["hard"] / max(difficulty_total["hard"], 1), 3)},
        }
        
        return result

    def _analyze_failure(self, case: dict, hits: list[RetrievalHit], expected_ids: list[str]) -> dict[str, str]:
        query = case["query"]
        query_tokens = _tokenize(query)
        
        expected_docs = [self._doc_by_id.get(eid) for eid in expected_ids if self._doc_by_id.get(eid)]
        
        if not expected_docs:
            return {
                "type": "document_not_found",
                "reason": "期望的文档在知识库中不存在",
                "suggestion": "请检查文档ID是否正确，或确认该文档已导入知识库"
            }
        
        expected_content = " ".join([doc.content for doc in expected_docs if doc])
        expected_tokens = _tokenize(expected_content)
        
        keyword_overlap = query_tokens & expected_tokens
        if len(keyword_overlap) == 0:
            return {
                "type": "keyword_missing",
                "reason": "查询与期望文档之间没有共同关键词",
                "suggestion": "考虑在查询中使用更专业的医学术语，或丰富文档的关键词标签"
            }
        
        if len(keyword_overlap) < len(query_tokens) * 0.3:
            return {
                "type": "semantic_mismatch",
                "reason": "查询与期望文档语义匹配度较低",
                "suggestion": "可能需要优化文档内容，使其包含更多相关的临床术语和表达方式"
            }
        
        if hits and len(hits) > 0:
            hit_categories = {hit.document.category for hit in hits}
            expected_categories = set(case.get("categories", []))
            if expected_categories and hit_categories.isdisjoint(expected_categories):
                return {
                    "type": "category_confusion",
                    "reason": "召回结果的类别与期望类别不匹配",
                    "suggestion": "检查文档的类别标注是否正确，或调整查询的类别过滤条件"
                }
        
        if len(query_tokens) <= 2:
            return {
                "type": "ambiguous_query",
                "reason": "查询过于简短，可能存在歧义",
                "suggestion": "增加查询的具体性，提供更多上下文信息"
            }
        
        return {
            "type": "other",
            "reason": "召回失败原因不明，可能是向量索引问题或模型参数需要调整",
            "suggestion": "尝试重建向量索引，或调整检索参数（如top_k、相似度阈值等）"
        }

    def _score_document(self, doc: KnowledgeDocument, query_lower: str, query_tokens: set[str]) -> float:
        searchable = f"{doc.title} {' '.join(doc.tags)} {doc.content}".lower()
        doc_tokens = _tokenize(searchable)
        overlap = len(query_tokens & doc_tokens)
        tag_hits = sum(2.5 for tag in doc.tags if tag.lower() in query_lower or tag in query_lower)
        phrase_hits = sum(1.5 for phrase in _clinical_phrases() if phrase in query_lower and phrase in searchable)
        char_overlap = len(set(query_lower) & set(searchable)) / max(math.sqrt(len(searchable)), 1)
        return overlap * 0.5 + tag_hits + phrase_hits + char_overlap


def _tokenize(text: str) -> set[str]:
    tokens = {token.lower() for token in TOKEN_RE.findall(text)}
    for phrase in _clinical_phrases():
        if phrase in text:
            tokens.add(phrase.lower())
    return tokens


def _clinical_phrases() -> list[str]:
    return [
        "牙痛",
        "夜间痛",
        "冷热刺激",
        "牙髓炎",
        "龋病",
        "牙龈出血",
        "牙齿松动",
        "口腔溃疡",
        "根管治疗",
        "治疗步骤",
        "费用因素",
        "复诊次数",
        "种植牙",
        "正畸",
        "抗生素",
        "阿莫西林",
        "甲硝唑",
        "青霉素过敏",
        "用药安全",
        "全景片",
        "CBCT",
        "阻生齿",
        "阻生智齿",
        "窝沟封闭",
        "涂氟",
        "换牙期",
        "儿童",
        "复诊",
    ]


def _excerpt(content: str, tokens: set[str], limit: int = 96) -> str:
    if len(content) <= limit:
        return content
    for token in tokens:
        if len(token) < 2:
            continue
        index = content.lower().find(token.lower())
        if index >= 0:
            start = max(0, index - 24)
            end = min(len(content), start + limit)
            return content[start:end] + ("..." if end < len(content) else "")
    return content[:limit] + "..."

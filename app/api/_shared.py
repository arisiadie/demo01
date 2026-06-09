"""Shared API singletons.

Holds the single APIRouter instance plus the KnowledgeStore / orchestrator
singletons that endpoint modules and the aggregator (app/api/routes.py) both
need. Extracted in phase-4 of the backend governance refactor so that routes
can be split by domain into app/api/endpoints/* without circular imports or
duplicated singletons.

Dependency direction (strictly one-way):
    services/*  ->  api/_shared  ->  api/endpoints/*  ->  api/routes (aggregator)
This module must NOT import from app.api.endpoints or app.api.routes.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.agents.orchestrator import OralAgentOrchestrator
from app.rag.store import KnowledgeStore

router = APIRouter()
store = KnowledgeStore()
orchestrator = OralAgentOrchestrator(store=store)

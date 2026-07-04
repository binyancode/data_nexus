"""/api/v1/concepts —— 本体概念读写。"""
from fastapi import APIRouter, Depends

from core.deps import get_nexus
from models.api import ConceptUpsertRequest
from nexus.client import NexusClient
from nexus.core.models import Concept

router = APIRouter()


@router.get("")
async def list_concepts(nexus: NexusClient = Depends(get_nexus)):
    """列出全部概念。"""
    return [c.model_dump() for c in nexus.ontology.list_concepts()]


@router.post("")
async def upsert_concept(req: ConceptUpsertRequest, nexus: NexusClient = Depends(get_nexus)):
    """新增/更新一个概念。"""
    concept = Concept(**req.concept)
    nexus.ontology.upsert_concept(concept)
    return {"status": "ok", "id": concept.id}

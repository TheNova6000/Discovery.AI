"""HTTP routes for the Main Block door (option B): the same operations as
`service.py`, so the main block can later run as its own process without the
clients changing shape."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.api.auth import get_current_user_id

from .models import AskRequest, AskResult, ResearchJob, ResearchJobRequest
from .service import JobNotFound, ask, get_job, start_research

router = APIRouter(prefix="/mainblock", tags=["mainblock"])


@router.post("/research", status_code=202, response_model=ResearchJob)
async def post_research(req: ResearchJobRequest, user_id: str = Depends(get_current_user_id)) -> ResearchJob:
    """Start (or return the existing) research job for this request. 202: the
    work runs in the background; poll GET /mainblock/research/{job_id}."""
    return await start_research(req, user_id)


@router.get("/research/{job_id}", response_model=ResearchJob)
async def get_research(job_id: str, user_id: str = Depends(get_current_user_id)) -> ResearchJob:
    try:
        return await get_job(job_id, user_id)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="research job not found") from None


@router.post("/ask", response_model=AskResult)
async def post_ask(req: AskRequest, user_id: str = Depends(get_current_user_id)) -> AskResult:
    """One grounded answer (archive first, research on a miss). Synchronous:
    bounded to one evidence step plus at most two gap searches."""
    return await ask(req)

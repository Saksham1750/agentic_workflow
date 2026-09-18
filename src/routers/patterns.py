from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db
from src.models.pattern import Pattern
from src.schemas.pattern import (
    PatternCreate,
    PatternUpdate,
    PatternResponse,
    PatternListResponse,
    PatternSearchRequest,
    PatternSearchResponse,
    PatternSearchResult,
)
from src.auth.dependencies import get_current_user
from src.exceptions import NotFoundError, ConflictError
from src.services.pattern_service import pattern_service

router = APIRouter(prefix="/patterns", tags=["patterns"])


@router.post("", response_model=PatternResponse, status_code=201)
async def create_pattern(
    body: PatternCreate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(select(Pattern).where(Pattern.name == body.name))
    if existing.scalar_one_or_none():
        raise ConflictError(f"Pattern '{body.name}' already exists")

    pattern = Pattern(
        name=body.name,
        intent=body.intent,
        structure=body.structure,
        when_to_use=body.when_to_use,
        strengths=body.strengths,
        weaknesses=body.weaknesses,
        example_use_case=body.example_use_case,
        tags=body.tags,
    )
    db.add(pattern)
    await db.flush()

    embedding_id = await pattern_service.upsert_pattern_embedding(pattern)
    pattern.embedding_id = embedding_id

    await db.flush()
    await db.refresh(pattern)
    return pattern


@router.get("", response_model=PatternListResponse)
async def list_patterns(
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Pattern))
    patterns = list(result.scalars().all())
    return PatternListResponse(patterns=patterns, total=len(patterns))


@router.get("/{pattern_id}", response_model=PatternResponse)
async def get_pattern(
    pattern_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Pattern).where(Pattern.id == pattern_id))
    pattern = result.scalar_one_or_none()
    if not pattern:
        raise NotFoundError("Pattern", pattern_id)
    return pattern


@router.patch("/{pattern_id}", response_model=PatternResponse)
async def update_pattern(
    pattern_id: str,
    body: PatternUpdate,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Pattern).where(Pattern.id == pattern_id))
    pattern = result.scalar_one_or_none()
    if not pattern:
        raise NotFoundError("Pattern", pattern_id)

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(pattern, field, value)

    await db.flush()

    embedding_id = await pattern_service.upsert_pattern_embedding(pattern)
    pattern.embedding_id = embedding_id

    await db.flush()
    await db.refresh(pattern)
    return pattern


@router.delete("/{pattern_id}", status_code=204)
async def delete_pattern(
    pattern_id: str,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Pattern).where(Pattern.id == pattern_id))
    pattern = result.scalar_one_or_none()
    if not pattern:
        raise NotFoundError("Pattern", pattern_id)

    if pattern.embedding_id:
        await pattern_service.remove_pattern_embedding(pattern.embedding_id)

    await db.delete(pattern)
    await db.flush()


@router.post("/search", response_model=PatternSearchResponse)
async def search_patterns(
    body: PatternSearchRequest,
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    search_results = await pattern_service.search_patterns(
        query=body.query,
        tags=body.tags,
        n_results=body.n_results,
    )

    pattern_ids = [r["metadata"].get("name") for r in search_results if r["metadata"].get("name")]

    results = []
    for sr in search_results:
        name = sr["metadata"].get("name")
        if not name:
            continue
        result = await db.execute(select(Pattern).where(Pattern.name == name))
        pattern = result.scalar_one_or_none()
        if pattern:
            results.append(PatternSearchResult(pattern=pattern, score=sr["score"]))

    return PatternSearchResponse(results=results, total=len(results))


@router.post("/bulk", status_code=201)
async def bulk_import_patterns(
    patterns_data: list[PatternCreate],
    user_id: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    created = 0
    skipped = 0
    for p_data in patterns_data:
        existing = await db.execute(select(Pattern).where(Pattern.name == p_data.name))
        if existing.scalar_one_or_none():
            skipped += 1
            continue

        pattern = Pattern(
            name=p_data.name,
            intent=p_data.intent,
            structure=p_data.structure,
            when_to_use=p_data.when_to_use,
            strengths=p_data.strengths,
            weaknesses=p_data.weaknesses,
            example_use_case=p_data.example_use_case,
            tags=p_data.tags,
        )
        db.add(pattern)
        await db.flush()

        embedding_id = await pattern_service.upsert_pattern_embedding(pattern)
        pattern.embedding_id = embedding_id
        created += 1

    await db.flush()
    return {"created": created, "skipped": skipped, "total": len(patterns_data)}

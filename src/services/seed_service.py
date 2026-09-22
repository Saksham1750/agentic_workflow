import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import async_session_factory
from src.models.pattern import Pattern
from src.services.pattern_service import pattern_service

logger = logging.getLogger(__name__)

SEED_FILE_PATH = "src/seeds/patterns.yaml"


async def seed_patterns():
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed, skipping pattern seeding")
        return

    from pathlib import Path

    seed_path = Path(SEED_FILE_PATH)
    if not seed_path.exists():
        logger.info("No seed file found at %s, skipping", SEED_FILE_PATH)
        return

    with open(seed_path, "r", encoding="utf-8") as f:
        patterns_data = yaml.safe_load(f)

    if not patterns_data or "patterns" not in patterns_data:
        logger.info("Seed file empty or malformed")
        return

    async with async_session_factory() as db:
        for p_data in patterns_data["patterns"]:
            result = await db.execute(
                select(Pattern).where(Pattern.name == p_data["name"])
            )
            existing = result.scalar_one_or_none()
            if existing:
                continue

            pattern = Pattern(
                id=str(uuid.uuid4()),
                name=p_data["name"],
                intent=p_data.get("intent", ""),
                structure=p_data.get("structure", ""),
                when_to_use=p_data.get("when_to_use", ""),
                strengths=p_data.get("strengths"),
                weaknesses=p_data.get("weaknesses"),
                example_use_case=p_data.get("example_use_case"),
                when_not_to_use=p_data.get("when_not_to_use"),
                prerequisites=p_data.get("prerequisites"),
                references=p_data.get("references"),
                tags=p_data.get("tags"),
            )
            db.add(pattern)
            await db.flush()

            embedding_id = await pattern_service.upsert_pattern_embedding(pattern)
            pattern.embedding_id = embedding_id

        await db.commit()
        logger.info("Pattern seeding complete")

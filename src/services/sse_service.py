import json
import asyncio
import logging
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.run_event import RunEvent
from src.database import async_session_factory

logger = logging.getLogger(__name__)


class SSEService:
    async def emit_event(
        self,
        run_id: str,
        event_type: str,
        node_name: str | None = None,
        data: dict | None = None,
    ):
        async with async_session_factory() as db:
            result = await db.execute(
                select(RunEvent).where(RunEvent.run_id == run_id)
            )
            existing = list(result.scalars().all())
            event_index = len(existing)

            event = RunEvent(
                run_id=run_id,
                event_type=event_type,
                node_name=node_name,
                data=data,
                event_index=event_index,
            )
            db.add(event)
            await db.commit()

    async def stream_events(
        self,
        run_id: str,
        last_event_id: int | None = None,
    ) -> AsyncGenerator[str, None]:
        async with async_session_factory() as db:
            query = select(RunEvent).where(RunEvent.run_id == run_id)
            if last_event_id is not None:
                query = query.where(RunEvent.event_index > last_event_id)
            query = query.order_by(RunEvent.event_index)

            result = await db.execute(query)
            events = list(result.scalars().all())

        for event in events:
            event_data = {
                "event": event.event_type,
                "id": str(event.event_index),
                "data": json.dumps({
                    "event_type": event.event_type,
                    "node_name": event.node_name,
                    "data": event.data,
                    "event_index": event.event_index,
                }),
            }
            yield f"event: {event_data['event']}\nid: {event_data['id']}\ndata: {event_data['data']}\n\n"

    async def wait_for_new_events(
        self,
        run_id: str,
        after_index: int,
        timeout: float = 30.0,
    ) -> AsyncGenerator[str, None]:
        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.event_index > after_index)
                    .order_by(RunEvent.event_index)
                )
                new_events = list(result.scalars().all())

            for event in new_events:
                event_data = {
                    "event": event.event_type,
                    "id": str(event.event_index),
                    "data": json.dumps({
                        "event_type": event.event_type,
                        "node_name": event.node_name,
                        "data": event.data,
                        "event_index": event.event_index,
                    }),
                }
                yield f"event: {event_data['event']}\nid: {event_data['id']}\ndata: {event_data['data']}\n\n"

                if event.event_type in ("run_completed", "run_failed"):
                    return

            await asyncio.sleep(0.5)

        yield "event: heartbeat\ndata: {}\n\n"


sse_service = SSEService()

import copy
import functools
import json
import logging
from contextvars import ContextVar

from opentelemetry import trace
from opentelemetry.trace import StatusCode

logger = logging.getLogger(__name__)

tracer = trace.get_tracer("ai-agent-factory.workflows")

_current_sse_service: ContextVar = ContextVar("current_sse_service", default=None)


def set_sse_service(sse_svc):
    _current_sse_service.set(sse_svc)


def clear_sse_service():
    _current_sse_service.set(None)


def _compute_changed_fields(before: dict, after: dict) -> list[str]:
    changed = []
    for key, value in after.items():
        if key not in before:
            changed.append(key)
        elif before[key] != value:
            changed.append(key)
    return changed


def traced_node(node_name: str):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(state: dict, *args, **kwargs):
            run_id = state.get("run_id", "")
            project_id = state.get("project_id", "")

            before_state = copy.deepcopy(state)

            with tracer.start_as_current_span(
                f"workflow.node.{node_name}",
                attributes={
                    "node.name": node_name,
                    "run.id": run_id,
                    "project.id": project_id,
                },
            ) as span:
                try:
                    result = await func(state, *args, **kwargs)
                    span.set_status(StatusCode.OK)

                    sse_svc = _current_sse_service.get()
                    if sse_svc and run_id:
                        changed_fields = _compute_changed_fields(before_state, result or {})
                        try:
                            await sse_svc.emit_event(
                                run_id=run_id,
                                event_type="node_state_captured",
                                node_name=node_name,
                                data={
                                    "node_name": node_name,
                                    "before": _serialize_state(before_state),
                                    "after": _serialize_state(result or {}),
                                    "changed_fields": changed_fields,
                                },
                            )
                        except Exception as e:
                            logger.debug("Failed to emit node_state_captured event: %s", e)

                    return result
                except Exception as e:
                    span.set_status(StatusCode.ERROR, str(e))
                    span.record_exception(e)
                    raise

        return wrapper

    return decorator


def _serialize_state(state: dict) -> dict:
    serialized = {}
    for key, value in state.items():
        try:
            json.dumps(value, default=str)
            serialized[key] = value
        except (TypeError, ValueError):
            serialized[key] = str(value)[:500]
    return serialized

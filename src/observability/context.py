from contextvars import ContextVar

_current_run_id: ContextVar[str] = ContextVar("otel_run_id", default="")
_current_project_id: ContextVar[str] = ContextVar("otel_project_id", default="")
_current_node_name: ContextVar[str] = ContextVar("otel_node_name", default="")


def get_current_run_id() -> str:
    return _current_run_id.get()


def get_current_project_id() -> str:
    return _current_project_id.get()


def get_current_node_name() -> str:
    return _current_node_name.get()


def set_observability_context(run_id: str, project_id: str, node_name: str = ""):
    _current_run_id.set(run_id)
    _current_project_id.set(project_id)
    _current_node_name.set(node_name)


def set_node_name(node_name: str):
    _current_node_name.set(node_name)

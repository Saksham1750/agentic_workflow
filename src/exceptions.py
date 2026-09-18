from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: dict | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class NotFoundError(AppError):
    def __init__(self, resource: str, resource_id: str):
        super().__init__(code="not_found", message=f"{resource} '{resource_id}' not found", status_code=404)


class ConflictError(AppError):
    def __init__(self, message: str):
        super().__init__(code="conflict", message=message, status_code=409)


class UnsupportedMediaError(AppError):
    def __init__(self, content_type: str):
        super().__init__(code="unsupported_media", message=f"Unsupported file type: {content_type}", status_code=415)


class PayloadTooLargeError(AppError):
    def __init__(self, max_mb: int):
        super().__init__(code="payload_too_large", message=f"File exceeds {max_mb}MB limit", status_code=413)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Invalid or missing authentication"):
        super().__init__(code="unauthorized", message=message, status_code=401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Access denied"):
        super().__init__(code="forbidden", message=message, status_code=403)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )

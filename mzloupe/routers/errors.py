"""Shared HTTP error handling for application route groups."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ErrorHandlers:
    """Translate expected application errors into readable HTTP responses."""

    @staticmethod
    def register(app: FastAPI) -> None:
        """Apply one consistent input-error response across every route group."""
        app.add_exception_handler(ValueError, ErrorHandlers.value_error)

    @staticmethod
    async def value_error(_request: Request, error: Exception) -> JSONResponse:
        """Return an HTTP 400 response for the registered ValueError exception type."""
        return JSONResponse({"detail": str(error)}, status_code=400)

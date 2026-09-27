from __future__ import annotations


class OpenWebUIError(Exception):
    """Base class for safe, user-facing upstream errors."""


class ConfigurationError(OpenWebUIError):
    """The server cannot determine a permitted knowledge base."""


class InputValidationError(OpenWebUIError):
    """The MCP tool input is invalid or not permitted."""


class AuthenticationError(OpenWebUIError):
    """The Open WebUI API key was rejected."""


class AccessDeniedError(OpenWebUIError):
    """The API key cannot access the requested resource."""


class ResourceNotFoundError(OpenWebUIError):
    """The requested Open WebUI resource or endpoint does not exist."""


class UpstreamValidationError(OpenWebUIError):
    """Open WebUI rejected a validly shaped request."""


class RateLimitError(OpenWebUIError):
    """Open WebUI is rate limiting requests."""


class UpstreamServiceError(OpenWebUIError):
    """Open WebUI returned a temporary server error."""


class UpstreamTimeoutError(OpenWebUIError):
    """The Open WebUI request exceeded its timeout."""


class UpstreamProtocolError(OpenWebUIError):
    """Open WebUI returned a response that could not be decoded."""

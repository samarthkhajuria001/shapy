"""Custom exception classes."""

from fastapi import HTTPException, status


class ShapyException(HTTPException):
    """Base exception for application errors."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str = "SHAPY_ERROR",
    ):
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


class AuthenticationError(ShapyException):
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            code="AUTH_ERROR",
        )


class InvalidCredentialsError(AuthenticationError):
    def __init__(self):
        super().__init__(detail="Invalid email or password")


class TokenExpiredError(AuthenticationError):
    def __init__(self):
        super().__init__(detail="Token has expired")


class InvalidTokenError(AuthenticationError):
    def __init__(self):
        super().__init__(detail="Invalid token")


class UserExistsError(ShapyException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
            code="USER_EXISTS",
        )


class UserNotFoundError(ShapyException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
            code="USER_NOT_FOUND",
        )


class SessionNotFoundError(ShapyException):
    def __init__(self, session_id: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
            code="SESSION_NOT_FOUND",
        )


class SessionExpiredError(ShapyException):
    def __init__(self):
        super().__init__(
            status_code=status.HTTP_410_GONE,
            detail="Session has expired",
            code="SESSION_EXPIRED",
        )


class SessionOwnershipError(ShapyException):
    def __init__(self, session_id: str):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied to session: {session_id}",
            code="SESSION_OWNERSHIP_ERROR",
        )


class MaxSessionsError(ShapyException):
    def __init__(self, limit: int):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Maximum sessions limit reached ({limit}). Delete an existing session first.",
            code="MAX_SESSIONS_ERROR",
        )


class InvalidDrawingObjectError(ShapyException):
    def __init__(self, errors: list[str]):
        self.errors = errors
        detail = f"Drawing validation failed with {len(errors)} error(s): {'; '.join(errors[:5])}"
        if len(errors) > 5:
            detail += f" ... and {len(errors) - 5} more"
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            code="INVALID_DRAWING_OBJECT",
        )


class ContextTooLargeError(ShapyException):
    def __init__(self, message: str):
        super().__init__(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=message,
            code="CONTEXT_TOO_LARGE",
        )

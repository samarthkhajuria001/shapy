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

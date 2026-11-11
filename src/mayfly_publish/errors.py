"""Errors with safe, stable codes for MCP responses."""


class PublishError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def as_dict(self) -> dict[str, str]:
        return {"error": self.code, "message": self.message}

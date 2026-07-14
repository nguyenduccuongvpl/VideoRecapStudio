"""Domain-specific exceptions for VideoRecapStudio."""


class DomainError(Exception):
    """Base exception class for all domain errors."""

    pass


class PathTraversalError(DomainError):
    """Raised when an operation attempts to access a path outside the allowed root directory."""

    pass


class ArtifactError(DomainError):
    """Raised when an artifact cannot be created, loaded, or validated."""

    pass


class ProjectNotFoundError(DomainError):
    """Raised when a requested project directory or configuration is not found."""

    pass


class ProjectAlreadyExistsError(DomainError):
    """Raised when trying to initialize a project that already exists."""

    pass


class JobCancelledError(DomainError):
    """Raised when a job execution is cooperatively cancelled."""

    pass


class ProcessExecutionError(DomainError):
    """Raised when a subprocess execution fails or returns a non-zero exit code."""

    def __init__(
        self,
        message: str,
        command: list[str],
        return_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        super().__init__(message)
        self.command = command
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr

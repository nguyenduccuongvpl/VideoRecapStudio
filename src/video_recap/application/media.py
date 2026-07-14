"""Application protocols and ports for subprocess execution."""

from typing import Callable, Optional, Protocol
from video_recap.application.pipeline import CancellationToken
from video_recap.domain.media import CommandSpec, CommandResult


class ProcessRunner(Protocol):
    """Protocol for executing subprocess commands securely with monitoring and progress tracking."""

    def run(
        self,
        spec: CommandSpec,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> CommandResult:
        """Run a process command synchronously and return execution details.

        Args:
            spec: Command execution parameters.
            cancellation_token: Token to signal cancellation cooperative halt.
            progress_callback: Callback triggered with execution progress (0.0 to 1.0).

        Returns:
            CommandResult model with stdout, stderr and exit code.

        Raises:
            ProcessExecutionError: If command fails, runs into timeout, or cancels.
        """
        ...

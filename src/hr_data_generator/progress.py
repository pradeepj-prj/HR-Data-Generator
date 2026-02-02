"""Progress callback support for long-running data generation."""

from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class ProgressInfo:
    """
    Information about the current progress of data generation.

    This dataclass is passed to progress callbacks during data generation,
    allowing consumers (like Streamlit dashboards) to display progress bars
    and status messages.

    Attributes:
        phase: Current generation phase (e.g., "employees", "hierarchy", "compensation")
        step: Current step number (1-based)
        total_steps: Total number of steps in generation
        message: Human-readable status message
        sub_step: Optional sub-step for phases with multiple iterations (e.g., year-by-year)
        sub_total: Optional total sub-steps for sub-progress tracking
    """

    phase: str
    step: int
    total_steps: int
    message: str
    sub_step: int | None = None
    sub_total: int | None = None

    @property
    def progress(self) -> float:
        """
        Calculate overall progress as a float between 0.0 and 1.0.

        This value is compatible with Streamlit's st.progress() function.
        When sub_step and sub_total are provided, the progress includes
        fractional advancement within the current step.

        Returns:
            Float between 0.0 and 1.0 representing overall progress.
        """
        if self.total_steps == 0:
            return 0.0

        # Base progress from completed steps
        base = (self.step - 1) / self.total_steps
        # Weight of one step
        step_weight = 1.0 / self.total_steps

        # If we have sub-progress, add fractional progress within current step
        if self.sub_step is not None and self.sub_total is not None and self.sub_total > 0:
            sub_progress = self.sub_step / self.sub_total
            return base + (step_weight * sub_progress)

        # Otherwise, count the current step as complete
        return base + step_weight


class ProgressCallback(Protocol):
    """
    Protocol for progress callback functions.

    Any callable that accepts a ProgressInfo argument satisfies this protocol.
    This allows type-safe callbacks without requiring inheritance.

    Example:
        def my_callback(info: ProgressInfo) -> None:
            print(f"{info.progress:.0%} - {info.message}")

        generate_hr_data(n_employees=1000, progress_callback=my_callback)
    """

    def __call__(self, info: ProgressInfo) -> None:
        """
        Called with progress updates during data generation.

        Args:
            info: Current progress information
        """
        ...

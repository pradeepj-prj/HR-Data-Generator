"""Streaming data generation for year-by-year loading with resumability.

This module provides streaming/chunked data generation that yields data
year-by-year, enabling:
- Progress visibility during long generation runs
- Database commits after each year
- Resumability after interruption using deterministic seeds
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Iterator

import pandas as pd


@dataclass
class YearlyDataChunk:
    """Data chunk for a single simulation year.

    Each chunk contains the employees and time-variant records that were
    created or modified during that simulation year. For streaming database
    loads, commit after each chunk for resumability.

    Attributes:
        year: The simulation year this chunk represents
        is_initial_year: True if this is the first year (contains reference data)
        is_final_year: True if this is the last year of simulation
        employees: DataFrame of new and updated employees
        job_assignments: DataFrame of job assignments for this year
        org_assignments: DataFrame of org assignments for this year
        compensation: DataFrame of compensation records (None if disabled)
        performance: DataFrame of performance reviews (None if disabled)
        terminated_employee_ids: List of employee IDs terminated this year
        new_hires_count: Number of new hires this year
        terminations_count: Number of terminations this year
        active_headcount: Total active employees at end of year
        organization_unit: Reference data (only in initial year)
        job_role: Reference data (only in initial year)
        location: Reference data (only in initial year)
    """

    year: int
    is_initial_year: bool
    is_final_year: bool

    # Core data for this year
    employees: pd.DataFrame
    job_assignments: pd.DataFrame
    org_assignments: pd.DataFrame
    compensation: pd.DataFrame | None
    performance: pd.DataFrame | None

    # Summary stats
    terminated_employee_ids: list[str] = field(default_factory=list)
    new_hires_count: int = 0
    terminations_count: int = 0
    active_headcount: int = 0

    # Reference data (only populated in initial year)
    organization_unit: pd.DataFrame | None = None
    job_role: pd.DataFrame | None = None
    location: pd.DataFrame | None = None

    def get_row_counts(self) -> dict[str, int]:
        """Get row counts for each table in this chunk.

        Returns:
            Dictionary mapping table names to row counts.
        """
        counts = {
            "employees": len(self.employees),
            "job_assignments": len(self.job_assignments),
            "org_assignments": len(self.org_assignments),
        }

        if self.compensation is not None:
            counts["compensation"] = len(self.compensation)
        if self.performance is not None:
            counts["performance"] = len(self.performance)
        if self.organization_unit is not None:
            counts["organization_unit"] = len(self.organization_unit)
        if self.job_role is not None:
            counts["job_role"] = len(self.job_role)
        if self.location is not None:
            counts["location"] = len(self.location)

        return counts

    def __repr__(self) -> str:
        """Return a concise string representation."""
        return (
            f"YearlyDataChunk(year={self.year}, "
            f"headcount={self.active_headcount}, "
            f"hires={self.new_hires_count}, "
            f"terms={self.terminations_count})"
        )


def generate_hr_data_streaming(
    n_employees: int = 100,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    seed: int | None = None,
    include_performance: bool = True,
    include_compensation: bool = True,
    include_attrition: bool = True,
    attrition_rate: float = 0.12,
    noise_std: float = 0.2,
    bu_distribution: dict[str, float] | None = None,
    include_hiring: bool = False,
    base_growth_rate: float = 0.05,
    backfill_rate: float = 0.85,
    bu_growth_rates: dict[str, float] | None = None,
) -> Iterator[YearlyDataChunk]:
    """Generate HR data as a stream of yearly chunks.

    This is the streaming version of generate_hr_data(). Instead of returning
    a complete dataset, it yields YearlyDataChunk objects one at a time.

    For resumability, use the same seed and fast-forward through already-loaded
    years when resuming an interrupted load.

    Args:
        n_employees: Number of initial employees to generate
        start_date: Simulation start date (default: 5 years ago)
        end_date: Simulation end date (default: today)
        seed: Random seed for reproducibility (REQUIRED for resumable loads)
        include_performance: Generate performance reviews
        include_compensation: Generate compensation records
        include_attrition: Apply employee attrition/turnover
        attrition_rate: Base annual attrition rate (default: 0.12 = 12%)
        noise_std: Noise standard deviation for attrition probability
        bu_distribution: Business unit distribution dict
        include_hiring: Enable hiring simulation
        base_growth_rate: Base annual growth rate for hiring
        backfill_rate: Fraction of attrition to backfill
        bu_growth_rates: Per-business-unit growth rate overrides

    Yields:
        YearlyDataChunk: One chunk per simulation year, containing all data
            for that year. The first chunk includes reference data.

    Example:
        >>> for chunk in generate_hr_data_streaming(n_employees=1000, seed=42):
        ...     print(f"Year {chunk.year}: {chunk.active_headcount} employees")
        ...     # Load chunk.employees, chunk.job_assignments, etc. to database
        ...     # Commit transaction
        Year 2021: 1000 employees
        Year 2022: 1050 employees
        Year 2023: 1100 employees
        ...

    Note:
        When using streaming mode with include_hiring=True and include_attrition=True,
        the generator yields incremental data for each year. Without these flags,
        all data is yielded in a single chunk for the initial year.
    """
    # Import here to avoid circular imports
    from .generator import HRDataGenerator

    generator = HRDataGenerator(seed=seed)
    yield from generator.generate_streaming(
        n_employees=n_employees,
        start_date=start_date,
        end_date=end_date,
        include_performance=include_performance,
        include_compensation=include_compensation,
        include_attrition=include_attrition,
        attrition_rate=attrition_rate,
        noise_std=noise_std,
        bu_distribution=bu_distribution,
        include_hiring=include_hiring,
        base_growth_rate=base_growth_rate,
        backfill_rate=backfill_rate,
        bu_growth_rates=bu_growth_rates,
    )

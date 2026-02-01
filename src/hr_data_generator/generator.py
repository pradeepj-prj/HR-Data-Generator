"""Main HR Data Generator orchestrator."""

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .assignments import generate_job_assignments, generate_org_assignments
from .attrition import (
    apply_attrition,
    apply_attrition_for_year,
    close_records_at_termination,
    filter_reviews_by_termination,
)
from .compensation import generate_compensation_records
from .employee import DEFAULT_BU_DISTRIBUTION, generate_employees_with_bands
from .hierarchy import build_manager_hierarchy, validate_hierarchy, validate_manager_bu_alignment
from .hiring import HiringModel, apply_hiring
from .loader import load_all_reference_data, load_employee_data, load_job_data, load_org_data
from .performance import generate_performance_reviews


class HRDataGenerator:
    """Orchestrates generation of complete HR datasets."""

    def __init__(self, seed: int | None = None):
        """
        Initialize the generator.

        Args:
            seed: Random seed for reproducibility. If None, uses random state.
        """
        self.rng = np.random.default_rng(seed)
        self.employee_data = load_employee_data()
        self.job_data = load_job_data()
        self.org_data = load_org_data()
        self.reference_data = load_all_reference_data()

    def generate(
        self,
        n_employees: int = 100,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
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
    ) -> dict[str, pd.DataFrame]:
        """
        Generate complete HR dataset.

        Args:
            n_employees: Number of employees to generate
            start_date: Simulation start date (default: 5 years ago)
            end_date: Simulation end date (default: today)
            include_performance: Generate performance reviews
            include_compensation: Generate compensation records
            include_attrition: Apply employee attrition/turnover (default: True)
            attrition_rate: Base annual attrition rate (default: 0.12 = 12%)
            noise_std: Noise standard deviation for attrition probability (default: 0.2)
                - Low (0.1): ML accuracy ~90%+
                - Medium (0.2): ML accuracy ~80-85%
                - High (0.3): ML accuracy ~70-75%
            bu_distribution: Business unit distribution dict mapping BU names to
                proportions (default: 50% Engineering, 30% Sales, 20% Corporate)
            include_hiring: Enable hiring simulation (default: False)
            base_growth_rate: Base annual growth rate for hiring (default: 0.05 = 5%)
            backfill_rate: Fraction of attrition to backfill (default: 0.85 = 85%)
            bu_growth_rates: Per-business-unit growth rate overrides
                (default: Engineering 8%, Sales 5%, Corporate 2%)

        Returns:
            Dictionary of DataFrames:
            - employee: Hub table with manager hierarchy and termination fields
            - employee_org_assignment: Time-variant org placements
            - employee_job_assignment: Time-variant job history
            - employee_compensation: Time-variant salary records
            - employee_performance: Annual performance ratings
            - organization_unit: Reference table
            - job_role: Reference table
            - location: Reference table
        """
        if start_date is None:
            start_date = date(date.today().year - 5, 1, 1)
        elif isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)

        if end_date is None:
            end_date = date.today()
        elif isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        employees = generate_employees_with_bands(
            n_employees,
            self.employee_data,
            self.job_data,
            self.rng,
            start_date=end_date,
            bu_distribution=bu_distribution,
        )

        employees = build_manager_hierarchy(
            employees, self.job_data, self.org_data, self.rng
        )

        errors = validate_hierarchy(employees)
        if errors:
            raise ValueError(f"Hierarchy validation failed: {errors}")

        bu_errors = validate_manager_bu_alignment(employees)
        if bu_errors:
            raise ValueError(f"Business unit alignment validation failed: {bu_errors}")

        job_assignments = generate_job_assignments(
            employees, self.job_data, self.rng, end_date=end_date
        )

        org_assignments = generate_org_assignments(
            employees, job_assignments, self.org_data, self.rng, end_date=end_date
        )

        # Generate compensation if requested
        compensation = None
        if include_compensation:
            compensation = generate_compensation_records(
                employees, job_assignments, self.rng, end_date=end_date
            )

        # Generate performance reviews if requested
        performance = None
        if include_performance:
            performance = generate_performance_reviews(
                employees,
                self.rng,
                start_year=start_date.year,
                end_year=end_date.year,
            )

        # Use combined simulation if both hiring and attrition are enabled
        if include_hiring and include_attrition:
            hiring_model = HiringModel(
                base_growth_rate=base_growth_rate,
                backfill_rate=backfill_rate,
                bu_growth_rates=bu_growth_rates,
            )
            employees, job_assignments, org_assignments, compensation, performance = (
                self._simulate_workforce_dynamics(
                    employees=employees,
                    job_assignments=job_assignments,
                    org_assignments=org_assignments,
                    compensation=compensation,
                    performance=performance,
                    start_year=start_date.year,
                    end_year=end_date.year,
                    attrition_rate=attrition_rate,
                    noise_std=noise_std,
                    hiring_model=hiring_model,
                )
            )
        elif include_hiring:
            # Hiring only (no attrition) - apply growth hires only
            hiring_model = HiringModel(
                base_growth_rate=base_growth_rate,
                backfill_rate=0.0,  # No backfill without attrition
                bu_growth_rates=bu_growth_rates,
            )
            for year in range(start_date.year, end_date.year + 1):
                # Calculate headcount by BU
                active = employees[employees["termination_date"].isna()]
                headcount_by_bu = (
                    active.groupby("_business_unit").size().to_dict()
                    if "_business_unit" in active.columns
                    else {}
                )

                growth_hires = hiring_model.calculate_growth_hires(headcount_by_bu)

                employees, job_assignments, org_assignments, compensation = apply_hiring(
                    employees=employees,
                    job_assignments=job_assignments,
                    org_assignments=org_assignments,
                    compensation=compensation,
                    employee_data=self.employee_data,
                    job_data=self.job_data,
                    org_data=self.org_data,
                    rng=self.rng,
                    year=year,
                    growth_hires_by_bu=growth_hires,
                    backfill_hires_by_bu={},
                    hiring_model=hiring_model,
                )
        elif include_attrition:
            # Attrition only (original behavior)
            employees_with_attrition = apply_attrition(
                employees=employees,
                performance_reviews=performance,
                job_assignments=job_assignments,
                rng=self.rng,
                start_year=start_date.year,
                end_year=end_date.year,
                attrition_rate=attrition_rate,
                noise_std=noise_std,
            )
            employees = employees_with_attrition

            # Close time-variant records at termination
            job_assignments = close_records_at_termination(
                job_assignments, employees_with_attrition
            )
            org_assignments = close_records_at_termination(
                org_assignments, employees_with_attrition
            )
            if compensation is not None:
                compensation = close_records_at_termination(
                    compensation, employees_with_attrition
                )
            if performance is not None:
                performance = filter_reviews_by_termination(
                    performance, employees_with_attrition
                )

        # Build result dictionary
        # Drop internal columns if present
        cols_to_drop = [c for c in ["_seniority_level", "_business_unit"] if c in employees.columns]
        result = {
            "employee": employees.drop(columns=cols_to_drop) if cols_to_drop else employees,
            "employee_job_assignment": job_assignments,
            "employee_org_assignment": org_assignments,
            "organization_unit": self.reference_data["organization_unit"],
            "job_role": self.reference_data["job_role"],
            "location": self.reference_data["location"],
        }

        if compensation is not None:
            result["employee_compensation"] = compensation
        if performance is not None:
            result["employee_performance"] = performance

        return result

    def _simulate_workforce_dynamics(
        self,
        employees: pd.DataFrame,
        job_assignments: pd.DataFrame,
        org_assignments: pd.DataFrame,
        compensation: pd.DataFrame | None,
        performance: pd.DataFrame | None,
        start_year: int,
        end_year: int,
        attrition_rate: float,
        noise_std: float,
        hiring_model: HiringModel,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame | None, pd.DataFrame | None]:
        """
        Run year-by-year simulation with interleaved attrition and hiring.

        For each year:
        1. Calculate growth hires based on current headcount
        2. Apply attrition
        3. Calculate backfill hires based on attrition
        4. Generate new hires (growth + backfill)
        5. Close terminated employees' records

        Args:
            employees: Employee DataFrame with _business_unit column
            job_assignments: Job assignments DataFrame
            org_assignments: Org assignments DataFrame
            compensation: Compensation DataFrame (optional)
            performance: Performance reviews DataFrame (optional)
            start_year: First year of simulation
            end_year: Last year of simulation
            attrition_rate: Base annual attrition rate
            noise_std: Noise for attrition probability
            hiring_model: HiringModel instance for configuration

        Returns:
            Tuple of updated DataFrames:
            (employees, job_assignments, org_assignments, compensation, performance)
        """
        for year in range(start_year, end_year + 1):
            # Step 1: Calculate growth hires based on current active headcount
            active = employees[employees["termination_date"].isna()]
            if "_business_unit" in active.columns:
                headcount_by_bu = active.groupby("_business_unit").size().to_dict()
            else:
                headcount_by_bu = {"Unknown": len(active)}

            growth_hires = hiring_model.calculate_growth_hires(headcount_by_bu)

            # Step 2: Apply attrition for this year
            employees, attrition_by_bu = apply_attrition_for_year(
                employees=employees,
                performance_reviews=performance,
                job_assignments=job_assignments,
                rng=self.rng,
                year=year,
                attrition_rate=attrition_rate,
                noise_std=noise_std,
            )

            # Step 3: Calculate backfill hires
            backfill_hires = hiring_model.calculate_backfill_hires(attrition_by_bu)

            # Step 4: Apply hiring (growth + backfill)
            employees, job_assignments, org_assignments, compensation = apply_hiring(
                employees=employees,
                job_assignments=job_assignments,
                org_assignments=org_assignments,
                compensation=compensation,
                employee_data=self.employee_data,
                job_data=self.job_data,
                org_data=self.org_data,
                rng=self.rng,
                year=year,
                growth_hires_by_bu=growth_hires,
                backfill_hires_by_bu=backfill_hires,
                hiring_model=hiring_model,
            )

            # Step 5: Close time-variant records for terminated employees
            job_assignments = close_records_at_termination(job_assignments, employees)
            org_assignments = close_records_at_termination(org_assignments, employees)
            if compensation is not None:
                compensation = close_records_at_termination(compensation, employees)

        # Final cleanup: filter performance reviews by termination
        if performance is not None:
            performance = filter_reviews_by_termination(performance, employees)

        return employees, job_assignments, org_assignments, compensation, performance


def generate_hr_data(
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
) -> dict[str, pd.DataFrame]:
    """
    Generate complete HR dataset.

    This is the main public API for the library.

    Args:
        n_employees: Number of employees to generate
        start_date: Simulation start date (default: 5 years ago)
        end_date: Simulation end date (default: today)
        seed: Random seed for reproducibility
        include_performance: Generate performance reviews
        include_compensation: Generate compensation records
        include_attrition: Apply employee attrition/turnover (default: True)
        attrition_rate: Base annual attrition rate (default: 0.12 = 12%)
        noise_std: Noise standard deviation for attrition probability.
            Controls ML prediction difficulty:
            - Low (0.1): ML accuracy ~90%+
            - Medium (0.2): ML accuracy ~80-85%
            - High (0.3): ML accuracy ~70-75%
        bu_distribution: Business unit distribution dict mapping BU names to
            proportions (default: 50% Engineering, 30% Sales, 20% Corporate).
            Example: {"Engineering": 0.30, "Sales": 0.50, "Corporate": 0.20}
        include_hiring: Enable hiring simulation (default: False).
            When True, new employees are hired each year based on growth
            rates and backfill needs.
        base_growth_rate: Base annual growth rate for hiring (default: 0.05 = 5%)
        backfill_rate: Fraction of attrition to backfill (default: 0.85 = 85%)
        bu_growth_rates: Per-business-unit growth rate overrides.
            Default: {"Engineering": 0.08, "Sales": 0.05, "Corporate": 0.02}

    Returns:
        Dictionary of DataFrames:
        - employee: Hub table with manager hierarchy and termination fields
        - employee_org_assignment: Time-variant org placements
        - employee_job_assignment: Time-variant job history
        - employee_compensation: Time-variant salary records (if include_compensation=True)
        - employee_performance: Annual performance ratings (if include_performance=True)
        - organization_unit: Reference table
        - job_role: Reference table
        - location: Reference table

    Example:
        >>> from hr_data_generator import generate_hr_data
        >>> data = generate_hr_data(n_employees=500, seed=42)
        >>> employees = data['employee']
        >>> job_history = data['employee_job_assignment']

        # Check attrition rate
        >>> terminated = employees[employees['termination_date'].notna()]
        >>> print(f"Attrition: {len(terminated)/len(employees):.1%}")

        # Custom distribution for a sales-heavy org
        >>> data = generate_hr_data(
        ...     n_employees=100,
        ...     seed=42,
        ...     bu_distribution={"Engineering": 0.30, "Sales": 0.50, "Corporate": 0.20}
        ... )

        # Generate without attrition (all employees remain Active)
        >>> data = generate_hr_data(n_employees=100, seed=42, include_attrition=False)

        # Balanced workforce dynamics with hiring and attrition
        >>> data = generate_hr_data(
        ...     n_employees=100,
        ...     seed=42,
        ...     include_attrition=True,
        ...     include_hiring=True,
        ...     base_growth_rate=0.05,
        ...     backfill_rate=0.85,
        ...     bu_growth_rates={
        ...         "Engineering": 0.08,
        ...         "Sales": 0.05,
        ...         "Corporate": 0.02,
        ...     },
        ... )
        >>> active = data['employee'][data['employee']['termination_date'].isna()]
        >>> print(f"Active employees: {len(active)}")
    """
    generator = HRDataGenerator(seed=seed)
    return generator.generate(
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

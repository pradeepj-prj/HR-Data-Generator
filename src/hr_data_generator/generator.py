"""Main HR Data Generator orchestrator."""

from datetime import date
from typing import Any, Callable, Iterator

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
from .progress import ProgressCallback, ProgressInfo
from .streaming import YearlyDataChunk


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
        progress_callback: ProgressCallback | None = None,
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
            progress_callback: Optional callback function that receives ProgressInfo
                updates during generation. Use for progress bars and status updates.

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

        # Helper to emit progress updates
        def emit_progress(
            phase: str,
            step: int,
            total: int,
            message: str,
            sub_step: int | None = None,
            sub_total: int | None = None,
        ) -> None:
            if progress_callback is not None:
                progress_callback(
                    ProgressInfo(
                        phase=phase,
                        step=step,
                        total_steps=total,
                        message=message,
                        sub_step=sub_step,
                        sub_total=sub_total,
                    )
                )

        # Total steps: employees, hierarchy, jobs, orgs, compensation, performance, dynamics, finalize
        total_steps = 8

        # Step 1: Generate employees
        emit_progress("employees", 1, total_steps, f"Generating {n_employees} employees...")
        employees = generate_employees_with_bands(
            n_employees,
            self.employee_data,
            self.job_data,
            self.rng,
            start_date=end_date,
            bu_distribution=bu_distribution,
        )

        # Step 2: Build hierarchy
        emit_progress("hierarchy", 2, total_steps, "Building manager hierarchy...")
        employees = build_manager_hierarchy(
            employees, self.job_data, self.org_data, self.rng
        )

        errors = validate_hierarchy(employees)
        if errors:
            raise ValueError(f"Hierarchy validation failed: {errors}")

        bu_errors = validate_manager_bu_alignment(employees)
        if bu_errors:
            raise ValueError(f"Business unit alignment validation failed: {bu_errors}")

        # Step 3: Job assignments
        emit_progress("job_assignments", 3, total_steps, "Generating job assignments...")
        job_assignments = generate_job_assignments(
            employees, self.job_data, self.rng, end_date=end_date
        )

        # Step 4: Org assignments
        emit_progress("org_assignments", 4, total_steps, "Generating org assignments...")
        org_assignments = generate_org_assignments(
            employees, job_assignments, self.org_data, self.rng, end_date=end_date
        )

        # Step 5: Generate compensation if requested
        emit_progress("compensation", 5, total_steps, "Generating compensation records...")
        compensation = None
        if include_compensation:
            compensation = generate_compensation_records(
                employees, job_assignments, self.rng, end_date=end_date
            )

        # Step 6: Generate performance reviews if requested
        emit_progress("performance", 6, total_steps, "Generating performance reviews...")
        performance = None
        if include_performance:
            performance = generate_performance_reviews(
                employees,
                self.rng,
                start_year=start_date.year,
                end_year=end_date.year,
            )

        # Step 7: Workforce dynamics (attrition and/or hiring)
        # Use combined simulation if both hiring and attrition are enabled
        if include_hiring and include_attrition:
            emit_progress(
                "workforce_dynamics", 7, total_steps, "Simulating workforce dynamics..."
            )
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
                    progress_callback=progress_callback,
                )
            )
        elif include_hiring:
            # Hiring only (no attrition) - apply growth hires only
            emit_progress("hiring", 7, total_steps, "Simulating hiring...")
            hiring_model = HiringModel(
                base_growth_rate=base_growth_rate,
                backfill_rate=0.0,  # No backfill without attrition
                bu_growth_rates=bu_growth_rates,
            )
            years = list(range(start_date.year, end_date.year + 1))
            for i, year in enumerate(years):
                emit_progress(
                    "hiring", 7, total_steps,
                    f"Simulating hiring for year {year}...",
                    sub_step=i + 1, sub_total=len(years),
                )
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
            emit_progress("attrition", 7, total_steps, "Applying attrition...")
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

        # Step 8: Finalize
        emit_progress("finalize", 8, total_steps, "Finalizing dataset...")

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
        progress_callback: ProgressCallback | None = None,
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
            progress_callback: Optional callback for progress updates

        Returns:
            Tuple of updated DataFrames:
            (employees, job_assignments, org_assignments, compensation, performance)
        """
        years = list(range(start_year, end_year + 1))
        total_years = len(years)

        for i, year in enumerate(years):
            # Emit progress for this year
            if progress_callback is not None:
                progress_callback(
                    ProgressInfo(
                        phase="workforce_dynamics",
                        step=7,
                        total_steps=8,
                        message=f"Simulating year {year} ({i + 1}/{total_years})...",
                        sub_step=i + 1,
                        sub_total=total_years,
                    )
                )

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

    def generate_streaming(
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
    ) -> Iterator[YearlyDataChunk]:
        """
        Generate HR data as a stream of yearly chunks.

        This is the streaming version of generate(). Instead of returning
        a complete dataset, it yields YearlyDataChunk objects year-by-year.

        Args:
            n_employees: Number of initial employees to generate
            start_date: Simulation start date (default: 5 years ago)
            end_date: Simulation end date (default: today)
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
        """
        if start_date is None:
            start_date = date(date.today().year - 5, 1, 1)
        elif isinstance(start_date, str):
            start_date = date.fromisoformat(start_date)

        if end_date is None:
            end_date = date.today()
        elif isinstance(end_date, str):
            end_date = date.fromisoformat(end_date)

        # Generate initial employees
        employees = generate_employees_with_bands(
            n_employees,
            self.employee_data,
            self.job_data,
            self.rng,
            start_date=end_date,
            bu_distribution=bu_distribution,
        )

        # Build hierarchy
        employees = build_manager_hierarchy(
            employees, self.job_data, self.org_data, self.rng
        )

        errors = validate_hierarchy(employees)
        if errors:
            raise ValueError(f"Hierarchy validation failed: {errors}")

        bu_errors = validate_manager_bu_alignment(employees)
        if bu_errors:
            raise ValueError(f"Business unit alignment validation failed: {bu_errors}")

        # Job assignments
        job_assignments = generate_job_assignments(
            employees, self.job_data, self.rng, end_date=end_date
        )

        # Org assignments
        org_assignments = generate_org_assignments(
            employees, job_assignments, self.org_data, self.rng, end_date=end_date
        )

        # Compensation
        compensation = None
        if include_compensation:
            compensation = generate_compensation_records(
                employees, job_assignments, self.rng, end_date=end_date
            )

        # Performance reviews
        performance = None
        if include_performance:
            performance = generate_performance_reviews(
                employees,
                self.rng,
                start_year=start_date.year,
                end_year=end_date.year,
            )

        # If both hiring and attrition are enabled, use streaming workforce dynamics
        if include_hiring and include_attrition:
            hiring_model = HiringModel(
                base_growth_rate=base_growth_rate,
                backfill_rate=backfill_rate,
                bu_growth_rates=bu_growth_rates,
            )
            yield from self._simulate_workforce_dynamics_streaming(
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
        else:
            # For simpler cases (attrition-only, hiring-only, or neither),
            # apply changes and yield a single chunk
            if include_hiring:
                # Hiring only (no attrition)
                hiring_model = HiringModel(
                    base_growth_rate=base_growth_rate,
                    backfill_rate=0.0,
                    bu_growth_rates=bu_growth_rates,
                )
                years = list(range(start_date.year, end_date.year + 1))
                for year in years:
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
                # Attrition only
                employees = apply_attrition(
                    employees=employees,
                    performance_reviews=performance,
                    job_assignments=job_assignments,
                    rng=self.rng,
                    start_year=start_date.year,
                    end_year=end_date.year,
                    attrition_rate=attrition_rate,
                    noise_std=noise_std,
                )
                job_assignments = close_records_at_termination(job_assignments, employees)
                org_assignments = close_records_at_termination(org_assignments, employees)
                if compensation is not None:
                    compensation = close_records_at_termination(compensation, employees)
                if performance is not None:
                    performance = filter_reviews_by_termination(performance, employees)

            # Yield single chunk for non-streaming modes
            cols_to_drop = [c for c in ["_seniority_level", "_business_unit"] if c in employees.columns]
            final_employees = employees.drop(columns=cols_to_drop) if cols_to_drop else employees
            active_count = len(employees[employees["termination_date"].isna()])
            terminated_ids = employees[employees["termination_date"].notna()]["employee_id"].tolist()

            yield YearlyDataChunk(
                year=end_date.year,
                is_initial_year=True,
                is_final_year=True,
                employees=final_employees,
                job_assignments=job_assignments,
                org_assignments=org_assignments,
                compensation=compensation,
                performance=performance,
                terminated_employee_ids=terminated_ids,
                new_hires_count=0,
                terminations_count=len(terminated_ids),
                active_headcount=active_count,
                organization_unit=self.reference_data["organization_unit"],
                job_role=self.reference_data["job_role"],
                location=self.reference_data["location"],
            )

    def _simulate_workforce_dynamics_streaming(
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
    ) -> Iterator[YearlyDataChunk]:
        """
        Run year-by-year simulation yielding chunks after each year.

        This is the streaming version of _simulate_workforce_dynamics().
        Instead of returning final DataFrames, it yields YearlyDataChunk
        after each year's processing.

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

        Yields:
            YearlyDataChunk: Data chunk for each simulation year
        """
        years = list(range(start_year, end_year + 1))
        total_years = len(years)

        # Track employees at start of simulation
        initial_employee_ids = set(employees["employee_id"].tolist())

        for i, year in enumerate(years):
            is_initial = i == 0
            is_final = i == total_years - 1

            # Track employee count before changes
            employees_before = set(employees["employee_id"].tolist())
            active_before = employees[employees["termination_date"].isna()]["employee_id"].tolist()

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

            # Identify terminated employees this year
            terminated_this_year = employees[
                (employees["termination_date"].notna()) &
                (employees["employee_id"].isin(active_before))
            ]
            terminated_ids = terminated_this_year["employee_id"].tolist()
            terminations_count = sum(attrition_by_bu.values())

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

            # Count new hires
            employees_after = set(employees["employee_id"].tolist())
            new_hire_ids = employees_after - employees_before
            new_hires_count = len(new_hire_ids)

            # Step 5: Close time-variant records for terminated employees
            job_assignments = close_records_at_termination(job_assignments, employees)
            org_assignments = close_records_at_termination(org_assignments, employees)
            if compensation is not None:
                compensation = close_records_at_termination(compensation, employees)

            # Final year: filter performance reviews
            if is_final and performance is not None:
                performance = filter_reviews_by_termination(performance, employees)

            # Prepare chunk data
            # For initial year, include reference data
            # For subsequent years, only include changed/new records
            cols_to_drop = [c for c in ["_seniority_level", "_business_unit"] if c in employees.columns]
            chunk_employees = employees.drop(columns=cols_to_drop) if cols_to_drop else employees.copy()

            active_headcount = len(employees[employees["termination_date"].isna()])

            yield YearlyDataChunk(
                year=year,
                is_initial_year=is_initial,
                is_final_year=is_final,
                employees=chunk_employees,
                job_assignments=job_assignments,
                org_assignments=org_assignments,
                compensation=compensation,
                performance=performance if is_final else None,  # Only include performance in final year
                terminated_employee_ids=terminated_ids,
                new_hires_count=new_hires_count,
                terminations_count=terminations_count,
                active_headcount=active_headcount,
                organization_unit=self.reference_data["organization_unit"] if is_initial else None,
                job_role=self.reference_data["job_role"] if is_initial else None,
                location=self.reference_data["location"] if is_initial else None,
            )


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
    progress_callback: ProgressCallback | None = None,
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
        progress_callback: Optional callback function that receives ProgressInfo
            updates during generation. Use for progress bars and status updates.

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
        progress_callback=progress_callback,
    )

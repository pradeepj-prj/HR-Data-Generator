"""Main HR Data Generator orchestrator."""

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .assignments import generate_job_assignments, generate_org_assignments
from .compensation import generate_compensation_records
from .employee import generate_employees_with_bands
from .hierarchy import build_manager_hierarchy, validate_hierarchy
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
    ) -> dict[str, pd.DataFrame]:
        """
        Generate complete HR dataset.

        Args:
            n_employees: Number of employees to generate
            start_date: Simulation start date (default: 5 years ago)
            end_date: Simulation end date (default: today)
            include_performance: Generate performance reviews
            include_compensation: Generate compensation records

        Returns:
            Dictionary of DataFrames:
            - employee: Hub table with manager hierarchy
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
        )

        employees = build_manager_hierarchy(
            employees, self.job_data, self.org_data, self.rng
        )

        errors = validate_hierarchy(employees)
        if errors:
            raise ValueError(f"Hierarchy validation failed: {errors}")

        job_assignments = generate_job_assignments(
            employees, self.job_data, self.rng, end_date=end_date
        )

        org_assignments = generate_org_assignments(
            employees, job_assignments, self.org_data, self.rng, end_date=end_date
        )

        result = {
            "employee": employees.drop(columns=["_seniority_level"]),
            "employee_job_assignment": job_assignments,
            "employee_org_assignment": org_assignments,
            "organization_unit": self.reference_data["organization_unit"],
            "job_role": self.reference_data["job_role"],
            "location": self.reference_data["location"],
        }

        if include_compensation:
            compensation = generate_compensation_records(
                employees, job_assignments, self.rng, end_date=end_date
            )
            result["employee_compensation"] = compensation

        if include_performance:
            performance = generate_performance_reviews(
                employees,
                self.rng,
                start_year=start_date.year,
                end_year=end_date.year,
            )
            result["employee_performance"] = performance

        return result


def generate_hr_data(
    n_employees: int = 100,
    start_date: str | date | None = None,
    end_date: str | date | None = None,
    seed: int | None = None,
    include_performance: bool = True,
    include_compensation: bool = True,
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

    Returns:
        Dictionary of DataFrames:
        - employee: Hub table with manager hierarchy
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
    """
    generator = HRDataGenerator(seed=seed)
    return generator.generate(
        n_employees=n_employees,
        start_date=start_date,
        end_date=end_date,
        include_performance=include_performance,
        include_compensation=include_compensation,
    )

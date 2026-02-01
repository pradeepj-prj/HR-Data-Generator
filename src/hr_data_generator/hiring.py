"""Employee hiring/growth generation module for workforce dynamics simulation."""

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd


# Default new hire seniority distribution (skews junior)
DEFAULT_NEW_HIRE_SENIORITY_WEIGHTS = {
    1: 0.40,  # Junior - 40%
    2: 0.30,  # Mid - 30%
    3: 0.20,  # Senior - 20%
    4: 0.08,  # Manager/Staff - 8%
    5: 0.02,  # Director - 2%
}

# Default business unit growth rates
DEFAULT_BU_GROWTH_RATES = {
    "Engineering": 0.08,  # Tech companies grow engineering faster
    "Sales": 0.05,        # Standard growth
    "Corporate": 0.02,    # Slower growth for support functions
}


class HiringModel:
    """Model for calculating hiring needs and generating new employees."""

    def __init__(
        self,
        base_growth_rate: float = 0.05,
        backfill_rate: float = 0.85,
        bu_growth_rates: dict[str, float] | None = None,
        new_hire_seniority_weights: dict[int, float] | None = None,
    ):
        """
        Initialize the hiring model.

        Args:
            base_growth_rate: Base annual growth rate (default 5%)
            backfill_rate: Fraction of attrition to backfill (default 85%)
            bu_growth_rates: Per-business-unit growth rate overrides
            new_hire_seniority_weights: Distribution of seniority levels for new hires
        """
        self.base_growth_rate = base_growth_rate
        self.backfill_rate = backfill_rate
        self.bu_growth_rates = bu_growth_rates or DEFAULT_BU_GROWTH_RATES.copy()
        self.new_hire_seniority_weights = (
            new_hire_seniority_weights or DEFAULT_NEW_HIRE_SENIORITY_WEIGHTS.copy()
        )

    def get_growth_rate(self, business_unit: str) -> float:
        """Get growth rate for a specific business unit."""
        return self.bu_growth_rates.get(business_unit, self.base_growth_rate)

    def calculate_growth_hires(
        self,
        headcount_by_bu: dict[str, int],
    ) -> dict[str, int]:
        """
        Calculate number of growth hires needed per business unit.

        Args:
            headcount_by_bu: Current headcount by business unit

        Returns:
            Dict of business_unit -> number of growth hires
        """
        growth_hires = {}
        for bu, count in headcount_by_bu.items():
            rate = self.get_growth_rate(bu)
            # Use Poisson distribution for small counts, deterministic for larger
            if count < 50:
                # For small teams, use expected value with some variance
                expected = count * rate
                growth_hires[bu] = max(0, int(round(expected)))
            else:
                growth_hires[bu] = int(count * rate)
        return growth_hires

    def calculate_backfill_hires(
        self,
        attrition_by_bu: dict[str, int],
    ) -> dict[str, int]:
        """
        Calculate number of backfill hires needed per business unit.

        Args:
            attrition_by_bu: Number of employees who left per business unit

        Returns:
            Dict of business_unit -> number of backfill hires
        """
        backfill_hires = {}
        for bu, attrition in attrition_by_bu.items():
            backfill_hires[bu] = int(attrition * self.backfill_rate)
        return backfill_hires

    def select_seniority_level(self, rng: np.random.Generator) -> int:
        """Select a seniority level for a new hire based on weights."""
        levels = list(self.new_hire_seniority_weights.keys())
        weights = list(self.new_hire_seniority_weights.values())
        # Normalize weights
        total = sum(weights)
        probs = [w / total for w in weights]
        return int(rng.choice(levels, p=probs))


def generate_new_hire(
    year: int,
    employee_data: dict[str, Any],
    rng: np.random.Generator,
    employee_id: str,
    business_unit: str,
    seniority_level: int,
) -> dict[str, Any]:
    """
    Generate a single new hire employee record.

    Args:
        year: Year of hire
        employee_data: Employee configuration data
        rng: Random number generator
        employee_id: ID to assign to this employee
        business_unit: Business unit assignment
        seniority_level: Seniority level (1-5)

    Returns:
        Dict with employee record fields
    """
    # Import here to avoid circular dependency
    from .employee import (
        get_age_for_band,
        get_birth_date,
        get_employment_type,
        get_location,
        get_name,
    )

    # Generate age appropriate for seniority level
    age = get_age_for_band(seniority_level, employee_data, rng)

    # Generate gender
    gender_roll = rng.random()
    if gender_roll < employee_data["prob_neutral"]:
        gender = "na"
    elif gender_roll < employee_data["prob_neutral"] + employee_data["prob_female"]:
        gender = "female"
    else:
        gender = "male"

    first_name, last_name = get_name(gender, employee_data, rng)

    # Generate hire date within the year
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    days_in_year = (year_end - year_start).days
    random_days = rng.integers(0, days_in_year + 1)
    hire_date = year_start + timedelta(days=int(random_days))

    birth_date = get_birth_date(age, hire_date, rng)
    emp_type = get_employment_type(employee_data, rng)
    location = get_location(employee_data, rng)

    return {
        "employee_id": employee_id,
        "first_name": first_name,
        "last_name": last_name,
        "gender": gender,
        "birth_date": birth_date,
        "hire_date": hire_date,
        "employment_type": emp_type,
        "employment_status": "Active",
        "location_id": location,
        "termination_date": None,
        "termination_reason": None,
        "_seniority_level": seniority_level,
        "_business_unit": business_unit,
    }


def generate_new_hire_job_assignment(
    employee: dict[str, Any],
    job_data: pd.DataFrame,
    rng: np.random.Generator,
    end_date: date,
) -> dict[str, Any]:
    """
    Generate job assignment record for a new hire.

    Args:
        employee: Employee record dict
        job_data: Job reference data
        rng: Random number generator
        end_date: Simulation end date

    Returns:
        Job assignment record dict
    """
    seniority_level = employee["_seniority_level"]

    # Filter jobs by seniority level (jobs aren't tied to business units)
    matching_jobs = job_data[job_data["seniority_level"] == seniority_level]

    if len(matching_jobs) == 0:
        # Last resort: any job
        matching_jobs = job_data

    job = matching_jobs.iloc[rng.integers(0, len(matching_jobs))]

    return {
        "employee_id": employee["employee_id"],
        "job_id": job["job_id"],
        "job_title": job["job_title"],
        "seniority_level": seniority_level,
        "start_date": employee["hire_date"],
        "end_date": None,  # Open-ended
    }


def generate_new_hire_org_assignment(
    employee: dict[str, Any],
    org_data: pd.DataFrame,
    rng: np.random.Generator,
) -> dict[str, Any]:
    """
    Generate org assignment record for a new hire.

    Args:
        employee: Employee record dict
        org_data: Organization reference data
        rng: Random number generator

    Returns:
        Org assignment record dict
    """
    business_unit = employee["_business_unit"]

    # Find departments in this business unit
    matching_orgs = org_data[org_data["business_unit"] == business_unit]

    if len(matching_orgs) == 0:
        matching_orgs = org_data

    org = matching_orgs.iloc[rng.integers(0, len(matching_orgs))]

    return {
        "employee_id": employee["employee_id"],
        "org_unit_id": org["org_id"],
        "start_date": employee["hire_date"],
        "end_date": None,  # Open-ended
    }


def generate_new_hire_compensation(
    employee: dict[str, Any],
    job_assignment: dict[str, Any],
    rng: np.random.Generator,
) -> dict[str, Any]:
    """
    Generate compensation record for a new hire.

    Args:
        employee: Employee record dict
        job_assignment: Job assignment record dict
        rng: Random number generator

    Returns:
        Compensation record dict
    """
    # Base salary by seniority level (simplified model)
    base_salaries = {
        1: 50000,   # Junior
        2: 70000,   # Mid
        3: 95000,   # Senior
        4: 120000,  # Manager/Staff
        5: 160000,  # Director
    }

    seniority = employee["_seniority_level"]
    base = base_salaries.get(seniority, 60000)

    # Add some variance (+/- 15%)
    variance = rng.uniform(0.85, 1.15)
    salary = int(base * variance)

    return {
        "employee_id": employee["employee_id"],
        "annual_salary": salary,
        "currency": "USD",
        "start_date": employee["hire_date"],
        "end_date": None,
    }


def select_manager_for_new_hire(
    employee: dict[str, Any],
    employees_df: pd.DataFrame,
    job_assignments_df: pd.DataFrame,
    year: int,
    rng: np.random.Generator,
) -> str | None:
    """
    Select an appropriate manager for a new hire.

    Args:
        employee: New hire employee record dict
        employees_df: Current employees DataFrame
        job_assignments_df: Current job assignments DataFrame
        year: Current simulation year
        rng: Random number generator

    Returns:
        Manager's employee_id or None if no suitable manager found
    """
    business_unit = employee["_business_unit"]
    seniority_level = employee["_seniority_level"]
    hire_date = employee["hire_date"]

    # Find active employees who could be managers (higher seniority, same BU)
    active_employees = employees_df[
        (employees_df["termination_date"].isna())
        & (employees_df["hire_date"] < hire_date)
    ]

    if len(active_employees) == 0:
        return None

    # Get current job assignments to check seniority
    year_end = date(year, 12, 31)
    current_jobs = job_assignments_df[
        (job_assignments_df["start_date"] <= year_end)
        & (
            (job_assignments_df["end_date"].isna())
            | (job_assignments_df["end_date"] >= year_end)
        )
    ]

    # Find potential managers (higher seniority level)
    potential_managers = []
    for _, emp in active_employees.iterrows():
        emp_jobs = current_jobs[current_jobs["employee_id"] == emp["employee_id"]]
        if len(emp_jobs) > 0:
            emp_seniority = emp_jobs.iloc[-1]["seniority_level"]
            if emp_seniority > seniority_level:
                # Check if in same business unit (via _business_unit if available)
                if "_business_unit" in emp and emp["_business_unit"] == business_unit:
                    potential_managers.append(emp["employee_id"])
                elif "_business_unit" not in emp:
                    # Fallback: accept any higher-level manager
                    potential_managers.append(emp["employee_id"])

    if len(potential_managers) == 0:
        # No suitable manager in same BU, try any higher-level employee
        for _, emp in active_employees.iterrows():
            emp_jobs = current_jobs[current_jobs["employee_id"] == emp["employee_id"]]
            if len(emp_jobs) > 0:
                emp_seniority = emp_jobs.iloc[-1]["seniority_level"]
                if emp_seniority > seniority_level:
                    potential_managers.append(emp["employee_id"])

    if len(potential_managers) == 0:
        return None

    return rng.choice(potential_managers)


def get_next_employee_id(employees_df: pd.DataFrame) -> tuple[int, str]:
    """
    Get the next employee ID number and formatted string.

    Args:
        employees_df: Current employees DataFrame

    Returns:
        Tuple of (next_id_number, formatted_id_string)
    """
    if len(employees_df) == 0:
        return 1, "EMP000001"

    # Extract numeric parts from employee IDs
    max_id = 0
    for emp_id in employees_df["employee_id"]:
        try:
            num = int(emp_id.replace("EMP", ""))
            max_id = max(max_id, num)
        except (ValueError, AttributeError):
            continue

    next_id = max_id + 1
    return next_id, f"EMP{next_id:06d}"


def apply_hiring(
    employees: pd.DataFrame,
    job_assignments: pd.DataFrame,
    org_assignments: pd.DataFrame,
    compensation: pd.DataFrame | None,
    employee_data: dict[str, Any],
    job_data: pd.DataFrame,
    org_data: pd.DataFrame,
    rng: np.random.Generator,
    year: int,
    growth_hires_by_bu: dict[str, int],
    backfill_hires_by_bu: dict[str, int],
    hiring_model: HiringModel,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    """
    Apply hiring for a single year.

    Args:
        employees: Current employees DataFrame
        job_assignments: Current job assignments DataFrame
        org_assignments: Current org assignments DataFrame
        compensation: Current compensation DataFrame (or None)
        employee_data: Employee generation configuration
        job_data: Job reference data
        org_data: Organization reference data
        rng: Random number generator
        year: Year to generate hires for
        growth_hires_by_bu: Growth hires needed per business unit
        backfill_hires_by_bu: Backfill hires needed per business unit
        hiring_model: HiringModel instance for configuration

    Returns:
        Tuple of updated (employees, job_assignments, org_assignments, compensation)
    """
    new_employees = []
    new_job_assignments = []
    new_org_assignments = []
    new_compensation = []

    next_id_num, _ = get_next_employee_id(employees)

    # Combine growth and backfill hires
    all_bus = set(growth_hires_by_bu.keys()) | set(backfill_hires_by_bu.keys())

    for bu in all_bus:
        growth = growth_hires_by_bu.get(bu, 0)
        backfill = backfill_hires_by_bu.get(bu, 0)
        total_hires = growth + backfill

        for _ in range(total_hires):
            employee_id = f"EMP{next_id_num:06d}"
            next_id_num += 1

            seniority = hiring_model.select_seniority_level(rng)

            # Generate the new hire
            emp = generate_new_hire(
                year=year,
                employee_data=employee_data,
                rng=rng,
                employee_id=employee_id,
                business_unit=bu,
                seniority_level=seniority,
            )
            new_employees.append(emp)

            # Generate job assignment
            job_assign = generate_new_hire_job_assignment(
                employee=emp,
                job_data=job_data,
                rng=rng,
                end_date=date(year, 12, 31),
            )
            new_job_assignments.append(job_assign)

            # Generate org assignment
            org_assign = generate_new_hire_org_assignment(
                employee=emp,
                org_data=org_data,
                rng=rng,
            )
            new_org_assignments.append(org_assign)

            # Generate compensation if we're tracking it
            if compensation is not None:
                comp = generate_new_hire_compensation(
                    employee=emp,
                    job_assignment=job_assign,
                    rng=rng,
                )
                new_compensation.append(comp)

    # Append new records to existing DataFrames
    if new_employees:
        new_emp_df = pd.DataFrame(new_employees)
        employees = pd.concat([employees, new_emp_df], ignore_index=True)

    if new_job_assignments:
        new_job_df = pd.DataFrame(new_job_assignments)
        job_assignments = pd.concat([job_assignments, new_job_df], ignore_index=True)

    if new_org_assignments:
        new_org_df = pd.DataFrame(new_org_assignments)
        org_assignments = pd.concat([org_assignments, new_org_df], ignore_index=True)

    if new_compensation and compensation is not None:
        new_comp_df = pd.DataFrame(new_compensation)
        compensation = pd.concat([compensation, new_comp_df], ignore_index=True)

    # Assign managers to new hires
    for emp in new_employees:
        manager_id = select_manager_for_new_hire(
            employee=emp,
            employees_df=employees,
            job_assignments_df=job_assignments,
            year=year,
            rng=rng,
        )
        if manager_id:
            mask = employees["employee_id"] == emp["employee_id"]
            employees.loc[mask, "manager_id"] = manager_id

    return employees, job_assignments, org_assignments, compensation

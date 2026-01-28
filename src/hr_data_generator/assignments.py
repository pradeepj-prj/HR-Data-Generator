"""Organization and job assignment generators."""

from datetime import date, timedelta

import numpy as np
import pandas as pd


JOB_FAMILY_TO_BUSINESS_UNIT = {
    "Engineering": "Engineering",
    "Sales": "Sales",
    "Corporate": "Corporate",
}


def get_compatible_orgs(
    job_family: str, org_data: pd.DataFrame
) -> pd.DataFrame:
    """Get organizations compatible with a job family."""
    business_unit = JOB_FAMILY_TO_BUSINESS_UNIT.get(job_family, "Corporate")

    compatible = org_data[org_data["business_unit"] == business_unit]
    if len(compatible) == 0:
        return org_data
    return compatible


def get_jobs_for_seniority(
    seniority_level: int, job_data: pd.DataFrame
) -> pd.DataFrame:
    """Get jobs matching a seniority level."""
    return job_data[job_data["seniority_level"] == seniority_level]


def generate_initial_job_assignment(
    employee: pd.Series,
    job_data: pd.DataFrame,
    rng: np.random.Generator,
) -> dict:
    """Generate initial job assignment for an employee."""
    seniority = employee.get("_seniority_level", 1)
    matching_jobs = get_jobs_for_seniority(seniority, job_data)

    if len(matching_jobs) == 0:
        matching_jobs = job_data[job_data["seniority_level"] <= seniority]
        if len(matching_jobs) == 0:
            matching_jobs = job_data

    job_idx = rng.integers(0, len(matching_jobs))
    job = matching_jobs.iloc[job_idx]

    hire_date = employee["hire_date"]
    if isinstance(hire_date, str):
        hire_date = date.fromisoformat(hire_date)

    return {
        "employee_id": employee["employee_id"],
        "job_id": job["job_id"],
        "job_title": job["job_title"],
        "job_family": job["job_family"],
        "job_level": job["job_level"],
        "seniority_level": job["seniority_level"],
        "start_date": hire_date,
        "end_date": None,
    }


def generate_initial_org_assignment(
    employee: pd.Series,
    job_assignment: dict,
    org_data: pd.DataFrame,
    rng: np.random.Generator,
) -> dict:
    """Generate initial org assignment aligned with job family."""
    job_family = job_assignment["job_family"]
    compatible_orgs = get_compatible_orgs(job_family, org_data)

    leaf_orgs = compatible_orgs[
        ~compatible_orgs["org_id"].isin(compatible_orgs["parent_org_id"].dropna())
    ]
    if len(leaf_orgs) == 0:
        leaf_orgs = compatible_orgs

    org_idx = rng.integers(0, len(leaf_orgs))
    org = leaf_orgs.iloc[org_idx]

    hire_date = employee["hire_date"]
    if isinstance(hire_date, str):
        hire_date = date.fromisoformat(hire_date)

    return {
        "employee_id": employee["employee_id"],
        "org_id": org["org_id"],
        "org_name": org["org_name"],
        "cost_center": org["cost_center"],
        "business_unit": org["business_unit"],
        "start_date": hire_date,
        "end_date": None,
    }


def generate_job_assignments(
    employees: pd.DataFrame,
    job_data: pd.DataFrame,
    rng: np.random.Generator,
    end_date: date | None = None,
    promotion_probability: float = 0.12,
) -> pd.DataFrame:
    """
    Generate job assignment history with promotions.

    Creates initial assignments for all employees, then simulates
    promotions based on tenure and probability.
    """
    if end_date is None:
        end_date = date.today()

    all_assignments = []

    for _, emp in employees.iterrows():
        initial = generate_initial_job_assignment(emp, job_data, rng)
        assignments = [initial]

        hire_date = emp["hire_date"]
        if isinstance(hire_date, str):
            hire_date = date.fromisoformat(hire_date)

        current_seniority = initial["seniority_level"]
        current_start = initial["start_date"]
        years_employed = (end_date - hire_date).days // 365

        for year in range(1, years_employed + 1):
            if current_seniority >= 5:
                break

            if rng.random() < promotion_probability:
                promo_date = hire_date + timedelta(days=year * 365)
                if promo_date > end_date:
                    break

                assignments[-1]["end_date"] = promo_date - timedelta(days=1)

                new_seniority = current_seniority + 1
                new_jobs = get_jobs_for_seniority(new_seniority, job_data)

                if len(new_jobs) > 0:
                    same_family = new_jobs[
                        new_jobs["job_family"] == assignments[-1]["job_family"]
                    ]
                    if len(same_family) > 0:
                        new_jobs = same_family

                    job_idx = rng.integers(0, len(new_jobs))
                    new_job = new_jobs.iloc[job_idx]

                    assignments.append({
                        "employee_id": emp["employee_id"],
                        "job_id": new_job["job_id"],
                        "job_title": new_job["job_title"],
                        "job_family": new_job["job_family"],
                        "job_level": new_job["job_level"],
                        "seniority_level": new_job["seniority_level"],
                        "start_date": promo_date,
                        "end_date": None,
                    })
                    current_seniority = new_seniority

        all_assignments.extend(assignments)

    return pd.DataFrame(all_assignments)


def generate_org_assignments(
    employees: pd.DataFrame,
    job_assignments: pd.DataFrame,
    org_data: pd.DataFrame,
    rng: np.random.Generator,
    end_date: date | None = None,
    transfer_probability: float = 0.05,
) -> pd.DataFrame:
    """
    Generate org assignment history with transfers.

    Creates initial assignments aligned with job family, then simulates
    occasional transfers.
    """
    if end_date is None:
        end_date = date.today()

    all_assignments = []

    for _, emp in employees.iterrows():
        emp_jobs = job_assignments[
            job_assignments["employee_id"] == emp["employee_id"]
        ]
        if len(emp_jobs) == 0:
            continue

        first_job = emp_jobs.iloc[0]
        initial = generate_initial_org_assignment(
            emp, first_job.to_dict(), org_data, rng
        )
        assignments = [initial]

        hire_date = emp["hire_date"]
        if isinstance(hire_date, str):
            hire_date = date.fromisoformat(hire_date)

        years_employed = (end_date - hire_date).days // 365

        for year in range(2, years_employed + 1):
            if rng.random() < transfer_probability:
                transfer_date = hire_date + timedelta(days=year * 365)
                if transfer_date > end_date:
                    break

                assignments[-1]["end_date"] = transfer_date - timedelta(days=1)

                current_job = emp_jobs[
                    (emp_jobs["start_date"] <= transfer_date)
                    & ((emp_jobs["end_date"].isna()) | (emp_jobs["end_date"] >= transfer_date))
                ]
                if len(current_job) == 0:
                    current_job = emp_jobs.iloc[-1:]

                job_family = current_job.iloc[0]["job_family"]
                compatible_orgs = get_compatible_orgs(job_family, org_data)

                current_org = assignments[-1]["org_id"]
                other_orgs = compatible_orgs[compatible_orgs["org_id"] != current_org]
                if len(other_orgs) == 0:
                    other_orgs = compatible_orgs

                org_idx = rng.integers(0, len(other_orgs))
                new_org = other_orgs.iloc[org_idx]

                assignments.append({
                    "employee_id": emp["employee_id"],
                    "org_id": new_org["org_id"],
                    "org_name": new_org["org_name"],
                    "cost_center": new_org["cost_center"],
                    "business_unit": new_org["business_unit"],
                    "start_date": transfer_date,
                    "end_date": None,
                })

        all_assignments.extend(assignments)

    return pd.DataFrame(all_assignments)

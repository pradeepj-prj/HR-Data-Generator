"""Compensation generation module."""

from datetime import date, timedelta

import numpy as np
import pandas as pd


SALARY_RANGES = {
    1: (50_000, 75_000),
    2: (70_000, 100_000),
    3: (90_000, 140_000),
    4: (130_000, 200_000),
    5: (180_000, 300_000),
}

BONUS_TARGETS = {
    "IC": 0.10,
    "Manager": 0.15,
    "Director": 0.20,
}


def generate_base_salary(
    seniority_level: int, rng: np.random.Generator
) -> float:
    """Generate base salary based on seniority level."""
    min_sal, max_sal = SALARY_RANGES.get(seniority_level, SALARY_RANGES[1])
    return round(rng.uniform(min_sal, max_sal), 2)


def generate_bonus_target(job_level: str) -> float:
    """Get bonus target percentage based on job level."""
    return BONUS_TARGETS.get(job_level, 0.10)


def generate_compensation_records(
    employees: pd.DataFrame,
    job_assignments: pd.DataFrame,
    rng: np.random.Generator,
    end_date: date | None = None,
    annual_raise_min: float = 0.02,
    annual_raise_max: float = 0.05,
    promotion_raise_min: float = 0.08,
    promotion_raise_max: float = 0.15,
) -> pd.DataFrame:
    """
    Generate compensation history for all employees.

    Creates records:
    - Initial salary at hire
    - Annual merit increases
    - Promotion-based salary increases
    """
    if end_date is None:
        end_date = date.today()

    all_records = []

    for _, emp in employees.iterrows():
        emp_jobs = job_assignments[
            job_assignments["employee_id"] == emp["employee_id"]
        ].sort_values("start_date")

        if len(emp_jobs) == 0:
            continue

        hire_date = emp["hire_date"]
        if isinstance(hire_date, str):
            hire_date = date.fromisoformat(hire_date)

        first_job = emp_jobs.iloc[0]
        seniority = first_job["seniority_level"]
        job_level = first_job["job_level"]

        current_salary = generate_base_salary(seniority, rng)
        bonus_target = generate_bonus_target(job_level)

        records = [{
            "employee_id": emp["employee_id"],
            "base_salary": current_salary,
            "bonus_target_pct": bonus_target,
            "currency": "USD",
            "start_date": hire_date,
            "end_date": None,
            "change_reason": "New Hire",
        }]

        years_employed = (end_date - hire_date).days // 365
        current_start = hire_date

        for year in range(1, years_employed + 1):
            review_date = date(hire_date.year + year, 4, 1)
            if review_date > end_date:
                break

            job_at_review = emp_jobs[
                (emp_jobs["start_date"] <= review_date)
                & ((emp_jobs["end_date"].isna()) | (emp_jobs["end_date"] >= review_date))
            ]

            if len(job_at_review) == 0:
                job_at_review = emp_jobs[emp_jobs["start_date"] <= review_date]
                if len(job_at_review) == 0:
                    continue
                job_at_review = job_at_review.iloc[-1:]

            current_job = job_at_review.iloc[0]
            current_seniority = current_job["seniority_level"]
            current_job_level = current_job["job_level"]

            was_promoted = False
            for _, job in emp_jobs.iterrows():
                job_start = job["start_date"]
                if isinstance(job_start, str):
                    job_start = date.fromisoformat(job_start)
                prev_review = date(hire_date.year + year - 1, 4, 1)
                if prev_review < job_start <= review_date:
                    was_promoted = True
                    break

            if was_promoted:
                raise_pct = rng.uniform(promotion_raise_min, promotion_raise_max)
                change_reason = "Promotion"
            else:
                raise_pct = rng.uniform(annual_raise_min, annual_raise_max)
                change_reason = "Annual Merit"

            records[-1]["end_date"] = review_date - timedelta(days=1)

            new_salary = round(current_salary * (1 + raise_pct), 2)
            new_bonus = generate_bonus_target(current_job_level)

            records.append({
                "employee_id": emp["employee_id"],
                "base_salary": new_salary,
                "bonus_target_pct": new_bonus,
                "currency": "USD",
                "start_date": review_date,
                "end_date": None,
                "change_reason": change_reason,
            })

            current_salary = new_salary

        all_records.extend(records)

    return pd.DataFrame(all_records)

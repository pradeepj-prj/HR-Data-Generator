"""Employee generation module with seeded randomness."""

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd


def get_age_for_band(
    band: int, employee_data: dict[str, Any], rng: np.random.Generator
) -> int:
    """Generate age based on seniority band profile."""
    band_profiles = {
        5: employee_data.get("leader_profile", {"age_min": 45, "age_max": 65}),
        4: employee_data.get("band_4_profile", {"age_min": 40, "age_max": 65}),
        3: employee_data.get("band_3_profile", {"age_min": 30, "age_max": 60}),
        2: employee_data.get("band_2_profile", {"age_min": 22, "age_max": 45}),
        1: employee_data.get("band_1_profile", {"age_min": 21, "age_max": 40}),
    }
    profile = band_profiles.get(band, band_profiles[1])
    age_min = profile["age_min"]
    age_max = profile["age_max"]
    return int(rng.integers(age_min, age_max + 1))


def get_age_gender(
    employee_data: dict[str, Any], rng: np.random.Generator
) -> tuple[int, str]:
    """Generate age and gender for an employee."""
    age = int(
        rng.normal(
            loc=employee_data["age_mean"],
            scale=employee_data["age_spread"],
        )
    )
    age = max(21, min(70, age))

    gender_roll = rng.random()
    if gender_roll < employee_data["prob_neutral"]:
        gender = "na"
    elif gender_roll < employee_data["prob_neutral"] + employee_data["prob_female"]:
        gender = "female"
    else:
        gender = "male"

    return age, gender


def get_name(
    gender: str, employee_data: dict[str, Any], rng: np.random.Generator
) -> tuple[str, str]:
    """Generate first and last name based on gender."""
    if gender == "female":
        first_name_choices = employee_data["female_names"]
    elif gender == "male":
        first_name_choices = employee_data["male_first_names"]
    else:
        first_name_choices = employee_data["neutral_names"]

    first_name = rng.choice(first_name_choices)
    last_name = rng.choice(employee_data["male_last_names"])

    return first_name, last_name


def get_hire_date(
    age: int, rng: np.random.Generator, reference_date: date | None = None
) -> date:
    """Generate realistic hire date based on age (career start at 21)."""
    if reference_date is None:
        reference_date = date.today()

    start_year = reference_date.year - age + 21
    if start_year > reference_date.year:
        return reference_date

    start = date(start_year, 1, 1)
    end = reference_date
    delta_days = (end - start).days
    if delta_days <= 0:
        return reference_date

    random_days = rng.integers(0, delta_days + 1)
    return start + timedelta(days=int(random_days))


def get_birth_date(age: int, hire_date: date, rng: np.random.Generator) -> date:
    """Calculate birth date from age, ensuring consistency with hire date."""
    birth_year = hire_date.year - age
    birth_month = rng.integers(1, 13)
    max_day = 28 if birth_month == 2 else (30 if birth_month in [4, 6, 9, 11] else 31)
    birth_day = rng.integers(1, max_day + 1)
    return date(birth_year, int(birth_month), int(birth_day))


def get_employment_type(
    employee_data: dict[str, Any], rng: np.random.Generator
) -> str:
    """Generate employment type with probabilities from config."""
    roll = rng.random()
    if roll < employee_data["prob_full_time"]:
        return "Full-time"
    elif roll < employee_data["prob_contract"]:
        return "Contract"
    else:
        return "Part-time"


def get_location(
    employee_data: dict[str, Any], rng: np.random.Generator
) -> str:
    """Select a location ID from available locations."""
    return rng.choice(employee_data["location_id"])


def generate_employee_demographics(
    n: int,
    employee_data: dict[str, Any],
    rng: np.random.Generator,
    start_date: date | None = None,
) -> pd.DataFrame:
    """
    Generate base employee demographics.

    Returns DataFrame with: employee_id, first_name, last_name, gender,
    birth_date, hire_date, employment_type, employment_status, location_id
    """
    if start_date is None:
        start_date = date.today()

    employees = []
    for i in range(n):
        age, gender = get_age_gender(employee_data, rng)
        first_name, last_name = get_name(gender, employee_data, rng)
        hire_date = get_hire_date(age, rng, start_date)
        birth_date = get_birth_date(age, hire_date, rng)
        emp_type = get_employment_type(employee_data, rng)
        location = get_location(employee_data, rng)

        employees.append({
            "employee_id": f"EMP{i+1:06d}",
            "first_name": first_name,
            "last_name": last_name,
            "gender": gender,
            "birth_date": birth_date,
            "hire_date": hire_date,
            "employment_type": emp_type,
            "employment_status": "Active",
            "location_id": location,
        })

    return pd.DataFrame(employees)


def generate_employees_with_bands(
    n: int,
    employee_data: dict[str, Any],
    job_data: pd.DataFrame,
    rng: np.random.Generator,
    start_date: date | None = None,
) -> pd.DataFrame:
    """
    Generate employees with seniority-appropriate ages.

    Distributes employees across seniority levels:
    - Level 5 (Director): ~5%
    - Level 4 (Manager/Staff): ~15%
    - Level 3 (Senior): ~25%
    - Level 2 (Mid): ~30%
    - Level 1 (Junior): ~25%
    """
    if start_date is None:
        start_date = date.today()

    band_distribution = {5: 0.05, 4: 0.15, 3: 0.25, 2: 0.30, 1: 0.25}
    band_counts = {}
    remaining = n

    # Ensure at least 1 level-5 employee for CEO
    band_counts[5] = max(1, int(n * band_distribution[5]))
    remaining -= band_counts[5]

    for band in [4, 3, 2]:
        count = int(n * band_distribution[band])
        band_counts[band] = count
        remaining -= count
    band_counts[1] = max(0, remaining)

    employees = []
    emp_idx = 0

    for band, count in sorted(band_counts.items(), reverse=True):
        for _ in range(count):
            age = get_age_for_band(band, employee_data, rng)
            gender_roll = rng.random()
            if gender_roll < employee_data["prob_neutral"]:
                gender = "na"
            elif gender_roll < employee_data["prob_neutral"] + employee_data["prob_female"]:
                gender = "female"
            else:
                gender = "male"

            first_name, last_name = get_name(gender, employee_data, rng)
            hire_date = get_hire_date(age, rng, start_date)
            birth_date = get_birth_date(age, hire_date, rng)
            emp_type = get_employment_type(employee_data, rng)
            location = get_location(employee_data, rng)

            employees.append({
                "employee_id": f"EMP{emp_idx+1:06d}",
                "first_name": first_name,
                "last_name": last_name,
                "gender": gender,
                "birth_date": birth_date,
                "hire_date": hire_date,
                "employment_type": emp_type,
                "employment_status": "Active",
                "location_id": location,
                "_seniority_level": band,
            })
            emp_idx += 1

    return pd.DataFrame(employees)

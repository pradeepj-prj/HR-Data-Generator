"""Tests for the compensation module."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hr_data_generator.assignments import generate_job_assignments
from hr_data_generator.compensation import (
    SALARY_RANGES,
    generate_base_salary,
    generate_bonus_target,
    generate_compensation_records,
)
from hr_data_generator.employee import generate_employees_with_bands
from hr_data_generator.loader import load_employee_data, load_job_data


@pytest.fixture
def employee_data():
    return load_employee_data()


@pytest.fixture
def job_data():
    return load_job_data()


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def employees(employee_data, job_data, rng):
    return generate_employees_with_bands(30, employee_data, job_data, rng)


@pytest.fixture
def job_assignments(employees, job_data, rng):
    return generate_job_assignments(employees, job_data, rng)


class TestGenerateBaseSalary:
    def test_salary_in_range_for_level_1(self, rng):
        for _ in range(50):
            salary = generate_base_salary(1, rng)
            min_sal, max_sal = SALARY_RANGES[1]
            assert min_sal <= salary <= max_sal

    def test_salary_in_range_for_level_5(self, rng):
        for _ in range(50):
            salary = generate_base_salary(5, rng)
            min_sal, max_sal = SALARY_RANGES[5]
            assert min_sal <= salary <= max_sal

    def test_higher_level_higher_salary_on_average(self, rng):
        level_1_salaries = [generate_base_salary(1, rng) for _ in range(100)]
        level_5_salaries = [generate_base_salary(5, rng) for _ in range(100)]
        assert np.mean(level_5_salaries) > np.mean(level_1_salaries)


class TestGenerateBonusTarget:
    def test_ic_bonus_target(self):
        assert generate_bonus_target("IC") == 0.10

    def test_manager_bonus_target(self):
        assert generate_bonus_target("Manager") == 0.15

    def test_director_bonus_target(self):
        assert generate_bonus_target("Director") == 0.20


class TestGenerateCompensationRecords:
    def test_returns_dataframe(self, employees, job_assignments, rng):
        result = generate_compensation_records(employees, job_assignments, rng)
        assert isinstance(result, pd.DataFrame)

    def test_all_employees_have_records(self, employees, job_assignments, rng):
        result = generate_compensation_records(employees, job_assignments, rng)
        emp_ids_in_comp = set(result["employee_id"].unique())
        emp_ids = set(employees["employee_id"].unique())
        assert emp_ids == emp_ids_in_comp

    def test_has_required_columns(self, employees, job_assignments, rng):
        result = generate_compensation_records(employees, job_assignments, rng)
        required = [
            "employee_id", "base_salary", "bonus_target_pct",
            "currency", "start_date", "end_date", "change_reason"
        ]
        for col in required:
            assert col in result.columns

    def test_first_record_is_new_hire(self, employees, job_assignments, rng):
        result = generate_compensation_records(employees, job_assignments, rng)
        for emp_id in employees["employee_id"]:
            emp_records = result[result["employee_id"] == emp_id].sort_values("start_date")
            assert emp_records.iloc[0]["change_reason"] == "New Hire"

    def test_salaries_are_positive(self, employees, job_assignments, rng):
        result = generate_compensation_records(employees, job_assignments, rng)
        assert all(result["base_salary"] > 0)

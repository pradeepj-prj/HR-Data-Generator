"""Tests for the assignments module."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hr_data_generator.assignments import (
    generate_initial_job_assignment,
    generate_initial_org_assignment,
    generate_job_assignments,
    generate_org_assignments,
    get_compatible_orgs,
    get_jobs_for_seniority,
)
from hr_data_generator.employee import generate_employees_with_bands
from hr_data_generator.loader import load_employee_data, load_job_data, load_org_data


@pytest.fixture
def employee_data():
    return load_employee_data()


@pytest.fixture
def job_data():
    return load_job_data()


@pytest.fixture
def org_data():
    return load_org_data()


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def employees(employee_data, job_data, rng):
    return generate_employees_with_bands(50, employee_data, job_data, rng)


class TestGetCompatibleOrgs:
    def test_engineering_returns_engineering_orgs(self, org_data):
        result = get_compatible_orgs("Engineering", org_data)
        assert all(result["business_unit"] == "Engineering")

    def test_sales_returns_sales_orgs(self, org_data):
        result = get_compatible_orgs("Sales", org_data)
        assert all(result["business_unit"] == "Sales")


class TestGetJobsForSeniority:
    def test_returns_matching_jobs(self, job_data):
        result = get_jobs_for_seniority(1, job_data)
        assert all(result["seniority_level"] == 1)

    def test_returns_empty_for_invalid_level(self, job_data):
        result = get_jobs_for_seniority(99, job_data)
        assert len(result) == 0


class TestGenerateInitialJobAssignment:
    def test_returns_dict_with_required_keys(self, employees, job_data, rng):
        emp = employees.iloc[0]
        result = generate_initial_job_assignment(emp, job_data, rng)
        assert "employee_id" in result
        assert "job_id" in result
        assert "job_title" in result
        assert "start_date" in result

    def test_job_matches_seniority(self, employees, job_data, rng):
        for _, emp in employees.iterrows():
            result = generate_initial_job_assignment(emp, job_data, rng)
            assert result["seniority_level"] <= emp["_seniority_level"]


class TestGenerateJobAssignments:
    def test_returns_dataframe(self, employees, job_data, rng):
        result = generate_job_assignments(employees, job_data, rng)
        assert isinstance(result, pd.DataFrame)

    def test_all_employees_have_assignments(self, employees, job_data, rng):
        result = generate_job_assignments(employees, job_data, rng)
        emp_ids_in_assignments = set(result["employee_id"].unique())
        emp_ids = set(employees["employee_id"].unique())
        assert emp_ids_in_assignments == emp_ids

    def test_has_required_columns(self, employees, job_data, rng):
        result = generate_job_assignments(employees, job_data, rng)
        required = ["employee_id", "job_id", "job_title", "start_date", "end_date"]
        for col in required:
            assert col in result.columns


class TestGenerateOrgAssignments:
    def test_returns_dataframe(self, employees, job_data, org_data, rng):
        job_assignments = generate_job_assignments(employees, job_data, rng)
        result = generate_org_assignments(employees, job_assignments, org_data, rng)
        assert isinstance(result, pd.DataFrame)

    def test_all_employees_have_assignments(self, employees, job_data, org_data, rng):
        job_assignments = generate_job_assignments(employees, job_data, rng)
        result = generate_org_assignments(employees, job_assignments, org_data, rng)
        emp_ids_in_assignments = set(result["employee_id"].unique())
        emp_ids = set(employees["employee_id"].unique())
        assert emp_ids_in_assignments == emp_ids

    def test_org_ids_are_valid(self, employees, job_data, org_data, rng):
        job_assignments = generate_job_assignments(employees, job_data, rng)
        result = generate_org_assignments(employees, job_assignments, org_data, rng)
        valid_org_ids = set(org_data["org_id"].tolist())
        for org_id in result["org_id"]:
            assert org_id in valid_org_ids

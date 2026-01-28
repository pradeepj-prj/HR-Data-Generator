"""Tests for the hierarchy module."""

import numpy as np
import pandas as pd
import pytest

from hr_data_generator.employee import generate_employees_with_bands
from hr_data_generator.hierarchy import build_manager_hierarchy, validate_hierarchy
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
def employees_with_bands(employee_data, job_data, rng):
    return generate_employees_with_bands(100, employee_data, job_data, rng)


class TestBuildManagerHierarchy:
    def test_adds_manager_id_column(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        assert "manager_id" in result.columns

    def test_exactly_one_ceo(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        ceo_count = result["manager_id"].isna().sum()
        assert ceo_count == 1

    def test_all_non_ceo_have_managers(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        non_ceo = result[result["manager_id"].notna()]
        assert len(non_ceo) == len(result) - 1

    def test_manager_ids_are_valid(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        emp_ids = set(result["employee_id"].tolist())
        for _, row in result.iterrows():
            if row["manager_id"] is not None:
                assert row["manager_id"] in emp_ids


class TestValidateHierarchy:
    def test_valid_hierarchy_no_errors(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        errors = validate_hierarchy(result)
        assert len(errors) == 0

    def test_detects_invalid_manager_id(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        result.loc[result.index[5], "manager_id"] = "INVALID_ID"
        errors = validate_hierarchy(result)
        assert len(errors) > 0
        assert any("invalid manager_id" in e for e in errors)

    def test_detects_self_reporting(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        emp_id = result.loc[result.index[5], "employee_id"]
        result.loc[result.index[5], "manager_id"] = emp_id
        errors = validate_hierarchy(result)
        assert len(errors) > 0
        assert any("reports to themselves" in e for e in errors)

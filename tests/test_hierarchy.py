"""Tests for the hierarchy module."""

import numpy as np
import pandas as pd
import pytest

from hr_data_generator.employee import generate_employees_with_bands
from hr_data_generator.hierarchy import (
    build_manager_hierarchy,
    validate_hierarchy,
    validate_manager_bu_alignment,
)
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


class TestValidateManagerBUAlignment:
    def test_valid_hierarchy_no_bu_errors(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        errors = validate_manager_bu_alignment(result)
        assert len(errors) == 0

    def test_detects_cross_bu_reporting(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        # Find a level-2 employee and change their BU to something different from manager
        level_2 = result[result["_seniority_level"] == 2]
        if len(level_2) > 0:
            emp_idx = level_2.index[0]
            manager_id = result.loc[emp_idx, "manager_id"]
            manager_bu = result.loc[result["employee_id"] == manager_id, "_business_unit"].iloc[0]
            # Set employee to different BU
            new_bu = "Sales" if manager_bu != "Sales" else "Engineering"
            result.loc[emp_idx, "_business_unit"] = new_bu
            errors = validate_manager_bu_alignment(result)
            assert len(errors) > 0
            assert any("cross-BU reporting" in e for e in errors)

    def test_allows_bu_heads_to_report_to_ceo(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        # Level-5 employees (except CEO) should report to CEO without BU errors
        ceo_mask = result["manager_id"].isna()
        ceo_id = result.loc[ceo_mask, "employee_id"].iloc[0]
        level_5_non_ceo = result[(result["_seniority_level"] == 5) & (result["employee_id"] != ceo_id)]
        # Verify they report to CEO
        for _, row in level_5_non_ceo.iterrows():
            assert row["manager_id"] == ceo_id
        # No BU alignment errors for this
        errors = validate_manager_bu_alignment(result)
        assert len(errors) == 0


class TestBuildManagerHierarchyBUAlignment:
    def test_managers_in_same_bu_as_reports(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        emp_to_bu = dict(zip(result["employee_id"], result["_business_unit"]))
        ceo_id = result.loc[result["manager_id"].isna(), "employee_id"].iloc[0]

        # Check all employees (except CEO)
        for _, row in result.iterrows():
            if row["manager_id"] is None:
                continue  # CEO
            # Anyone reporting directly to CEO is allowed (CEO is company-wide)
            if row["manager_id"] == ceo_id:
                continue
            # For non-CEO managers, must be same BU
            manager_bu = emp_to_bu.get(row["manager_id"])
            assert row["_business_unit"] == manager_bu, (
                f"Employee {row['employee_id']} ({row['_business_unit']}) "
                f"reports to manager in different BU ({manager_bu})"
            )

    def test_each_bu_has_leadership(self, employees_with_bands, job_data, org_data, rng):
        result = build_manager_hierarchy(employees_with_bands, job_data, org_data, rng)
        # Get all BUs that have employees
        bus_with_employees = result["_business_unit"].unique()
        # Get leadership (level 4+) per BU
        leadership = result[result["_seniority_level"] >= 4]
        for bu in bus_with_employees:
            bu_leadership = leadership[leadership["_business_unit"] == bu]
            # Each BU should have at least one leader (or use CEO as fallback)
            ceo_bu = result.loc[result["manager_id"].isna(), "_business_unit"].iloc[0]
            if bu != ceo_bu:
                assert len(bu_leadership) >= 1 or bu == ceo_bu

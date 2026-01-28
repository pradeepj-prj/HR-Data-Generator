"""Integration tests for the complete HR data generation pipeline."""

from datetime import date

import pandas as pd
import pytest

from hr_data_generator import HRDataGenerator, generate_hr_data


class TestGenerateHrData:
    """Tests for the main generate_hr_data function."""

    def test_returns_dict_of_dataframes(self):
        result = generate_hr_data(n_employees=20, seed=42)
        assert isinstance(result, dict)
        for key, value in result.items():
            assert isinstance(value, pd.DataFrame), f"{key} is not a DataFrame"

    def test_contains_all_expected_tables(self):
        result = generate_hr_data(n_employees=20, seed=42)
        expected_tables = [
            "employee",
            "employee_job_assignment",
            "employee_org_assignment",
            "employee_compensation",
            "employee_performance",
            "organization_unit",
            "job_role",
            "location",
        ]
        for table in expected_tables:
            assert table in result, f"Missing table: {table}"

    def test_correct_employee_count(self):
        n = 50
        result = generate_hr_data(n_employees=n, seed=42)
        assert len(result["employee"]) == n

    def test_seed_produces_reproducible_results(self):
        result1 = generate_hr_data(n_employees=30, seed=123)
        result2 = generate_hr_data(n_employees=30, seed=123)

        pd.testing.assert_frame_equal(result1["employee"], result2["employee"])
        pd.testing.assert_frame_equal(
            result1["employee_job_assignment"],
            result2["employee_job_assignment"]
        )

    def test_different_seeds_produce_different_results(self):
        result1 = generate_hr_data(n_employees=30, seed=1)
        result2 = generate_hr_data(n_employees=30, seed=2)

        assert not result1["employee"]["first_name"].equals(result2["employee"]["first_name"])


class TestReferentialIntegrity:
    """Tests for referential integrity across tables."""

    @pytest.fixture
    def data(self):
        return generate_hr_data(n_employees=100, seed=42)

    def test_all_manager_ids_exist_in_employees(self, data):
        """All manager_ids should reference valid employee_ids."""
        employees = data["employee"]
        valid_emp_ids = set(employees["employee_id"].tolist())

        for manager_id in employees["manager_id"].dropna():
            assert manager_id in valid_emp_ids, f"Invalid manager_id: {manager_id}"

    def test_job_assignment_employee_ids_exist(self, data):
        """All employee_ids in job_assignment should exist in employee table."""
        employees = data["employee"]
        job_assignments = data["employee_job_assignment"]
        valid_emp_ids = set(employees["employee_id"].tolist())

        for emp_id in job_assignments["employee_id"]:
            assert emp_id in valid_emp_ids

    def test_job_assignment_job_ids_exist(self, data):
        """All job_ids in job_assignment should exist in job_role table."""
        job_assignments = data["employee_job_assignment"]
        job_roles = data["job_role"]
        valid_job_ids = set(job_roles["job_id"].tolist())

        for job_id in job_assignments["job_id"]:
            assert job_id in valid_job_ids

    def test_org_assignment_employee_ids_exist(self, data):
        """All employee_ids in org_assignment should exist in employee table."""
        employees = data["employee"]
        org_assignments = data["employee_org_assignment"]
        valid_emp_ids = set(employees["employee_id"].tolist())

        for emp_id in org_assignments["employee_id"]:
            assert emp_id in valid_emp_ids

    def test_org_assignment_org_ids_exist(self, data):
        """All org_ids in org_assignment should exist in organization_unit table."""
        org_assignments = data["employee_org_assignment"]
        org_units = data["organization_unit"]
        valid_org_ids = set(org_units["org_id"].tolist())

        for org_id in org_assignments["org_id"]:
            assert org_id in valid_org_ids

    def test_compensation_employee_ids_exist(self, data):
        """All employee_ids in compensation should exist in employee table."""
        employees = data["employee"]
        compensation = data["employee_compensation"]
        valid_emp_ids = set(employees["employee_id"].tolist())

        for emp_id in compensation["employee_id"]:
            assert emp_id in valid_emp_ids

    def test_performance_employee_ids_exist(self, data):
        """All employee_ids in performance should exist in employee table."""
        employees = data["employee"]
        performance = data["employee_performance"]
        valid_emp_ids = set(employees["employee_id"].tolist())

        for emp_id in performance["employee_id"]:
            assert emp_id in valid_emp_ids


class TestTimeVariantRecords:
    """Tests for time-variant record validity."""

    @pytest.fixture
    def data(self):
        return generate_hr_data(n_employees=50, seed=42)

    def test_job_assignment_start_date_before_end_date(self, data):
        """start_date should always be before or equal to end_date."""
        job_assignments = data["employee_job_assignment"]
        for _, row in job_assignments.iterrows():
            if row["end_date"] is not None and pd.notna(row["end_date"]):
                assert row["start_date"] <= row["end_date"]

    def test_org_assignment_start_date_before_end_date(self, data):
        """start_date should always be before or equal to end_date."""
        org_assignments = data["employee_org_assignment"]
        for _, row in org_assignments.iterrows():
            if row["end_date"] is not None and pd.notna(row["end_date"]):
                assert row["start_date"] <= row["end_date"]

    def test_compensation_start_date_before_end_date(self, data):
        """start_date should always be before or equal to end_date."""
        compensation = data["employee_compensation"]
        for _, row in compensation.iterrows():
            if row["end_date"] is not None and pd.notna(row["end_date"]):
                assert row["start_date"] <= row["end_date"]

    def test_all_employees_have_job_assignment(self, data):
        """Every employee should have at least one job assignment."""
        employees = data["employee"]
        job_assignments = data["employee_job_assignment"]

        for emp_id in employees["employee_id"]:
            emp_jobs = job_assignments[job_assignments["employee_id"] == emp_id]
            assert len(emp_jobs) >= 1, f"Employee {emp_id} has no job assignments"

    def test_all_employees_have_org_assignment(self, data):
        """Every employee should have at least one org assignment."""
        employees = data["employee"]
        org_assignments = data["employee_org_assignment"]

        for emp_id in employees["employee_id"]:
            emp_orgs = org_assignments[org_assignments["employee_id"] == emp_id]
            assert len(emp_orgs) >= 1, f"Employee {emp_id} has no org assignments"


class TestHRDataGenerator:
    """Tests for the HRDataGenerator class."""

    def test_can_instantiate_with_seed(self):
        generator = HRDataGenerator(seed=42)
        assert generator is not None

    def test_generate_returns_data(self):
        generator = HRDataGenerator(seed=42)
        result = generator.generate(n_employees=10)
        assert isinstance(result, dict)
        assert len(result["employee"]) == 10

    def test_can_exclude_performance(self):
        generator = HRDataGenerator(seed=42)
        result = generator.generate(n_employees=10, include_performance=False)
        assert "employee_performance" not in result

    def test_can_exclude_compensation(self):
        generator = HRDataGenerator(seed=42)
        result = generator.generate(n_employees=10, include_compensation=False)
        assert "employee_compensation" not in result

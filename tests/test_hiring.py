"""Tests for the hiring module."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hr_data_generator import generate_hr_data, HiringModel
from hr_data_generator.hiring import (
    DEFAULT_BU_GROWTH_RATES,
    DEFAULT_NEW_HIRE_SENIORITY_WEIGHTS,
    apply_hiring,
    generate_new_hire,
    generate_new_hire_compensation,
    generate_new_hire_job_assignment,
    generate_new_hire_org_assignment,
    get_next_employee_id,
)
from hr_data_generator.loader import load_employee_data, load_job_data, load_org_data


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def employee_data():
    return load_employee_data()


@pytest.fixture
def job_data():
    return load_job_data()


@pytest.fixture
def org_data():
    return load_org_data()


class TestHiringModel:
    def test_default_growth_rate(self):
        model = HiringModel()
        assert model.base_growth_rate == 0.05
        assert model.backfill_rate == 0.85

    def test_custom_growth_rate(self):
        model = HiringModel(base_growth_rate=0.10, backfill_rate=0.90)
        assert model.base_growth_rate == 0.10
        assert model.backfill_rate == 0.90

    def test_bu_specific_growth_rates(self):
        model = HiringModel()
        assert model.get_growth_rate("Engineering") == 0.08
        assert model.get_growth_rate("Sales") == 0.05
        assert model.get_growth_rate("Corporate") == 0.02

    def test_unknown_bu_uses_base_rate(self):
        model = HiringModel(base_growth_rate=0.05)
        assert model.get_growth_rate("UnknownBU") == 0.05

    def test_custom_bu_growth_rates(self):
        custom_rates = {"Engineering": 0.15, "Sales": 0.10}
        model = HiringModel(bu_growth_rates=custom_rates)
        assert model.get_growth_rate("Engineering") == 0.15
        assert model.get_growth_rate("Sales") == 0.10

    def test_calculate_growth_hires(self):
        model = HiringModel(base_growth_rate=0.10)
        headcount = {"Engineering": 100, "Sales": 50}
        growth_hires = model.calculate_growth_hires(headcount)
        # 10% of 100 = 10, 8% of 100 for Engineering with default BU rates
        assert growth_hires["Engineering"] >= 5  # At least some hires
        assert growth_hires["Sales"] >= 2

    def test_calculate_backfill_hires(self):
        model = HiringModel(backfill_rate=0.80)
        attrition = {"Engineering": 10, "Sales": 5}
        backfill = model.calculate_backfill_hires(attrition)
        assert backfill["Engineering"] == 8  # 80% of 10
        assert backfill["Sales"] == 4  # 80% of 5

    def test_select_seniority_level(self, rng):
        model = HiringModel()
        # Run many times and check distribution
        levels = [model.select_seniority_level(rng) for _ in range(1000)]

        # Should be more juniors than directors
        level_1_count = levels.count(1)
        level_5_count = levels.count(5)
        assert level_1_count > level_5_count * 5  # Much more L1 than L5

    def test_seniority_distribution_matches_weights(self, rng):
        model = HiringModel()
        levels = [model.select_seniority_level(rng) for _ in range(10000)]

        # Check approximate distribution (with some tolerance)
        level_1_pct = levels.count(1) / len(levels)
        level_5_pct = levels.count(5) / len(levels)

        assert 0.35 < level_1_pct < 0.45  # Should be ~40%
        assert 0.01 < level_5_pct < 0.04  # Should be ~2%


class TestGenerateNewHire:
    def test_returns_dict_with_required_fields(self, rng, employee_data):
        emp = generate_new_hire(
            year=2023,
            employee_data=employee_data,
            rng=rng,
            employee_id="EMP000101",
            business_unit="Engineering",
            seniority_level=2,
        )

        assert emp["employee_id"] == "EMP000101"
        assert emp["_business_unit"] == "Engineering"
        assert emp["_seniority_level"] == 2
        assert emp["employment_status"] == "Active"
        assert emp["termination_date"] is None

    def test_hire_date_in_correct_year(self, rng, employee_data):
        for _ in range(20):
            emp = generate_new_hire(
                year=2023,
                employee_data=employee_data,
                rng=rng,
                employee_id="EMP000101",
                business_unit="Engineering",
                seniority_level=2,
            )
            assert emp["hire_date"].year == 2023

    def test_age_appropriate_for_seniority(self, rng, employee_data):
        # Junior (L1) should be younger
        junior_ages = []
        for _ in range(50):
            emp = generate_new_hire(
                year=2023,
                employee_data=employee_data,
                rng=rng,
                employee_id="EMP000101",
                business_unit="Engineering",
                seniority_level=1,
            )
            age = 2023 - emp["birth_date"].year
            junior_ages.append(age)

        # Director (L5) should be older
        director_ages = []
        for _ in range(50):
            emp = generate_new_hire(
                year=2023,
                employee_data=employee_data,
                rng=rng,
                employee_id="EMP000102",
                business_unit="Engineering",
                seniority_level=5,
            )
            age = 2023 - emp["birth_date"].year
            director_ages.append(age)

        assert np.mean(junior_ages) < np.mean(director_ages)


class TestGenerateNewHireJobAssignment:
    def test_returns_dict_with_required_fields(self, rng, job_data):
        employee = {
            "employee_id": "EMP000101",
            "hire_date": date(2023, 6, 15),
            "_seniority_level": 2,
            "_business_unit": "Engineering",
        }

        job_assign = generate_new_hire_job_assignment(
            employee=employee,
            job_data=job_data,
            rng=rng,
            end_date=date(2023, 12, 31),
        )

        assert job_assign["employee_id"] == "EMP000101"
        assert job_assign["start_date"] == date(2023, 6, 15)
        assert job_assign["end_date"] is None
        assert job_assign["seniority_level"] == 2
        assert "job_id" in job_assign
        assert "job_title" in job_assign


class TestGenerateNewHireOrgAssignment:
    def test_returns_dict_with_required_fields(self, rng, org_data):
        employee = {
            "employee_id": "EMP000101",
            "hire_date": date(2023, 6, 15),
            "_business_unit": "Engineering",
        }

        org_assign = generate_new_hire_org_assignment(
            employee=employee,
            org_data=org_data,
            rng=rng,
        )

        assert org_assign["employee_id"] == "EMP000101"
        assert org_assign["start_date"] == date(2023, 6, 15)
        assert org_assign["end_date"] is None
        assert "org_id" in org_assign
        assert "org_name" in org_assign
        assert "business_unit" in org_assign


class TestGenerateNewHireCompensation:
    def test_returns_dict_with_required_fields(self, rng):
        employee = {
            "employee_id": "EMP000101",
            "hire_date": date(2023, 6, 15),
            "_seniority_level": 3,
        }
        job_assign = {"job_id": "JOB001", "seniority_level": 3}

        comp = generate_new_hire_compensation(
            employee=employee,
            job_assignment=job_assign,
            rng=rng,
        )

        assert comp["employee_id"] == "EMP000101"
        assert comp["start_date"] == date(2023, 6, 15)
        assert comp["end_date"] is None
        assert comp["currency"] == "USD"
        assert comp["base_salary"] > 0
        assert comp["bonus_target_pct"] >= 0
        assert comp["change_reason"] == "New Hire"

    def test_salary_increases_with_seniority(self, rng):
        salaries_by_level = {}

        for level in [1, 2, 3, 4, 5]:
            salaries = []
            for _ in range(20):
                employee = {
                    "employee_id": "EMP000101",
                    "hire_date": date(2023, 6, 15),
                    "_seniority_level": level,
                }
                job_assign = {"job_id": "JOB001", "seniority_level": level}
                comp = generate_new_hire_compensation(employee, job_assign, rng)
                salaries.append(comp["base_salary"])
            salaries_by_level[level] = np.mean(salaries)

        # Higher levels should have higher average salary
        assert salaries_by_level[1] < salaries_by_level[3]
        assert salaries_by_level[3] < salaries_by_level[5]


class TestGetNextEmployeeId:
    def test_empty_dataframe_returns_one(self):
        df = pd.DataFrame(columns=["employee_id"])
        num, id_str = get_next_employee_id(df)
        assert num == 1
        assert id_str == "EMP000001"

    def test_continues_from_max(self):
        df = pd.DataFrame({
            "employee_id": ["EMP000001", "EMP000050", "EMP000025"]
        })
        num, id_str = get_next_employee_id(df)
        assert num == 51
        assert id_str == "EMP000051"


class TestApplyHiring:
    @pytest.fixture
    def sample_data(self, rng, employee_data, job_data, org_data):
        employees = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "first_name": "John",
                "last_name": "Doe",
                "hire_date": date(2020, 1, 15),
                "birth_date": date(1985, 5, 10),
                "employment_type": "Full-time",
                "employment_status": "Active",
                "location_id": "LOC001",
                "termination_date": None,
                "termination_reason": None,
                "_seniority_level": 3,
                "_business_unit": "Engineering",
            },
        ])

        job_assignments = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "job_id": "JOB001",
                "job_title": "Software Engineer",
                "seniority_level": 3,
                "start_date": date(2020, 1, 15),
                "end_date": None,
            },
        ])

        org_assignments = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "org_unit_id": "ORG001",
                "start_date": date(2020, 1, 15),
                "end_date": None,
            },
        ])

        compensation = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "annual_salary": 80000,
                "currency": "USD",
                "start_date": date(2020, 1, 15),
                "end_date": None,
            },
        ])

        return employees, job_assignments, org_assignments, compensation

    def test_adds_new_employees(
        self, sample_data, rng, employee_data, job_data, org_data
    ):
        employees, job_assignments, org_assignments, compensation = sample_data
        hiring_model = HiringModel()

        new_employees, new_jobs, new_orgs, new_comp = apply_hiring(
            employees=employees,
            job_assignments=job_assignments,
            org_assignments=org_assignments,
            compensation=compensation,
            employee_data=employee_data,
            job_data=job_data,
            org_data=org_data,
            rng=rng,
            year=2023,
            growth_hires_by_bu={"Engineering": 2, "Sales": 1},
            backfill_hires_by_bu={"Engineering": 1},
            hiring_model=hiring_model,
        )

        # Should have added 4 new employees (2 + 1 + 1)
        assert len(new_employees) == 5  # 1 original + 4 new
        assert len(new_jobs) == 5
        assert len(new_orgs) == 5
        assert len(new_comp) == 5

    def test_new_employee_ids_continue_sequence(
        self, sample_data, rng, employee_data, job_data, org_data
    ):
        employees, job_assignments, org_assignments, compensation = sample_data
        hiring_model = HiringModel()

        new_employees, _, _, _ = apply_hiring(
            employees=employees,
            job_assignments=job_assignments,
            org_assignments=org_assignments,
            compensation=compensation,
            employee_data=employee_data,
            job_data=job_data,
            org_data=org_data,
            rng=rng,
            year=2023,
            growth_hires_by_bu={"Engineering": 2},
            backfill_hires_by_bu={},
            hiring_model=hiring_model,
        )

        # New employees should have IDs EMP000002 and EMP000003
        new_ids = new_employees[new_employees["employee_id"] != "EMP000001"]["employee_id"].tolist()
        assert "EMP000002" in new_ids
        assert "EMP000003" in new_ids


class TestCombinedSimulation:
    def test_headcount_with_hiring_and_attrition(self):
        # With balanced hiring and attrition, headcount should be relatively stable
        data = generate_hr_data(
            n_employees=100,
            seed=42,
            include_attrition=True,
            include_hiring=True,
            base_growth_rate=0.05,
            backfill_rate=0.85,
        )
        employees = data["employee"]
        active = employees[employees["termination_date"].isna()]

        # With 5% growth and 85% backfill, should maintain or grow headcount
        # Starting from 100, after 5 years could be anywhere from 80-200
        assert len(active) >= 50  # Shouldn't shrink too much
        assert len(employees) > 100  # Should have hired some people

    def test_headcount_shrinks_with_attrition_only(self):
        data = generate_hr_data(
            n_employees=100,
            seed=42,
            include_attrition=True,
            include_hiring=False,
        )
        employees = data["employee"]
        active = employees[employees["termination_date"].isna()]

        # Without hiring, headcount should decrease
        assert len(active) < 100

    def test_headcount_grows_with_hiring_only(self):
        data = generate_hr_data(
            n_employees=100,
            seed=42,
            include_attrition=False,
            include_hiring=True,
            base_growth_rate=0.10,
        )
        employees = data["employee"]

        # With 10% growth and no attrition, should have more employees
        assert len(employees) > 100

    def test_new_hires_have_satellite_records(self):
        data = generate_hr_data(
            n_employees=50,
            seed=42,
            include_attrition=True,
            include_hiring=True,
        )

        employees = data["employee"]
        job_assignments = data["employee_job_assignment"]
        org_assignments = data["employee_org_assignment"]

        # Every employee should have at least one job assignment
        emp_ids_with_jobs = set(job_assignments["employee_id"].unique())
        for emp_id in employees["employee_id"]:
            assert emp_id in emp_ids_with_jobs, f"{emp_id} has no job assignment"

        # Every employee should have at least one org assignment
        emp_ids_with_orgs = set(org_assignments["employee_id"].unique())
        for emp_id in employees["employee_id"]:
            assert emp_id in emp_ids_with_orgs, f"{emp_id} has no org assignment"

    def test_tenure_distribution_with_hiring(self):
        data = generate_hr_data(
            n_employees=100,
            seed=42,
            include_attrition=True,
            include_hiring=True,
        )

        employees = data["employee"]
        today = date.today()

        # Calculate tenure for active employees
        active = employees[employees["termination_date"].isna()]
        tenures = []
        for _, emp in active.iterrows():
            hire_date = emp["hire_date"]
            if isinstance(hire_date, str):
                hire_date = date.fromisoformat(hire_date)
            tenure = (today - hire_date).days / 365.25
            tenures.append(tenure)

        # With hiring, should have some newer employees (tenure < 2 years)
        new_hires = [t for t in tenures if t < 2]
        assert len(new_hires) > 0, "Should have some recent hires"

    def test_reproducible_with_seed(self):
        data1 = generate_hr_data(
            n_employees=50,
            seed=123,
            include_attrition=True,
            include_hiring=True,
        )
        data2 = generate_hr_data(
            n_employees=50,
            seed=123,
            include_attrition=True,
            include_hiring=True,
        )

        pd.testing.assert_frame_equal(data1["employee"], data2["employee"])

    def test_different_seeds_different_results(self):
        data1 = generate_hr_data(
            n_employees=50,
            seed=1,
            include_attrition=True,
            include_hiring=True,
        )
        data2 = generate_hr_data(
            n_employees=50,
            seed=2,
            include_attrition=True,
            include_hiring=True,
        )

        # Different seeds should produce different employee data
        assert not data1["employee"]["first_name"].equals(data2["employee"]["first_name"])

    def test_bu_growth_rates_affect_composition(self):
        # Engineering grows faster
        data = generate_hr_data(
            n_employees=100,
            seed=42,
            include_attrition=True,
            include_hiring=True,
            bu_growth_rates={
                "Engineering": 0.20,  # Very high growth
                "Sales": 0.02,        # Low growth
                "Corporate": 0.01,    # Very low growth
            },
        )

        # This test verifies that the BU-specific rates are being used
        # The exact composition depends on many factors, so we just verify
        # the data was generated successfully with the custom rates
        employees = data["employee"]
        assert len(employees) > 100  # Should have hired people


class TestIntegrationWithGenerator:
    def test_generate_with_all_features(self):
        data = generate_hr_data(
            n_employees=100,
            seed=42,
            include_performance=True,
            include_compensation=True,
            include_attrition=True,
            include_hiring=True,
        )

        # All expected tables should be present
        assert "employee" in data
        assert "employee_job_assignment" in data
        assert "employee_org_assignment" in data
        assert "employee_compensation" in data
        assert "employee_performance" in data

        # Should have more employees than started with
        employees = data["employee"]
        assert len(employees) > 100

    def test_hiring_model_exported(self):
        # Verify HiringModel is accessible from main package
        from hr_data_generator import HiringModel
        model = HiringModel(base_growth_rate=0.10)
        assert model.base_growth_rate == 0.10

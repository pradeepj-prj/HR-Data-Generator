"""Tests for the attrition module."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hr_data_generator import generate_hr_data
from hr_data_generator.attrition import (
    AttritionModel,
    FormulaStrategy,
    LookupStrategy,
    RangeLookupStrategy,
    apply_attrition,
    close_records_at_termination,
    filter_reviews_by_termination,
    get_termination_date,
    select_termination_reason,
)


@pytest.fixture
def rng():
    return np.random.default_rng(42)


class TestLookupStrategy:
    def test_returns_mapped_value(self):
        strategy = LookupStrategy({1: 2.0, 2: 1.5, 3: 1.0})
        assert strategy.get_factor(1) == 2.0
        assert strategy.get_factor(2) == 1.5
        assert strategy.get_factor(3) == 1.0

    def test_returns_default_for_missing(self):
        strategy = LookupStrategy({1: 2.0}, default=0.5)
        assert strategy.get_factor(99) == 0.5

    def test_default_is_one(self):
        strategy = LookupStrategy({1: 2.0})
        assert strategy.get_factor(99) == 1.0


class TestRangeLookupStrategy:
    def test_returns_factor_for_range(self):
        strategy = RangeLookupStrategy([
            (0, 1, 1.8),
            (1, 5, 1.0),
            (5, 10, 0.7),
        ])
        assert strategy.get_factor(0.5) == 1.8
        assert strategy.get_factor(1) == 1.0
        assert strategy.get_factor(3) == 1.0
        assert strategy.get_factor(7) == 0.7

    def test_returns_default_for_out_of_range(self):
        strategy = RangeLookupStrategy([
            (0, 5, 1.0),
        ], default=0.5)
        assert strategy.get_factor(10) == 0.5


class TestFormulaStrategy:
    def test_applies_function(self):
        strategy = FormulaStrategy(lambda x: x * 2)
        assert strategy.get_factor(3) == 6

    def test_complex_formula(self):
        # U-shaped curve example
        strategy = FormulaStrategy(lambda r: 1.0 + 0.3 * (r - 3) ** 2)
        assert strategy.get_factor(1) == pytest.approx(2.2)
        assert strategy.get_factor(3) == pytest.approx(1.0)
        assert strategy.get_factor(5) == pytest.approx(2.2)


class TestAttritionModel:
    def test_base_probability_calculation(self):
        model = AttritionModel(base_annual_rate=0.12)
        prob = model.calculate_base_probability(
            performance_rating=3,
            tenure_years=3,
            employment_type="Full-time",
            seniority_level=3,
            had_recent_promotion=False,
        )
        # With all baseline values, should be close to base rate
        # 0.12 * 1.0 * 1.0 * 1.0 * 0.9 * 1.0 = 0.108
        assert 0.05 < prob < 0.20

    def test_low_performer_high_probability(self):
        model = AttritionModel(base_annual_rate=0.12)
        low_perf_prob = model.calculate_base_probability(
            performance_rating=1,
            tenure_years=0.5,
            employment_type="Contract",
            seniority_level=1,
            had_recent_promotion=False,
        )
        high_perf_prob = model.calculate_base_probability(
            performance_rating=5,
            tenure_years=10,
            employment_type="Full-time",
            seniority_level=5,
            had_recent_promotion=True,
        )
        assert low_perf_prob > high_perf_prob * 5

    def test_probability_bounded_zero_one(self, rng):
        model = AttritionModel(base_annual_rate=0.5, noise_std=0.5)
        for _ in range(100):
            base_prob = model.calculate_base_probability(
                performance_rating=1,
                tenure_years=0.5,
                employment_type="Contract",
                seniority_level=1,
                had_recent_promotion=False,
            )
            final_prob = model.calculate_probability_with_noise(base_prob, rng)
            assert 0 <= final_prob <= 1

    def test_will_leave_returns_bool(self, rng):
        model = AttritionModel()
        result = model.will_leave_this_year(
            performance_rating=3,
            tenure_years=2,
            employment_type="Full-time",
            seniority_level=3,
            had_recent_promotion=False,
            rng=rng,
        )
        assert isinstance(result, bool)


class TestSelectTerminationReason:
    def test_returns_tuple(self, rng):
        reason, category = select_termination_reason(35, 3, rng)
        assert isinstance(reason, str)
        assert category in ["Voluntary", "Involuntary"]

    def test_low_performer_more_involuntary(self, rng):
        involuntary_count = 0
        for _ in range(100):
            rng_iter = np.random.default_rng(rng.integers(0, 10000))
            _, category = select_termination_reason(35, 1, rng_iter)
            if category == "Involuntary":
                involuntary_count += 1
        # Low performers should have mostly involuntary terminations
        assert involuntary_count > 40

    def test_high_performer_mostly_voluntary(self, rng):
        voluntary_count = 0
        for _ in range(100):
            rng_iter = np.random.default_rng(rng.integers(0, 10000))
            _, category = select_termination_reason(35, 5, rng_iter)
            if category == "Voluntary":
                voluntary_count += 1
        # High performers should have mostly voluntary terminations
        assert voluntary_count > 80

    def test_old_employee_can_retire(self, rng):
        retirement_count = 0
        for _ in range(100):
            rng_iter = np.random.default_rng(rng.integers(0, 10000))
            reason, _ = select_termination_reason(62, 4, rng_iter)
            if "Retirement" in reason:
                retirement_count += 1
        # 62-year-olds should have significant retirement rate
        assert retirement_count > 20

    def test_young_employee_no_retirement(self, rng):
        for _ in range(50):
            rng_iter = np.random.default_rng(rng.integers(0, 10000))
            reason, _ = select_termination_reason(30, 4, rng_iter)
            assert "Retirement" not in reason


class TestGetTerminationDate:
    def test_returns_date(self, rng):
        result = get_termination_date(2023, date(2020, 1, 1), rng)
        assert isinstance(result, date)

    def test_date_in_correct_year(self, rng):
        for _ in range(10):
            result = get_termination_date(2023, date(2020, 1, 1), rng)
            assert result.year == 2023

    def test_date_after_hire(self, rng):
        hire_date = date(2023, 6, 1)
        for _ in range(10):
            result = get_termination_date(2023, hire_date, rng)
            assert result >= hire_date


class TestApplyAttrition:
    @pytest.fixture
    def sample_data(self, rng):
        employees = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "hire_date": date(2020, 1, 15),
                "birth_date": date(1985, 5, 10),
                "employment_type": "Full-time",
                "employment_status": "Active",
            },
            {
                "employee_id": "EMP000002",
                "hire_date": date(2021, 6, 1),
                "birth_date": date(1990, 8, 20),
                "employment_type": "Contract",
                "employment_status": "Active",
            },
        ])

        job_assignments = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "job_id": "JOB001",
                "seniority_level": 3,
                "start_date": date(2020, 1, 15),
                "end_date": None,
            },
            {
                "employee_id": "EMP000002",
                "job_id": "JOB002",
                "seniority_level": 2,
                "start_date": date(2021, 6, 1),
                "end_date": None,
            },
        ])

        performance = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "review_period_year": 2020,
                "review_date": date(2020, 12, 15),
                "rating": 3,
            },
            {
                "employee_id": "EMP000001",
                "review_period_year": 2021,
                "review_date": date(2021, 12, 15),
                "rating": 4,
            },
        ])

        return employees, job_assignments, performance

    def test_returns_dataframe(self, sample_data, rng):
        employees, job_assignments, performance = sample_data
        result = apply_attrition(
            employees, performance, job_assignments, rng,
            start_year=2021, end_year=2023,
        )
        assert isinstance(result, pd.DataFrame)

    def test_adds_termination_columns(self, sample_data, rng):
        employees, job_assignments, performance = sample_data
        result = apply_attrition(
            employees, performance, job_assignments, rng,
            start_year=2021, end_year=2023,
        )
        assert "termination_date" in result.columns
        assert "termination_reason" in result.columns

    def test_some_employees_terminate_over_time(self, rng):
        # Generate larger dataset to ensure some attrition
        data = generate_hr_data(n_employees=100, seed=42, include_attrition=True)
        employees = data["employee"]
        terminated = employees[employees["termination_date"].notna()]
        # With 5 years at 12% rate, expect 30-60% attrition
        assert len(terminated) > 10
        assert len(terminated) < 80

    def test_high_attrition_rate_more_terminations(self, rng):
        data_low = generate_hr_data(
            n_employees=100, seed=42,
            include_attrition=True, attrition_rate=0.05
        )
        data_high = generate_hr_data(
            n_employees=100, seed=42,
            include_attrition=True, attrition_rate=0.25
        )
        low_terminated = len(data_low["employee"][data_low["employee"]["termination_date"].notna()])
        high_terminated = len(data_high["employee"][data_high["employee"]["termination_date"].notna()])
        assert high_terminated > low_terminated


class TestCloseRecordsAtTermination:
    def test_closes_records_at_termination(self):
        employees = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "termination_date": date(2023, 6, 15),
            },
        ])

        records = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "start_date": date(2020, 1, 1),
                "end_date": None,
            },
        ])

        result = close_records_at_termination(records, employees)
        assert result.iloc[0]["end_date"] == date(2023, 6, 15)

    def test_preserves_earlier_end_dates(self):
        employees = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "termination_date": date(2023, 6, 15),
            },
        ])

        records = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "start_date": date(2020, 1, 1),
                "end_date": date(2022, 12, 31),
            },
        ])

        result = close_records_at_termination(records, employees)
        assert result.iloc[0]["end_date"] == date(2022, 12, 31)

    def test_ignores_non_terminated_employees(self):
        employees = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "termination_date": None,
            },
        ])

        records = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "start_date": date(2020, 1, 1),
                "end_date": None,
            },
        ])

        result = close_records_at_termination(records, employees)
        assert result.iloc[0]["end_date"] is None


class TestFilterReviewsByTermination:
    def test_removes_reviews_after_termination(self):
        employees = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "termination_date": date(2022, 6, 15),
            },
        ])

        reviews = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "review_date": date(2021, 12, 15),
            },
            {
                "employee_id": "EMP000001",
                "review_date": date(2022, 12, 15),  # After termination
            },
        ])

        result = filter_reviews_by_termination(reviews, employees)
        assert len(result) == 1
        assert result.iloc[0]["review_date"] == date(2021, 12, 15)

    def test_keeps_reviews_for_active_employees(self):
        employees = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "termination_date": None,
            },
        ])

        reviews = pd.DataFrame([
            {
                "employee_id": "EMP000001",
                "review_date": date(2021, 12, 15),
            },
            {
                "employee_id": "EMP000001",
                "review_date": date(2022, 12, 15),
            },
        ])

        result = filter_reviews_by_termination(reviews, employees)
        assert len(result) == 2


class TestIntegrationWithGenerator:
    def test_generate_with_attrition(self):
        data = generate_hr_data(n_employees=50, seed=42, include_attrition=True)
        employees = data["employee"]

        # Should have termination columns
        assert "termination_date" in employees.columns
        assert "termination_reason" in employees.columns

        # Should have some terminated employees
        terminated = employees[employees["termination_date"].notna()]
        assert len(terminated) > 0

        # Terminated employees should have valid status
        for _, emp in terminated.iterrows():
            assert emp["employment_status"] in ["Terminated", "Retired"]

    def test_generate_without_attrition(self):
        data = generate_hr_data(n_employees=50, seed=42, include_attrition=False)
        employees = data["employee"]

        # All employees should be active
        assert (employees["employment_status"] == "Active").all()

        # No termination dates
        assert employees["termination_date"].isna().all()

    def test_job_records_closed_at_termination(self):
        data = generate_hr_data(n_employees=100, seed=42, include_attrition=True)
        employees = data["employee"]
        job_assignments = data["employee_job_assignment"]

        terminated = employees[employees["termination_date"].notna()]

        for _, emp in terminated.head(10).iterrows():
            term_date = emp["termination_date"]
            emp_jobs = job_assignments[job_assignments["employee_id"] == emp["employee_id"]]

            # All job records should have end_date <= termination_date
            for _, job in emp_jobs.iterrows():
                if job["end_date"] is not None and pd.notna(job["end_date"]):
                    assert job["end_date"] <= term_date

    def test_no_performance_reviews_after_termination(self):
        data = generate_hr_data(n_employees=100, seed=42, include_attrition=True)
        employees = data["employee"]
        performance = data["employee_performance"]

        terminated = employees[employees["termination_date"].notna()]

        for _, emp in terminated.head(10).iterrows():
            term_date = emp["termination_date"]
            emp_reviews = performance[performance["employee_id"] == emp["employee_id"]]

            for _, review in emp_reviews.iterrows():
                assert review["review_date"] <= term_date

    def test_reproducible_with_seed(self):
        data1 = generate_hr_data(n_employees=50, seed=123, include_attrition=True)
        data2 = generate_hr_data(n_employees=50, seed=123, include_attrition=True)

        pd.testing.assert_frame_equal(data1["employee"], data2["employee"])

    def test_different_seeds_different_attrition(self):
        data1 = generate_hr_data(n_employees=50, seed=1, include_attrition=True)
        data2 = generate_hr_data(n_employees=50, seed=2, include_attrition=True)

        term1 = set(data1["employee"][data1["employee"]["termination_date"].notna()]["employee_id"])
        term2 = set(data2["employee"][data2["employee"]["termination_date"].notna()]["employee_id"])

        # Different seeds should (usually) produce different terminated employees
        assert term1 != term2

"""Tests for the employee generation module."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hr_data_generator.employee import (
    DEFAULT_BU_DISTRIBUTION,
    assign_business_units,
    generate_employee_demographics,
    generate_employees_with_bands,
    get_age_for_band,
    get_age_gender,
    get_birth_date,
    get_employment_type,
    get_hire_date,
    get_location,
    get_name,
)
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


class TestGetAgeGender:
    def test_returns_tuple(self, employee_data, rng):
        result = get_age_gender(employee_data, rng)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_age_in_valid_range(self, employee_data, rng):
        for _ in range(100):
            age, _ = get_age_gender(employee_data, rng)
            assert 21 <= age <= 70

    def test_gender_is_valid(self, employee_data, rng):
        for _ in range(100):
            _, gender = get_age_gender(employee_data, rng)
            assert gender in ["male", "female", "na"]


class TestGetAgeForBand:
    def test_band_5_age_range(self, employee_data, rng):
        for _ in range(50):
            age = get_age_for_band(5, employee_data, rng)
            assert 45 <= age <= 65

    def test_band_1_age_range(self, employee_data, rng):
        for _ in range(50):
            age = get_age_for_band(1, employee_data, rng)
            assert 21 <= age <= 40


class TestGetName:
    def test_returns_tuple_of_strings(self, employee_data, rng):
        first, last = get_name("male", employee_data, rng)
        assert isinstance(first, str)
        assert isinstance(last, str)

    def test_male_names_from_male_list(self, employee_data, rng):
        first, _ = get_name("male", employee_data, rng)
        assert first in employee_data["male_first_names"]

    def test_female_names_from_female_list(self, employee_data, rng):
        first, _ = get_name("female", employee_data, rng)
        assert first in employee_data["female_names"]


class TestGetHireDate:
    def test_returns_date(self, rng):
        result = get_hire_date(30, rng)
        assert isinstance(result, date)

    def test_hire_date_not_future(self, rng):
        today = date.today()
        for _ in range(50):
            hire = get_hire_date(35, rng, today)
            assert hire <= today


class TestGetBirthDate:
    def test_returns_date(self, rng):
        hire_date = date(2020, 6, 15)
        result = get_birth_date(30, hire_date, rng)
        assert isinstance(result, date)

    def test_birth_year_matches_age(self, rng):
        hire_date = date(2020, 6, 15)
        age = 30
        birth_date = get_birth_date(age, hire_date, rng)
        assert birth_date.year == hire_date.year - age


class TestGenerateEmployeeDemographics:
    def test_returns_dataframe(self, employee_data, rng):
        df = generate_employee_demographics(10, employee_data, rng)
        assert isinstance(df, pd.DataFrame)

    def test_correct_row_count(self, employee_data, rng):
        n = 50
        df = generate_employee_demographics(n, employee_data, rng)
        assert len(df) == n

    def test_has_required_columns(self, employee_data, rng):
        df = generate_employee_demographics(10, employee_data, rng)
        required = [
            "employee_id", "first_name", "last_name", "gender",
            "birth_date", "hire_date", "employment_type",
            "employment_status", "location_id"
        ]
        for col in required:
            assert col in df.columns

    def test_unique_employee_ids(self, employee_data, rng):
        df = generate_employee_demographics(100, employee_data, rng)
        assert df["employee_id"].is_unique


class TestGenerateEmployeesWithBands:
    def test_returns_dataframe_with_seniority(self, employee_data, job_data, rng):
        df = generate_employees_with_bands(50, employee_data, job_data, rng)
        assert isinstance(df, pd.DataFrame)
        assert "_seniority_level" in df.columns

    def test_seniority_distribution(self, employee_data, job_data, rng):
        df = generate_employees_with_bands(100, employee_data, job_data, rng)
        seniority_counts = df["_seniority_level"].value_counts()
        assert 5 in seniority_counts.index
        assert seniority_counts[5] < seniority_counts[1]

    def test_has_business_unit_column(self, employee_data, job_data, rng):
        df = generate_employees_with_bands(50, employee_data, job_data, rng)
        assert "_business_unit" in df.columns

    def test_business_unit_values_are_valid(self, employee_data, job_data, rng):
        df = generate_employees_with_bands(100, employee_data, job_data, rng)
        valid_bus = set(DEFAULT_BU_DISTRIBUTION.keys())
        actual_bus = set(df["_business_unit"].unique())
        assert actual_bus.issubset(valid_bus)

    def test_custom_bu_distribution(self, employee_data, job_data, rng):
        custom_dist = {"Engineering": 0.70, "Sales": 0.20, "Corporate": 0.10}
        df = generate_employees_with_bands(
            200, employee_data, job_data, rng, bu_distribution=custom_dist
        )
        bu_counts = df["_business_unit"].value_counts(normalize=True)
        # Engineering should be majority with 70% target
        assert bu_counts.get("Engineering", 0) > 0.5


class TestAssignBusinessUnits:
    def test_returns_dict_with_all_bands(self, rng):
        seniority_counts = {5: 5, 4: 15, 3: 25, 2: 30, 1: 25}
        result = assign_business_units(100, seniority_counts, rng)
        assert set(result.keys()) == set(seniority_counts.keys())

    def test_correct_count_per_band(self, rng):
        seniority_counts = {5: 5, 4: 15, 3: 25, 2: 30, 1: 25}
        result = assign_business_units(100, seniority_counts, rng)
        for band, count in seniority_counts.items():
            assert len(result[band]) == count

    def test_all_assignments_are_valid_bus(self, rng):
        seniority_counts = {5: 5, 4: 15, 3: 25, 2: 30, 1: 25}
        result = assign_business_units(100, seniority_counts, rng)
        valid_bus = set(DEFAULT_BU_DISTRIBUTION.keys())
        for band, assignments in result.items():
            for bu in assignments:
                assert bu in valid_bus

    def test_leadership_coverage_in_each_bu(self, rng):
        # With enough level-4+ employees, each BU should have at least one
        seniority_counts = {5: 6, 4: 20, 3: 30, 2: 25, 1: 19}
        result = assign_business_units(100, seniority_counts, rng)
        # Combine level 4 and 5 assignments
        leadership_bus = result[5] + result[4]
        # Each BU with >=10% share should have leadership
        for bu in DEFAULT_BU_DISTRIBUTION.keys():
            assert bu in leadership_bus

    def test_custom_distribution(self, rng):
        seniority_counts = {5: 5, 4: 15, 3: 25, 2: 30, 1: 25}
        custom_dist = {"Engineering": 0.80, "Sales": 0.10, "Corporate": 0.10}
        result = assign_business_units(
            100, seniority_counts, rng, distribution=custom_dist
        )
        all_assignments = []
        for assignments in result.values():
            all_assignments.extend(assignments)
        # Engineering should be majority
        eng_count = sum(1 for bu in all_assignments if bu == "Engineering")
        assert eng_count > 50  # More than 50% should be Engineering

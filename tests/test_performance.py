"""Tests for the performance module."""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from hr_data_generator.employee import generate_employees_with_bands
from hr_data_generator.hierarchy import build_manager_hierarchy
from hr_data_generator.loader import load_employee_data, load_job_data, load_org_data
from hr_data_generator.performance import (
    RATING_DISTRIBUTION,
    RATING_LABELS,
    generate_performance_rating,
    generate_performance_reviews,
    get_performance_summary,
)


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
def employees_with_managers(employee_data, job_data, org_data, rng):
    employees = generate_employees_with_bands(50, employee_data, job_data, rng)
    return build_manager_hierarchy(employees, job_data, org_data, rng)


class TestGeneratePerformanceRating:
    def test_returns_valid_rating(self, rng):
        for _ in range(100):
            rating = generate_performance_rating(rng)
            assert rating in RATING_LABELS

    def test_rating_distribution_approximate(self, rng):
        ratings = [generate_performance_rating(rng) for _ in range(1000)]
        rating_counts = pd.Series(ratings).value_counts(normalize=True)

        for rating, expected_prob in RATING_DISTRIBUTION.items():
            actual = rating_counts.get(rating, 0)
            assert abs(actual - expected_prob) < 0.1


class TestGeneratePerformanceReviews:
    def test_returns_dataframe(self, employees_with_managers, rng):
        result = generate_performance_reviews(
            employees_with_managers, rng, start_year=2020, end_year=2023
        )
        assert isinstance(result, pd.DataFrame)

    def test_has_required_columns(self, employees_with_managers, rng):
        result = generate_performance_reviews(
            employees_with_managers, rng, start_year=2020, end_year=2023
        )
        required = [
            "employee_id", "review_period_year", "review_date",
            "rating", "rating_label", "manager_id"
        ]
        for col in required:
            assert col in result.columns

    def test_ratings_are_valid(self, employees_with_managers, rng):
        result = generate_performance_reviews(
            employees_with_managers, rng, start_year=2020, end_year=2023
        )
        for rating in result["rating"]:
            assert rating in RATING_LABELS

    def test_review_dates_in_december(self, employees_with_managers, rng):
        result = generate_performance_reviews(
            employees_with_managers, rng, start_year=2020, end_year=2023
        )
        for review_date in result["review_date"]:
            assert review_date.month == 12


class TestGetPerformanceSummary:
    def test_returns_dataframe(self, employees_with_managers, rng):
        reviews = generate_performance_reviews(
            employees_with_managers, rng, start_year=2020, end_year=2023
        )
        summary = get_performance_summary(reviews)
        assert isinstance(summary, pd.DataFrame)

    def test_percentages_sum_to_100(self, employees_with_managers, rng):
        reviews = generate_performance_reviews(
            employees_with_managers, rng, start_year=2020, end_year=2023
        )
        summary = get_performance_summary(reviews)
        if len(summary) > 0:
            assert abs(summary["percentage"].sum() - 100) < 0.01

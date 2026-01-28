"""Performance review generation module."""

from datetime import date

import numpy as np
import pandas as pd


RATING_DISTRIBUTION = {
    1: 0.05,
    2: 0.15,
    3: 0.50,
    4: 0.25,
    5: 0.05,
}

RATING_LABELS = {
    1: "Needs Improvement",
    2: "Partially Meets Expectations",
    3: "Meets Expectations",
    4: "Exceeds Expectations",
    5: "Outstanding",
}


def generate_performance_rating(rng: np.random.Generator) -> int:
    """Generate a performance rating based on distribution."""
    roll = rng.random()
    cumulative = 0.0
    for rating, prob in RATING_DISTRIBUTION.items():
        cumulative += prob
        if roll < cumulative:
            return rating
    return 3


def generate_performance_reviews(
    employees: pd.DataFrame,
    rng: np.random.Generator,
    start_year: int | None = None,
    end_year: int | None = None,
    review_month: int = 12,
    review_day: int = 15,
) -> pd.DataFrame:
    """
    Generate annual performance reviews for all employees.

    Reviews occur on Dec 15 each year for employees who were hired
    before that date.
    """
    if end_year is None:
        end_year = date.today().year

    if start_year is None:
        hire_dates = employees["hire_date"].apply(
            lambda x: x.year if isinstance(x, date) else date.fromisoformat(x).year
        )
        start_year = hire_dates.min()

    all_reviews = []

    for year in range(start_year, end_year + 1):
        review_date = date(year, review_month, review_day)

        for _, emp in employees.iterrows():
            hire_date = emp["hire_date"]
            if isinstance(hire_date, str):
                hire_date = date.fromisoformat(hire_date)

            if hire_date >= review_date:
                continue

            months_employed = (review_date.year - hire_date.year) * 12 + (
                review_date.month - hire_date.month
            )
            if months_employed < 6:
                continue

            rating = generate_performance_rating(rng)

            all_reviews.append({
                "employee_id": emp["employee_id"],
                "review_period_year": year,
                "review_date": review_date,
                "rating": rating,
                "rating_label": RATING_LABELS[rating],
                "manager_id": emp.get("manager_id"),
            })

    return pd.DataFrame(all_reviews)


def get_performance_summary(reviews: pd.DataFrame) -> pd.DataFrame:
    """Summarize performance by rating distribution."""
    if len(reviews) == 0:
        return pd.DataFrame()

    summary = reviews.groupby("rating_label")["employee_id"].count()
    summary = summary.reset_index()
    summary.columns = ["rating_label", "count"]
    summary["percentage"] = summary["count"] / summary["count"].sum() * 100
    return summary

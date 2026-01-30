"""Employee attrition generation module for ML turnover prediction."""

from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any, Callable

import numpy as np
import pandas as pd


class FactorStrategy(ABC):
    """Abstract strategy for calculating attrition probability factors."""

    @abstractmethod
    def get_factor(self, value: Any) -> float:
        """Calculate the factor multiplier for a given value."""
        ...


class LookupStrategy(FactorStrategy):
    """Lookup table-based factor calculation (simple, linear-ish patterns)."""

    def __init__(self, mapping: dict[Any, float], default: float = 1.0):
        """
        Initialize with a mapping from values to factors.

        Args:
            mapping: Dict mapping values to factor multipliers
            default: Default factor if value not in mapping
        """
        self.mapping = mapping
        self.default = default

    def get_factor(self, value: Any) -> float:
        return self.mapping.get(value, self.default)


class RangeLookupStrategy(FactorStrategy):
    """Range-based lookup for continuous values like tenure."""

    def __init__(self, ranges: list[tuple[float, float, float]], default: float = 1.0):
        """
        Initialize with ranges.

        Args:
            ranges: List of (min, max, factor) tuples. Max is exclusive.
            default: Default factor if value not in any range
        """
        self.ranges = ranges
        self.default = default

    def get_factor(self, value: float) -> float:
        for min_val, max_val, factor in self.ranges:
            if min_val <= value < max_val:
                return factor
        return self.default


class FormulaStrategy(FactorStrategy):
    """Formula-based factor calculation (non-linear patterns)."""

    def __init__(self, func: Callable[[Any], float]):
        """
        Initialize with a calculation function.

        Args:
            func: Function that takes a value and returns a factor
        """
        self.func = func

    def get_factor(self, value: Any) -> float:
        return self.func(value)


# Default factor configurations
DEFAULT_PERFORMANCE_FACTORS = {
    1: 2.5,  # Needs Improvement - highest attrition risk
    2: 1.5,  # Partially Meets
    3: 1.0,  # Meets Expectations - baseline
    4: 0.6,  # Exceeds Expectations
    5: 0.4,  # Outstanding - lowest attrition risk
}

# Tenure in years: (min, max_exclusive, factor)
DEFAULT_TENURE_RANGES = [
    (0, 1, 1.8),    # < 1 year - very high risk (still adjusting)
    (1, 2, 1.3),    # 1-2 years - elevated risk
    (2, 5, 1.0),    # 2-5 years - baseline
    (5, 10, 0.7),   # 5-10 years - lower risk (invested)
    (10, 100, 0.5), # 10+ years - lowest risk (long tenure)
]

DEFAULT_EMPLOYMENT_TYPE_FACTORS = {
    "Full-time": 1.0,   # Baseline
    "Contract": 2.0,    # Higher turnover (less stability)
    "Part-time": 1.4,   # Moderately higher
}

DEFAULT_SENIORITY_FACTORS = {
    1: 1.3,  # Junior - higher turnover (career exploration)
    2: 1.1,  # Mid-level
    3: 0.9,  # Senior
    4: 0.7,  # Manager/Staff
    5: 0.5,  # Director - lowest turnover
}

DEFAULT_PROMOTION_FACTORS = {
    True: 0.4,   # Recent promotion - much lower attrition
    False: 1.0,  # No recent promotion - baseline
}

# Termination reasons with their relative weights
VOLUNTARY_REASONS = {
    "Resignation - Career Opportunity": 0.35,
    "Resignation - Personal Reasons": 0.20,
    "Resignation - Relocation": 0.15,
    "Retirement": 0.30,  # Will be weighted by age
}

INVOLUNTARY_REASONS = {
    "Termination - Performance": 0.40,
    "Termination - Policy Violation": 0.15,
    "Layoff - Restructuring": 0.30,
    "Layoff - Cost Reduction": 0.15,
}


class AttritionModel:
    """Model for calculating employee attrition probability."""

    def __init__(
        self,
        base_annual_rate: float = 0.12,
        performance_strategy: FactorStrategy | None = None,
        tenure_strategy: FactorStrategy | None = None,
        employment_type_strategy: FactorStrategy | None = None,
        seniority_strategy: FactorStrategy | None = None,
        promotion_strategy: FactorStrategy | None = None,
        noise_std: float = 0.2,
        unexplained_departure_rate: float = 0.025,
        unexplained_retention_rate: float = 0.05,
    ):
        """
        Initialize the attrition model.

        Args:
            base_annual_rate: Base annual attrition rate (default 12%)
            performance_strategy: Strategy for performance factor
            tenure_strategy: Strategy for tenure factor
            employment_type_strategy: Strategy for employment type factor
            seniority_strategy: Strategy for seniority factor
            promotion_strategy: Strategy for promotion factor
            noise_std: Standard deviation for probability noise (0.2 = ~80-85% ML accuracy)
            unexplained_departure_rate: Baseline chance any employee leaves unexpectedly
            unexplained_retention_rate: Chance high-risk employees stay anyway
        """
        self.base_annual_rate = base_annual_rate
        self.noise_std = noise_std
        self.unexplained_departure_rate = unexplained_departure_rate
        self.unexplained_retention_rate = unexplained_retention_rate

        # Initialize strategies with defaults
        self.performance_strategy = performance_strategy or LookupStrategy(
            DEFAULT_PERFORMANCE_FACTORS
        )
        self.tenure_strategy = tenure_strategy or RangeLookupStrategy(
            DEFAULT_TENURE_RANGES
        )
        self.employment_type_strategy = employment_type_strategy or LookupStrategy(
            DEFAULT_EMPLOYMENT_TYPE_FACTORS
        )
        self.seniority_strategy = seniority_strategy or LookupStrategy(
            DEFAULT_SENIORITY_FACTORS
        )
        self.promotion_strategy = promotion_strategy or LookupStrategy(
            DEFAULT_PROMOTION_FACTORS
        )

    def calculate_base_probability(
        self,
        performance_rating: int | None,
        tenure_years: float,
        employment_type: str,
        seniority_level: int,
        had_recent_promotion: bool,
    ) -> float:
        """
        Calculate base attrition probability before noise.

        Returns:
            Annual probability of leaving (0.0 to 1.0)
        """
        # Start with base rate
        prob = self.base_annual_rate

        # Apply factors
        if performance_rating is not None:
            prob *= self.performance_strategy.get_factor(performance_rating)

        prob *= self.tenure_strategy.get_factor(tenure_years)
        prob *= self.employment_type_strategy.get_factor(employment_type)
        prob *= self.seniority_strategy.get_factor(seniority_level)
        prob *= self.promotion_strategy.get_factor(had_recent_promotion)

        return min(1.0, max(0.0, prob))

    def calculate_probability_with_noise(
        self,
        base_probability: float,
        rng: np.random.Generator,
    ) -> float:
        """
        Apply noise to base probability for realism.

        Args:
            base_probability: Calculated base probability
            rng: Random number generator

        Returns:
            Final probability with noise applied
        """
        # Add Gaussian noise
        if self.noise_std > 0:
            noise = rng.normal(0, self.noise_std)
            prob = base_probability * (1 + noise)
        else:
            prob = base_probability

        # Unexplained departures: even low-risk employees sometimes leave
        if rng.random() < self.unexplained_departure_rate:
            prob = max(prob, 0.5)  # Bump up probability significantly

        # Unexplained retention: high-risk employees sometimes stay
        if base_probability > 0.3 and rng.random() < self.unexplained_retention_rate:
            prob *= 0.3  # Significantly reduce probability

        return min(1.0, max(0.0, prob))

    def will_leave_this_year(
        self,
        performance_rating: int | None,
        tenure_years: float,
        employment_type: str,
        seniority_level: int,
        had_recent_promotion: bool,
        rng: np.random.Generator,
    ) -> bool:
        """Determine if an employee will leave this year."""
        base_prob = self.calculate_base_probability(
            performance_rating,
            tenure_years,
            employment_type,
            seniority_level,
            had_recent_promotion,
        )
        final_prob = self.calculate_probability_with_noise(base_prob, rng)
        return rng.random() < final_prob


def select_termination_reason(
    age: int,
    performance_rating: int | None,
    rng: np.random.Generator,
) -> tuple[str, str]:
    """
    Select termination reason based on employee characteristics.

    Args:
        age: Employee age
        performance_rating: Most recent performance rating (1-5)
        rng: Random number generator

    Returns:
        Tuple of (reason, category) where category is "Voluntary" or "Involuntary"
    """
    # Determine voluntary vs involuntary based on performance
    # Low performers more likely to be terminated
    involuntary_prob = 0.15  # Base involuntary rate

    if performance_rating is not None:
        if performance_rating <= 2:
            involuntary_prob = 0.60  # Low performers mostly terminated
        elif performance_rating == 3:
            involuntary_prob = 0.20
        else:
            involuntary_prob = 0.05  # High performers rarely terminated

    is_voluntary = rng.random() > involuntary_prob

    if is_voluntary:
        reasons = VOLUNTARY_REASONS.copy()

        # Adjust retirement probability based on age
        if age >= 60:
            # High retirement probability for 60+
            retirement_boost = min(0.8, (age - 55) * 0.1)
            reasons["Retirement"] = retirement_boost
        elif age >= 55:
            reasons["Retirement"] = 0.15
        else:
            reasons["Retirement"] = 0.0  # Can't retire young

        # Normalize weights
        total = sum(reasons.values())
        if total == 0:
            # Fallback if retirement was the only option
            return "Resignation - Career Opportunity", "Voluntary"

        probs = [v / total for v in reasons.values()]
        reason = rng.choice(list(reasons.keys()), p=probs)
        return reason, "Voluntary"
    else:
        probs = list(INVOLUNTARY_REASONS.values())
        total = sum(probs)
        probs = [p / total for p in probs]
        reason = rng.choice(list(INVOLUNTARY_REASONS.keys()), p=probs)
        return reason, "Involuntary"


def get_termination_date(
    year: int,
    hire_date: date,
    rng: np.random.Generator,
) -> date:
    """
    Generate a termination date within a given year.

    Args:
        year: Year of termination
        hire_date: Employee hire date (termination must be after)
        rng: Random number generator

    Returns:
        Termination date
    """
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)

    # Start from later of year start or hire date
    start = max(year_start, hire_date + timedelta(days=30))  # At least 30 days employed

    if start >= year_end:
        return year_end

    days_range = (year_end - start).days
    if days_range <= 0:
        return year_end

    random_days = rng.integers(0, days_range + 1)
    return start + timedelta(days=int(random_days))


def apply_attrition(
    employees: pd.DataFrame,
    performance_reviews: pd.DataFrame | None,
    job_assignments: pd.DataFrame,
    rng: np.random.Generator,
    start_year: int,
    end_year: int,
    attrition_rate: float = 0.12,
    noise_std: float = 0.2,
) -> pd.DataFrame:
    """
    Apply attrition to employees over a simulation period.

    Modifies employees DataFrame in place to add termination information.

    Args:
        employees: Employee DataFrame (must include hire_date, employment_type)
        performance_reviews: Performance reviews DataFrame (optional)
        job_assignments: Job assignments DataFrame
        rng: Random number generator
        start_year: First year of simulation
        end_year: Last year of simulation
        attrition_rate: Base annual attrition rate
        noise_std: Noise for probability variation

    Returns:
        Updated employees DataFrame with termination fields
    """
    model = AttritionModel(
        base_annual_rate=attrition_rate,
        noise_std=noise_std,
    )

    # Initialize termination fields
    employees = employees.copy()
    employees["termination_date"] = None
    employees["termination_reason"] = None

    # Process each year
    for year in range(start_year, end_year + 1):
        year_end = date(year, 12, 31)

        for idx, emp in employees.iterrows():
            # Skip already terminated
            if emp["termination_date"] is not None:
                continue

            hire_date = emp["hire_date"]
            if isinstance(hire_date, str):
                hire_date = date.fromisoformat(hire_date)

            # Skip if not hired yet
            if hire_date.year > year:
                continue

            # Calculate tenure
            tenure_years = (year_end - hire_date).days / 365.25

            # Skip if tenure < 0.25 years (3 months)
            if tenure_years < 0.25:
                continue

            # Get most recent performance rating
            perf_rating = None
            if performance_reviews is not None and len(performance_reviews) > 0:
                emp_reviews = performance_reviews[
                    (performance_reviews["employee_id"] == emp["employee_id"])
                    & (performance_reviews["review_period_year"] < year)
                ].sort_values("review_period_year", ascending=False)
                if len(emp_reviews) > 0:
                    perf_rating = emp_reviews.iloc[0]["rating"]

            # Get current seniority level
            emp_jobs = job_assignments[
                job_assignments["employee_id"] == emp["employee_id"]
            ]
            current_job = emp_jobs[
                (emp_jobs["start_date"] <= year_end)
                & ((emp_jobs["end_date"].isna()) | (emp_jobs["end_date"] >= year_end))
            ]
            if len(current_job) == 0:
                current_job = emp_jobs[emp_jobs["start_date"] <= year_end]
                if len(current_job) == 0:
                    continue
                current_job = current_job.iloc[-1:]

            seniority_level = current_job.iloc[0]["seniority_level"]

            # Check for recent promotion (within last year)
            had_promotion = False
            year_start = date(year, 1, 1)
            prev_year_start = date(year - 1, 1, 1)
            for _, job in emp_jobs.iterrows():
                job_start = job["start_date"]
                if isinstance(job_start, str):
                    job_start = date.fromisoformat(job_start)
                if prev_year_start <= job_start <= year_start:
                    # Check if this was a promotion (higher seniority than previous)
                    prev_jobs = emp_jobs[emp_jobs["start_date"] < job_start]
                    if len(prev_jobs) > 0:
                        prev_seniority = prev_jobs.iloc[-1]["seniority_level"]
                        if job["seniority_level"] > prev_seniority:
                            had_promotion = True
                            break

            # Determine if employee leaves this year
            will_leave = model.will_leave_this_year(
                performance_rating=perf_rating,
                tenure_years=tenure_years,
                employment_type=emp["employment_type"],
                seniority_level=seniority_level,
                had_recent_promotion=had_promotion,
                rng=rng,
            )

            if will_leave:
                # Calculate age at termination
                birth_date = emp["birth_date"]
                if isinstance(birth_date, str):
                    birth_date = date.fromisoformat(birth_date)
                age = year - birth_date.year

                # Select termination reason
                reason, category = select_termination_reason(age, perf_rating, rng)

                # If retirement selected but age < 55, choose different reason
                if "Retirement" in reason and age < 55:
                    reason = "Resignation - Career Opportunity"
                    category = "Voluntary"

                # Get termination date
                term_date = get_termination_date(year, hire_date, rng)

                employees.at[idx, "termination_date"] = term_date
                employees.at[idx, "termination_reason"] = reason

                # Update employment status
                if "Retirement" in reason:
                    employees.at[idx, "employment_status"] = "Retired"
                else:
                    employees.at[idx, "employment_status"] = "Terminated"

    return employees


def close_records_at_termination(
    records: pd.DataFrame,
    employees: pd.DataFrame,
    date_column: str = "start_date",
) -> pd.DataFrame:
    """
    Close time-variant records at employee termination dates.

    Args:
        records: Time-variant records with employee_id, start_date, end_date
        employees: Employees DataFrame with termination_date
        date_column: Name of the date column to check

    Returns:
        Updated records with end_dates set appropriately
    """
    records = records.copy()

    terminated = employees[employees["termination_date"].notna()]

    for _, emp in terminated.iterrows():
        term_date = emp["termination_date"]
        if isinstance(term_date, str):
            term_date = date.fromisoformat(term_date)

        emp_records = records[records["employee_id"] == emp["employee_id"]]

        for idx, record in emp_records.iterrows():
            start = record["start_date"]
            if isinstance(start, str):
                start = date.fromisoformat(start)

            # Close records that are open and started before termination
            if start <= term_date:
                end = record["end_date"]
                if end is None or pd.isna(end):
                    records.at[idx, "end_date"] = term_date
                elif isinstance(end, str):
                    end = date.fromisoformat(end)
                    if end > term_date:
                        records.at[idx, "end_date"] = term_date
                elif end > term_date:
                    records.at[idx, "end_date"] = term_date

    return records


def filter_reviews_by_termination(
    reviews: pd.DataFrame,
    employees: pd.DataFrame,
) -> pd.DataFrame:
    """
    Remove performance reviews that occurred after termination.

    Args:
        reviews: Performance reviews DataFrame
        employees: Employees DataFrame with termination_date

    Returns:
        Filtered reviews DataFrame
    """
    if len(reviews) == 0:
        return reviews

    reviews = reviews.copy()

    terminated = employees[employees["termination_date"].notna()]

    mask = pd.Series(True, index=reviews.index)

    for _, emp in terminated.iterrows():
        term_date = emp["termination_date"]
        if isinstance(term_date, str):
            term_date = date.fromisoformat(term_date)

        emp_reviews_mask = (
            (reviews["employee_id"] == emp["employee_id"])
            & (reviews["review_date"] > term_date)
        )
        mask = mask & ~emp_reviews_mask

    return reviews[mask]

"""Career event simulation for time-variant records."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

import numpy as np
import pandas as pd


@dataclass
class CareerEvent:
    """Represents a career event for an employee."""

    employee_id: str
    event_type: Literal["hire", "promotion", "transfer", "termination"]
    event_date: date
    old_value: str | None = None
    new_value: str | None = None


class CareerSimulator:
    """Simulates career events over time for employees."""

    def __init__(
        self,
        rng: np.random.Generator,
        promotion_probability: float = 0.15,
        transfer_probability: float = 0.08,
        termination_probability: float = 0.05,
    ):
        self.rng = rng
        self.promotion_probability = promotion_probability
        self.transfer_probability = transfer_probability
        self.termination_probability = termination_probability

    def simulate_career_events(
        self,
        employees: pd.DataFrame,
        start_date: date,
        end_date: date,
        job_data: pd.DataFrame,
        org_data: pd.DataFrame,
    ) -> list[CareerEvent]:
        """
        Simulate career events for all employees between start and end dates.

        Events are generated per-year for each employee who was hired before
        that year and is still active.
        """
        events = []

        for _, emp in employees.iterrows():
            emp_events = self._simulate_employee_career(
                emp, start_date, end_date, job_data, org_data
            )
            events.extend(emp_events)

        return events

    def _simulate_employee_career(
        self,
        employee: pd.Series,
        start_date: date,
        end_date: date,
        job_data: pd.DataFrame,
        org_data: pd.DataFrame,
    ) -> list[CareerEvent]:
        """Simulate career events for a single employee."""
        events = []
        hire_date = employee["hire_date"]
        if isinstance(hire_date, str):
            hire_date = date.fromisoformat(hire_date)

        current_seniority = employee.get("_seniority_level", 1)
        is_active = True

        sim_start = max(hire_date, start_date)
        current_year = sim_start.year

        while current_year <= end_date.year and is_active:
            year_date = date(current_year, 7, 1)

            if year_date <= hire_date:
                current_year += 1
                continue

            if self.rng.random() < self.promotion_probability:
                if current_seniority < 5:
                    events.append(
                        CareerEvent(
                            employee_id=employee["employee_id"],
                            event_type="promotion",
                            event_date=year_date,
                            old_value=str(current_seniority),
                            new_value=str(current_seniority + 1),
                        )
                    )
                    current_seniority += 1

            if self.rng.random() < self.transfer_probability:
                events.append(
                    CareerEvent(
                        employee_id=employee["employee_id"],
                        event_type="transfer",
                        event_date=year_date + timedelta(days=self.rng.integers(0, 180)),
                    )
                )

            if self.rng.random() < self.termination_probability:
                term_date = date(current_year, 12, 31)
                events.append(
                    CareerEvent(
                        employee_id=employee["employee_id"],
                        event_type="termination",
                        event_date=term_date,
                    )
                )
                is_active = False

            current_year += 1

        return events


def get_years_between(start: date, end: date) -> list[int]:
    """Get list of years between two dates."""
    return list(range(start.year, end.year + 1))

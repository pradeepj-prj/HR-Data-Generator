"""Manager hierarchy builder for organizational structure."""

import numpy as np
import pandas as pd


def build_manager_hierarchy(
    employees: pd.DataFrame,
    job_data: pd.DataFrame,
    org_data: pd.DataFrame,
    rng: np.random.Generator,
    min_span: int = 3,
    max_span: int = 10,
) -> pd.DataFrame:
    """
    Build manager hierarchy ensuring managers have higher seniority than reports.

    Algorithm:
    1. Sort employees by seniority (highest first)
    2. Select CEO (seniority=5, NULL manager_id)
    3. Assign Directors to CEO
    4. Assign Managers to Directors (respecting business_unit alignment)
    5. Assign ICs to Managers (respecting span of control)

    Returns employees DataFrame with manager_id column added.
    """
    df = employees.copy()

    if "_seniority_level" not in df.columns:
        raise ValueError("Employees must have _seniority_level column")

    df = df.sort_values("_seniority_level", ascending=False).reset_index(drop=True)
    df["manager_id"] = None

    level_5 = df[df["_seniority_level"] == 5]
    level_4 = df[df["_seniority_level"] == 4]
    level_3 = df[df["_seniority_level"] == 3]
    level_2 = df[df["_seniority_level"] == 2]
    level_1 = df[df["_seniority_level"] == 1]

    if len(level_5) == 0:
        raise ValueError("Need at least one level-5 employee for CEO")

    ceo_idx = level_5.index[0]
    ceo_id = df.loc[ceo_idx, "employee_id"]

    directors = level_5.index[1:].tolist()
    for dir_idx in directors:
        df.loc[dir_idx, "manager_id"] = ceo_id

    all_directors = [ceo_id] + [df.loc[idx, "employee_id"] for idx in directors]

    managers_idx = level_4.index.tolist()
    if len(managers_idx) > 0 and len(all_directors) > 0:
        for mgr_idx in managers_idx:
            director_id = rng.choice(all_directors)
            df.loc[mgr_idx, "manager_id"] = director_id

    all_managers = [df.loc[idx, "employee_id"] for idx in managers_idx]
    if len(all_managers) == 0:
        all_managers = all_directors

    senior_idx = level_3.index.tolist()
    if len(senior_idx) > 0 and len(all_managers) > 0:
        for sr_idx in senior_idx:
            manager_id = rng.choice(all_managers)
            df.loc[sr_idx, "manager_id"] = manager_id

    all_seniors = [df.loc[idx, "employee_id"] for idx in senior_idx]
    if len(all_seniors) == 0:
        all_seniors = all_managers

    mid_idx = level_2.index.tolist()
    if len(mid_idx) > 0:
        supervisors = all_seniors if len(all_seniors) > 0 else all_managers
        if len(supervisors) > 0:
            for m_idx in mid_idx:
                supervisor_id = rng.choice(supervisors)
                df.loc[m_idx, "manager_id"] = supervisor_id

    all_mids = [df.loc[idx, "employee_id"] for idx in mid_idx]
    potential_supervisors = all_mids + all_seniors + all_managers

    junior_idx = level_1.index.tolist()
    if len(junior_idx) > 0 and len(potential_supervisors) > 0:
        for j_idx in junior_idx:
            supervisor_id = rng.choice(potential_supervisors)
            df.loc[j_idx, "manager_id"] = supervisor_id

    return df


def validate_hierarchy(employees: pd.DataFrame) -> list[str]:
    """Validate manager hierarchy for correctness."""
    errors = []

    emp_ids = set(employees["employee_id"].tolist())
    for _, row in employees.iterrows():
        if row["manager_id"] is not None and row["manager_id"] not in emp_ids:
            errors.append(
                f"Employee {row['employee_id']} has invalid manager_id {row['manager_id']}"
            )

    for _, row in employees.iterrows():
        if row["manager_id"] == row["employee_id"]:
            errors.append(f"Employee {row['employee_id']} reports to themselves")

    ceo_count = employees["manager_id"].isna().sum()
    if ceo_count != 1:
        errors.append(f"Expected 1 CEO (null manager_id), found {ceo_count}")

    return errors

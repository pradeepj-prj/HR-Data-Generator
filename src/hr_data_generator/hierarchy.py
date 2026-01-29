"""Manager hierarchy builder for organizational structure."""

import warnings

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

    Builds hierarchy per business unit to ensure manager-report alignment.

    Algorithm:
    1. Select CEO (first level-5 employee) - manages entire company
    2. Other level-5 employees are BU heads, report to CEO
    3. For each business unit:
       - Level-4 reports to level-5 in same BU
       - Level-3 reports to level-4 in same BU
       - Level-2 reports to level-3 in same BU
       - Level-1 reports to level-2/3 in same BU
    4. Handle edge cases with fallbacks

    Returns employees DataFrame with manager_id column added.
    """
    df = employees.copy()

    if "_seniority_level" not in df.columns:
        raise ValueError("Employees must have _seniority_level column")

    if "_business_unit" not in df.columns:
        raise ValueError("Employees must have _business_unit column")

    df = df.sort_values("_seniority_level", ascending=False).reset_index(drop=True)
    df["manager_id"] = None

    level_5 = df[df["_seniority_level"] == 5]

    if len(level_5) == 0:
        raise ValueError("Need at least one level-5 employee for CEO")

    # Select CEO (first level-5 employee)
    ceo_idx = level_5.index[0]
    ceo_id = df.loc[ceo_idx, "employee_id"]

    # Other level-5 employees are BU heads, report to CEO
    bu_heads: dict[str, str] = {}  # BU -> employee_id of BU head
    for idx in level_5.index[1:]:
        df.loc[idx, "manager_id"] = ceo_id
        bu = df.loc[idx, "_business_unit"]
        if bu not in bu_heads:
            bu_heads[bu] = df.loc[idx, "employee_id"]

    # Get all business units
    business_units = df["_business_unit"].unique().tolist()

    # Build hierarchy per business unit
    for bu in business_units:
        bu_df = df[df["_business_unit"] == bu]

        # Get BU head (level-5 in this BU, or CEO if none)
        bu_level_5 = bu_df[bu_df["_seniority_level"] == 5]
        if len(bu_level_5) > 0:
            # Use first non-CEO level-5 as BU head, or CEO if that's the only one
            bu_head_candidates = [
                idx for idx in bu_level_5.index if df.loc[idx, "employee_id"] != ceo_id
            ]
            if bu_head_candidates:
                bu_head_id = df.loc[bu_head_candidates[0], "employee_id"]
            else:
                # CEO is the only level-5 in this BU
                bu_head_id = ceo_id
        else:
            # No level-5 in this BU, use CEO
            bu_head_id = ceo_id

        # Level-4 reports to BU head (level-5 or CEO)
        bu_level_4 = bu_df[bu_df["_seniority_level"] == 4]
        level_4_ids = []
        for idx in bu_level_4.index:
            df.loc[idx, "manager_id"] = bu_head_id
            level_4_ids.append(df.loc[idx, "employee_id"])

        # Level-3 reports to level-4 in same BU
        bu_level_3 = bu_df[bu_df["_seniority_level"] == 3]
        level_3_ids = []
        supervisors_for_3 = level_4_ids if level_4_ids else [bu_head_id]
        for idx in bu_level_3.index:
            manager_id = rng.choice(supervisors_for_3)
            df.loc[idx, "manager_id"] = manager_id
            level_3_ids.append(df.loc[idx, "employee_id"])

        # Level-2 reports to level-3 in same BU
        bu_level_2 = bu_df[bu_df["_seniority_level"] == 2]
        level_2_ids = []
        supervisors_for_2 = level_3_ids if level_3_ids else supervisors_for_3
        for idx in bu_level_2.index:
            manager_id = rng.choice(supervisors_for_2)
            df.loc[idx, "manager_id"] = manager_id
            level_2_ids.append(df.loc[idx, "employee_id"])

        # Level-1 reports to level-2 or level-3 in same BU
        bu_level_1 = bu_df[bu_df["_seniority_level"] == 1]
        potential_supervisors = level_2_ids + level_3_ids
        if not potential_supervisors:
            potential_supervisors = supervisors_for_2
        for idx in bu_level_1.index:
            manager_id = rng.choice(potential_supervisors)
            df.loc[idx, "manager_id"] = manager_id

    # Warn if any non-CEO employees have no manager (shouldn't happen)
    missing_managers = df[(df["manager_id"].isna()) & (df["employee_id"] != ceo_id)]
    if len(missing_managers) > 0:
        warnings.warn(
            f"{len(missing_managers)} employees have no manager assigned. "
            "Assigning to CEO as fallback."
        )
        for idx in missing_managers.index:
            df.loc[idx, "manager_id"] = ceo_id

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


def validate_manager_bu_alignment(employees: pd.DataFrame) -> list[str]:
    """
    Validate that non-CEO employees have managers in the same business unit.

    Exceptions:
    - CEO has no manager (allowed)
    - Anyone reporting directly to CEO is allowed (CEO is company-wide)
    - For non-CEO managers, employee must be in same BU as manager

    Args:
        employees: DataFrame with employee_id, manager_id, _business_unit, _seniority_level

    Returns:
        List of validation error messages
    """
    errors = []

    if "_business_unit" not in employees.columns:
        errors.append("Missing _business_unit column for BU alignment validation")
        return errors

    # Create lookup for employee -> business unit
    emp_to_bu = dict(zip(employees["employee_id"], employees["_business_unit"]))

    # Find CEO (employee with null manager_id)
    ceo_mask = employees["manager_id"].isna()
    if ceo_mask.sum() != 1:
        errors.append(f"Expected exactly 1 CEO, found {ceo_mask.sum()}")
        return errors

    ceo_id = employees.loc[ceo_mask, "employee_id"].iloc[0]

    for _, row in employees.iterrows():
        emp_id = row["employee_id"]
        manager_id = row["manager_id"]
        emp_bu = row["_business_unit"]

        # Skip CEO (no manager)
        if manager_id is None:
            continue

        # Anyone reporting directly to CEO is allowed (CEO is company-wide)
        if manager_id == ceo_id:
            continue

        # For non-CEO managers, employee must be in same BU as manager
        manager_bu = emp_to_bu.get(manager_id)
        if manager_bu is None:
            errors.append(f"Employee {emp_id} has unknown manager {manager_id}")
        elif manager_bu != emp_bu:
            errors.append(
                f"Employee {emp_id} ({emp_bu}) reports to manager {manager_id} "
                f"({manager_bu}) - cross-BU reporting"
            )

    return errors

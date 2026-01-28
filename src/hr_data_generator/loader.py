"""Data loader module for bundled HR data files."""

from importlib import resources
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def _get_data_path(filename: str) -> Path:
    """Get path to a bundled data file."""
    with resources.as_file(
        resources.files("hr_data_generator.data").joinpath(filename)
    ) as path:
        return Path(path)


def load_employee_data() -> dict[str, Any]:
    """Load employee generation parameters from YAML."""
    path = _get_data_path("employee_data.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def load_job_data() -> pd.DataFrame:
    """Load job role catalog."""
    path = _get_data_path("job_data.csv")
    return pd.read_csv(path)


def load_org_data() -> pd.DataFrame:
    """Load organization hierarchy."""
    path = _get_data_path("org_data.csv")
    return pd.read_csv(path)


def load_location_data() -> pd.DataFrame:
    """Load location reference data."""
    path = _get_data_path("location_data.csv")
    return pd.read_csv(path)


def load_all_reference_data() -> dict[str, pd.DataFrame]:
    """Load all reference tables as DataFrames."""
    return {
        "organization_unit": load_org_data(),
        "job_role": load_job_data(),
        "location": load_location_data(),
    }

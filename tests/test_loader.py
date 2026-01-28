"""Tests for the data loader module."""

import pandas as pd
import pytest

from hr_data_generator.loader import (
    load_all_reference_data,
    load_employee_data,
    load_job_data,
    load_location_data,
    load_org_data,
)


def test_load_employee_data():
    """Test loading employee configuration YAML."""
    data = load_employee_data()
    assert isinstance(data, dict)
    assert "male_first_names" in data
    assert "female_names" in data
    assert "male_last_names" in data
    assert "age_mean" in data
    assert "age_spread" in data
    assert "prob_female" in data
    assert "location_id" in data


def test_load_job_data():
    """Test loading job role catalog."""
    df = load_job_data()
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert "job_id" in df.columns
    assert "job_title" in df.columns
    assert "job_family" in df.columns
    assert "job_level" in df.columns
    assert "seniority_level" in df.columns


def test_load_org_data():
    """Test loading organization hierarchy."""
    df = load_org_data()
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert "org_id" in df.columns
    assert "org_name" in df.columns
    assert "parent_org_id" in df.columns
    assert "business_unit" in df.columns


def test_load_location_data():
    """Test loading location reference data."""
    df = load_location_data()
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert "location_id" in df.columns
    assert "city" in df.columns
    assert "country" in df.columns


def test_load_all_reference_data():
    """Test loading all reference tables."""
    data = load_all_reference_data()
    assert isinstance(data, dict)
    assert "organization_unit" in data
    assert "job_role" in data
    assert "location" in data
    assert all(isinstance(df, pd.DataFrame) for df in data.values())

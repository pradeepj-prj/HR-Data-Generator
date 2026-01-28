# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

HR Data Generator is a Python-based synthetic data generator that creates realistic mock HR datasets in a SuccessFactors-style format. Designed for learning and demos with SAP HANA Cloud, BDC/Datasphere, and AI use cases.

## Development Setup

Python version: 3.10 (managed via pyenv, see `.python-version`)

Activate the virtual environment:
```bash
source .venv/bin/activate
```

Dependencies: numpy, pandas, pyyaml (installed in venv)

## Running the Generator

Via Jupyter notebook:
```bash
jupyter notebook notebooks/01_generate_date.ipynb
```

Via Python:
```python
from hr_data_generation import hr_gen, config
import yaml

with open(config.EMPLOYEE_DATA_PATH, "r") as f:
    employee_data = yaml.load(f, Loader=yaml.SafeLoader)

employees = hr_gen.generate_employees(100, employee_data)
```

## Architecture

### Data Model (SuccessFactors-style)

- `employee` is the hub table with one row per person
- Time-variant satellites: org assignment, job assignment, compensation, performance
- Org assignment and job assignment are separate by design
- `start_date`/`end_date` enable time-travel analytics and ML feature engineering
- `seniority_level` on jobs enforces plausible synthetic assignments

### Code Structure

- `hr_data_generation/hr_gen.py` - Core generator functions:
  - `generate_employees(n, employee_data)` - Main batch generation function
  - `get_age_gender()` - Normal distribution for age, probabilistic gender
  - `get_name()` - Gender-based name selection
  - `get_hiring_date()` - Realistic hire dates based on age (21-year career start)
  - `get_emp_type_country()` - Employment type and location assignment

- `hr_data_generation/config.py` - Paths to parameter files

- `hr_data_generation/params/` - Configuration data:
  - `employee_data.yaml` - Employee generation parameters (names, probabilities)
  - `job_data.csv` - Job role catalog (48 roles across Engineering, Sales, Corporate)
  - `org_data.csv` - Organization hierarchy (multi-level departments)
  - `location_data.csv` - 45+ APJ region locations with coordinates

### Generation Flow

1. Generate employee demographics (age via normal distribution, probabilistic gender)
2. Select names based on gender from YAML config
3. Calculate realistic hire dates based on age
4. Assign employment type (Full-time 70%, Contract 10%, Part-time 20%) and location
5. Assign to organization and job roles based on seniority profiles

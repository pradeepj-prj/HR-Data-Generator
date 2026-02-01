# HR Data Generator

A pip-installable Python library that generates realistic SuccessFactors-style HR datasets for learning and demos with **SAP HANA Cloud**, **BDC/Datasphere**, and **AI use cases**.

## Features

- Generates 8 interconnected HR tables with referential integrity
- **Employee attrition simulation** for ML turnover prediction
- **Hiring simulation** for balanced workforce dynamics
- Reproducible results with seed parameter
- Time-variant records with proper start_date/end_date chaining
- Realistic manager hierarchy with seniority constraints
- Band-aware age generation matching job seniority
- Configurable employee count, date ranges, and business unit distribution

## Installation

```bash
# Install from source
pip install -e .

# With development dependencies (for testing)
pip install -e ".[dev]"
```

## Quick Start

```python
from hr_data_generator import generate_hr_data

# Generate 500 employees with reproducible results
data = generate_hr_data(n_employees=500, seed=42)

# Access the generated tables
employees = data['employee']
job_history = data['employee_job_assignment']
org_history = data['employee_org_assignment']
compensation = data['employee_compensation']
performance = data['employee_performance']

# Reference tables
orgs = data['organization_unit']
jobs = data['job_role']
locations = data['location']

# Check attrition (enabled by default)
terminated = employees[employees['termination_date'].notna()]
print(f"Attrition rate: {len(terminated)/len(employees):.1%}")
```

## API Reference

### `generate_hr_data()`

Main function to generate complete HR dataset.

```python
generate_hr_data(
    n_employees=100,           # Number of employees to generate
    start_date=None,           # Simulation start (default: 5 years ago)
    end_date=None,             # Simulation end (default: today)
    seed=None,                 # Random seed for reproducibility
    include_performance=True,  # Generate performance reviews
    include_compensation=True, # Generate compensation records
    include_attrition=True,    # Apply employee attrition/turnover
    attrition_rate=0.12,       # Base annual attrition rate (12%)
    noise_std=0.2,             # Noise for ML difficulty (see below)
    bu_distribution=None,      # Business unit distribution dict
    include_hiring=False,      # Enable hiring simulation
    base_growth_rate=0.05,     # Base annual growth rate (5%)
    backfill_rate=0.85,        # Fraction of attrition to backfill (85%)
    bu_growth_rates=None,      # Per-BU growth rate overrides
)
```

**Returns:** Dictionary of pandas DataFrames

#### Noise Parameter for ML Difficulty

The `noise_std` parameter controls how predictable the attrition patterns are:

| noise_std | ML Accuracy | Use Case |
|-----------|-------------|----------|
| 0.1 | ~90%+ | Easy demos, teaching basic ML |
| 0.2 | ~80-85% | Realistic scenarios (default) |
| 0.3 | ~70-75% | Challenging ML problems |

### `HRDataGenerator` Class

For more control, use the class directly:

```python
from hr_data_generator import HRDataGenerator

generator = HRDataGenerator(seed=42)
data = generator.generate(
    n_employees=100,
    start_date="2020-01-01",
    end_date="2024-12-31"
)
```

## Output Tables

### `employee` (Hub Table)

Core employee master with one row per person.

| Column | Type | Description |
|--------|------|-------------|
| employee_id | STRING | Unique person ID (e.g., EMP000001) |
| first_name | STRING | First name |
| last_name | STRING | Last name |
| gender | STRING | male / female / na |
| birth_date | DATE | Date of birth |
| hire_date | DATE | Employment start date |
| employment_type | STRING | Full-time / Part-time / Contract |
| employment_status | STRING | Active / Terminated / Retired |
| location_id | STRING | FK to location table |
| manager_id | STRING | FK to employee (NULL for CEO) |
| termination_date | DATE | Date of termination (NULL if active) |
| termination_reason | STRING | Reason for leaving (NULL if active) |

### `employee_job_assignment` (Time-Variant)

Job placement history including promotions.

| Column | Type | Description |
|--------|------|-------------|
| employee_id | STRING | FK to employee |
| job_id | STRING | FK to job_role |
| job_title | STRING | Job title at time of assignment |
| job_family | STRING | Engineering / Sales / Corporate |
| job_level | STRING | IC / Manager / Director |
| seniority_level | INTEGER | 1 (junior) to 5 (director) |
| start_date | DATE | Assignment start |
| end_date | DATE | Assignment end (NULL if current) |

### `employee_org_assignment` (Time-Variant)

Organization placement history including transfers.

| Column | Type | Description |
|--------|------|-------------|
| employee_id | STRING | FK to employee |
| org_id | STRING | FK to organization_unit |
| org_name | STRING | Organization name |
| cost_center | STRING | Cost center code |
| business_unit | STRING | Corporate / Sales / Engineering |
| start_date | DATE | Assignment start |
| end_date | DATE | Assignment end (NULL if current) |

### `employee_compensation` (Time-Variant)

Salary and bonus history.

| Column | Type | Description |
|--------|------|-------------|
| employee_id | STRING | FK to employee |
| base_salary | FLOAT | Annual base salary (USD) |
| bonus_target_pct | FLOAT | Bonus target percentage |
| currency | STRING | Currency code (USD) |
| start_date | DATE | Effective date |
| end_date | DATE | End date (NULL if current) |
| change_reason | STRING | New Hire / Annual Merit / Promotion |

### `employee_performance` (Annual)

Annual performance review records.

| Column | Type | Description |
|--------|------|-------------|
| employee_id | STRING | FK to employee |
| review_period_year | INTEGER | Review year |
| review_date | DATE | Review date (Dec 15) |
| rating | INTEGER | 1-5 rating |
| rating_label | STRING | Needs Improvement to Outstanding |
| manager_id | STRING | Reviewing manager |

### Reference Tables

**`organization_unit`** - 35 departments across Engineering, Sales, and Corporate

**`job_role`** - 39 job roles with seniority levels 1-5

**`location`** - 44 APJ region locations with coordinates

## Data Generation Rules

### Seniority Distribution

| Level | Role Type | Percentage |
|-------|-----------|------------|
| 5 | Director | ~5% (min 1) |
| 4 | Manager/Staff | ~15% |
| 3 | Senior IC | ~25% |
| 2 | Mid IC | ~30% |
| 1 | Junior IC | ~25% |

### Age Ranges by Seniority

| Level | Age Range |
|-------|-----------|
| 5 | 45-65 years |
| 4 | 40-65 years |
| 3 | 30-60 years |
| 2 | 22-45 years |
| 1 | 21-40 years |

### Salary Ranges

| Level | Base Salary Range |
|-------|-------------------|
| 5 | $180,000 - $300,000 |
| 4 | $130,000 - $200,000 |
| 3 | $90,000 - $140,000 |
| 2 | $70,000 - $100,000 |
| 1 | $50,000 - $75,000 |

### Performance Rating Distribution

| Rating | Label | Distribution |
|--------|-------|--------------|
| 1 | Needs Improvement | 5% |
| 2 | Partially Meets | 15% |
| 3 | Meets Expectations | 50% |
| 4 | Exceeds Expectations | 25% |
| 5 | Outstanding | 5% |

### Manager Hierarchy Rules

- Exactly one CEO (null manager_id)
- Managers always have higher seniority than their direct reports
- Directors (level 5) report to CEO
- Managers (level 4) report to Directors
- Senior ICs (level 3) report to Managers
- Junior/Mid ICs (levels 1-2) report to Senior ICs or Managers

### Job-Org Alignment

Jobs are assigned to compatible organizations:
- Engineering jobs → Engineering business unit orgs
- Sales jobs → Sales business unit orgs
- Corporate jobs → Corporate business unit orgs

## Employee Attrition (ML Use Case)

The library simulates realistic employee turnover for **binary classification ML** tasks.

### Attrition Probability Model

```
P(leave) = base_rate × perf_factor × tenure_factor × emp_type_factor × seniority_factor × promotion_factor
```

### Factor Multipliers

| Factor | Values | Multipliers |
|--------|--------|-------------|
| **Performance** | 1 (Needs Improvement) | 2.5× (highest risk) |
| | 3 (Meets Expectations) | 1.0× (baseline) |
| | 5 (Outstanding) | 0.4× (lowest risk) |
| **Tenure** | < 1 year | 1.8× |
| | 2-5 years | 1.0× (baseline) |
| | 10+ years | 0.5× |
| **Employment Type** | Full-time | 1.0× |
| | Contract | 2.0× |
| | Part-time | 1.4× |
| **Seniority** | Level 1 (Junior) | 1.3× |
| | Level 3 (Senior) | 0.9× |
| | Level 5 (Director) | 0.5× |
| **Recent Promotion** | Yes | 0.4× |
| | No | 1.0× |

### Termination Reasons

**Voluntary:**
- Resignation - Career Opportunity
- Resignation - Personal Reasons
- Resignation - Relocation
- Retirement (age 55+ only, higher probability at 60+)

**Involuntary:**
- Termination - Performance (more likely for low performers)
- Termination - Policy Violation
- Layoff - Restructuring
- Layoff - Cost Reduction

### ML Features Enabled

The generated data supports these predictive features:
- `performance_rating`, `tenure_years`, `time_in_current_role`
- `salary_percentile`, `time_since_last_raise`, `recent_promotion`
- `employment_type`, `seniority_level`, `age`, `business_unit`

**Target variable:** `termination_date IS NOT NULL` (binary classification)

## Hiring Simulation (Workforce Dynamics)

When `include_hiring=True`, the library simulates realistic workforce growth alongside attrition.

### How It Works

Each simulation year:
1. **Growth hires** are calculated based on current headcount and growth rate
2. **Attrition** is applied (employees leave)
3. **Backfill hires** replace a fraction of departed employees
4. New employees are generated with realistic demographics

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `include_hiring` | `False` | Enable hiring simulation |
| `base_growth_rate` | `0.05` | 5% annual workforce growth |
| `backfill_rate` | `0.85` | Replace 85% of departures |
| `bu_growth_rates` | See below | Per-business-unit rates |

### Default Business Unit Growth Rates

```python
{
    "Engineering": 0.08,  # Tech grows faster
    "Sales": 0.05,        # Standard growth
    "Corporate": 0.02,    # Support functions grow slower
}
```

### New Hire Seniority Distribution

New hires skew junior (realistic hiring patterns):

| Level | Percentage |
|-------|------------|
| 1 (Junior) | 40% |
| 2 (Mid) | 30% |
| 3 (Senior) | 20% |
| 4 (Manager) | 8% |
| 5 (Director) | 2% |

### Example: Balanced Workforce Dynamics

```python
from hr_data_generator import generate_hr_data

# 10-year simulation with hiring and attrition
data = generate_hr_data(
    n_employees=100,
    seed=42,
    start_date="2015-01-01",
    end_date="2025-12-31",
    include_attrition=True,
    attrition_rate=0.12,
    include_hiring=True,
    base_growth_rate=0.05,
    backfill_rate=0.85,
)

employees = data['employee']
active = employees[employees['termination_date'].isna()]
print(f"Started with 100, now have {len(active)} active employees")
# Typical output: "Started with 100, now have 150+ active employees"
```

### Example: Preparing ML Dataset

```python
from hr_data_generator import generate_hr_data
import pandas as pd

data = generate_hr_data(n_employees=1000, seed=42)
employees = data['employee']

# Create target variable
employees['is_terminated'] = employees['termination_date'].notna().astype(int)

# Calculate tenure
employees['tenure_years'] = (
    pd.to_datetime('today') - pd.to_datetime(employees['hire_date'])
).dt.days / 365.25

print(f"Attrition rate: {employees['is_terminated'].mean():.1%}")
```

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=hr_data_generator
```

## Development Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"
```

## Design Notes

- `employee` is the **hub** table
- Org, job, compensation, performance are **time-variant satellites**
- Org assignment and job assignment are **separate by design**
- `start_date` / `end_date` enable **time-travel analytics and ML feature engineering**
- `location` is a reusable **dimension table**
- `seniority_level` on jobs helps enforce **plausible synthetic assignments**

## License

MIT

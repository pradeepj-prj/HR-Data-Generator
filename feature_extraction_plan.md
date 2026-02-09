# Feature Extraction Plan

## Overview

This module bridges the gap between the HR Data Generator's 8 raw tables (SuccessFactors-style hub + satellites) and the ML-ready feature matrix needed for attrition prediction. It implements pure SQL queries that transform raw tables into a **panel dataset** (one row per employee per observation year).

## Why Panel Data?

The attrition model in `attrition.py` processes employees **year by year** via `apply_attrition_for_year()`. Each year, it looks up that employee's current tenure, latest performance rating, current seniority, etc., and decides whether they leave. A panel dataset mirrors this exactly:

```
employee_id | observation_year | tenure_years | perf_rating | ... | left_this_year
EMP000001   | 2020             | 0.8          | NULL        | ... | 0
EMP000001   | 2021             | 1.8          | 3           | ... | 0
EMP000001   | 2022             | 2.8          | 4           | ... | 0
EMP000001   | 2023             | 3.8          | 3           | ... | 1  <-- departed
```

This produces ~N x Y rows (instead of just N), giving ML models significantly more training data and enabling temporal patterns.

## File Structure

```
scripts/features/
  01_create_feature_view.sql   -- Main: CREATE VIEW v_attrition_features
  02_create_feature_table.sql  -- Optional: materialize view into table
  03_verify_features.sql       -- Validation queries
  04_drop_features.sql         -- Cleanup script
```

## Feature Catalog (25 features + 2 identifiers + 1 target)

### Identifiers

| Column | Type | Description |
|--------|------|-------------|
| `employee_id` | VARCHAR | Employee identifier |
| `observation_year` | INTEGER | The year being observed |

### Core Attrition Model Features (5)

These match the 5 factor inputs in `attrition.py`:

| # | Feature | Type | Source Table | Matches attrition.py |
|---|---------|------|-------------|---------------------|
| 1 | `performance_rating` | INT 1-5, nullable | employee_performance | Lines 417-423: latest review where year < observation_year |
| 2 | `tenure_years` | NUMERIC | employee.hire_date | Line 409: `(year_end - hire_date).days / 365.25` |
| 3 | `employment_type` | VARCHAR | employee | Direct column lookup |
| 4 | `seniority_level` | INT 1-5 | employee_job_assignment | Lines 426-437: active assignment as of year-end |
| 5 | `had_recent_promotion` | BOOLEAN | employee_job_assignment | Lines 443-456: seniority increase in prior year window |

### Demographic Features (3)

| # | Feature | Type | Source |
|---|---------|------|--------|
| 6 | `age` | INT | employee.birth_date |
| 7 | `gender` | VARCHAR | employee |
| 8 | `country` | VARCHAR | location |

### Job History Features (4)

| # | Feature | Type | Description |
|---|---------|------|-------------|
| 9 | `job_level` | VARCHAR | IC/Manager/Director |
| 10 | `job_changes_count` | INT | Number of job changes up to observation year |
| 11 | `time_in_current_role_years` | NUMERIC | Time in current role as of year-end |
| 12 | `total_promotions` | INT | Count of seniority increases |

### Organization Features (3)

| # | Feature | Type | Description |
|---|---------|------|-------------|
| 13 | `business_unit` | VARCHAR | Engineering/Sales/Corporate |
| 14 | `org_changes_count` | INT | Number of org transfers |
| 15 | `cost_center` | VARCHAR | Current cost center |

### Compensation Features (4)

| # | Feature | Type | Description |
|---|---------|------|-------------|
| 16 | `current_salary` | NUMERIC | Base salary as of year-end |
| 17 | `salary_growth_pct` | NUMERIC | Growth from initial salary |
| 18 | `comp_ratio_in_role` | NUMERIC | Salary / avg salary for same seniority band |
| 19 | `bonus_target_pct` | NUMERIC | Bonus target percentage |

### Performance Features (4)

| # | Feature | Type | Description |
|---|---------|------|-------------|
| 20 | `avg_rating` | NUMERIC | Average of all prior ratings |
| 21 | `performance_trend` | INT | Latest rating minus second-latest |
| 22 | `had_low_rating` | BOOLEAN | Ever had rating <= 2 |
| 23 | `review_count` | INT | Number of prior reviews |

### Target Variable

| # | Column | Type | Description |
|---|--------|------|-------------|
| 24 | `left_this_year` | INT (0/1) | 1 if termination_date falls in observation_year |
| 25 | `termination_reason` | VARCHAR, nullable | Only populated in year of departure |

## Key Design Decisions

1. **reference_date = Dec 31 of observation_year** -- matches `attrition.py` line 393
2. **Performance reviews use `< observation_year`** -- reviews from the current year are excluded (they happen Dec 15, after the attrition decision)
3. **Recent promotion window: Jan 1 of (year-1) to Jan 1 of year** -- matches `attrition.py` lines 443-444
4. **Skip employees with < 90 days tenure** -- matches `attrition.py` line 412
5. **PostgreSQL-specific** -- uses `DISTINCT ON`, `generate_series`, `BOOL_OR`
6. **View + optional materialization** -- `v_attrition_features` is always-fresh; materialized table is opt-in

## Verification Strategy

The `03_verify_features.sql` script validates:
- Row count per employee matches active years
- Exactly one `left_this_year=1` per terminated employee
- No rows after termination year
- Feature ranges (tenure 0-50, seniority 1-5, rating 1-5, age 16-80)
- Tenure monotonically increases per employee
- Distribution checks (rating ~5/15/50/25/5%, comp_ratio ~1.0)

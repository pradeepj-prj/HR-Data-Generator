# HR Data Generator - Data Model

This document describes the data model used by the HR Data Generator, which implements a **Data Vault-inspired hub-and-satellite architecture** similar to SAP SuccessFactors.

## Overview

The generator produces **8 interconnected tables** designed for:
- Time-travel analytics ("What was this employee's salary on date X?")
- ML feature engineering (tenure calculations, promotion velocity)
- Complete audit trails with full change history

## Table Summary

| Table | Type | Description |
|-------|------|-------------|
| `employee` | Hub | Core entity - one row per person |
| `employee_job_assignment` | Satellite | Time-variant job/promotion history |
| `employee_org_assignment` | Satellite | Time-variant department/transfer history |
| `employee_compensation` | Satellite | Time-variant salary/raise history |
| `employee_performance` | Satellite | Annual performance review snapshots |
| `organization_unit` | Dimension | Org hierarchy (35 departments) |
| `job_role` | Dimension | Job catalog (39 roles) |
| `location` | Dimension | Geographic locations (44 APJ cities) |

## Entity Relationship Diagram

```
                         ┌─────────────────┐
                         │    location     │
                         │   (44 cities)   │
                         └────────┬────────┘
                                  │ FK: location_id
     ┌────────────────────────────┼────────────────────────┐
     │                            ▼                        │
     │                 ┌─────────────────────┐             │
     │                 │      employee       │◄────────────┤
     │                 │    (Hub Table)      │  manager_id │
     │                 │                     │  (self-ref) │
     │                 └──────────┬──────────┘             │
     │                            │                        │
     │              employee_id   │   (FK to all satellites)
     │     ┌──────────┬───────────┼───────────┬──────────┐ │
     │     ▼          ▼           ▼           ▼          │ │
     │ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │ │
     │ │  job_  │ │  org_  │ │ comp-  │ │ perfor-│       │ │
     │ │ assign │ │ assign │ │ ensatn │ │ mance  │       │ │
     │ └───┬────┘ └───┬────┘ └────────┘ └────────┘       │ │
     │     │          │                                   │ │
     │     ▼          ▼                                   │ │
     │ ┌────────┐ ┌────────┐                              │ │
     │ │job_role│ │org_unit│◄─────────────────────────────┘ │
     │ │ (39)   │ │ (35)   │  parent_org_id (self-ref)      │
     └─┴────────┴─┴────────┴────────────────────────────────┘
```

## Hub Table: `employee`

The central entity containing one row per person with static identity attributes.

| Column | Type | Description |
|--------|------|-------------|
| `employee_id` | STRING | Primary key (e.g., "EMP000001") |
| `first_name` | STRING | First name |
| `last_name` | STRING | Last name |
| `gender` | STRING | "male" / "female" / "na" |
| `birth_date` | DATE | Date of birth |
| `hire_date` | DATE | Employment start date |
| `employment_type` | STRING | "Full-time" / "Part-time" / "Contract" |
| `employment_status` | STRING | "Active" / "Terminated" / "Retired" |
| `location_id` | STRING | FK to `location` |
| `manager_id` | STRING | FK to `employee` (self-reference, NULL for CEO) |
| `termination_date` | DATE | NULL if active, date if terminated |
| `termination_reason` | STRING | NULL if active, reason if terminated |

**Business Rules:**
- Exactly one CEO has `manager_id = NULL`
- Managers must have higher seniority than their direct reports
- No circular references in the management hierarchy

## Time-Variant Satellite Tables

Satellites track changes over time using the **SCD Type 2** (Slowly Changing Dimension) pattern.

### How start_date/end_date Works

```
employee_id | job_title              | seniority | start_date | end_date
------------|------------------------|-----------|------------|------------
EMP000001   | Software Engineer I    | 1         | 2019-03-15 | 2020-04-30
EMP000001   | Software Engineer II   | 2         | 2020-05-01 | 2022-06-14
EMP000001   | Senior Software Eng.   | 3         | 2022-06-15 | NULL
```

**Key Rules:**
- `end_date = NULL` indicates the current/active record
- Exactly one active record per employee per satellite
- No overlapping date ranges for the same employee
- When an employee terminates, all satellite records get `end_date = termination_date`

### `employee_job_assignment`

Tracks job changes and promotions.

| Column | Type | Description |
|--------|------|-------------|
| `employee_id` | STRING | FK to `employee` |
| `job_id` | STRING | FK to `job_role` |
| `job_title` | STRING | Denormalized job title |
| `seniority_level` | INT | 1 (Junior) to 5 (Director) |
| `start_date` | DATE | When this assignment started |
| `end_date` | DATE | NULL if current, date if ended |

### `employee_org_assignment`

Tracks department transfers and reorganizations.

| Column | Type | Description |
|--------|------|-------------|
| `employee_id` | STRING | FK to `employee` |
| `org_unit_id` | STRING | FK to `organization_unit` |
| `start_date` | DATE | When this assignment started |
| `end_date` | DATE | NULL if current, date if ended |

### `employee_compensation`

Tracks salary changes, raises, and bonuses.

| Column | Type | Description |
|--------|------|-------------|
| `employee_id` | STRING | FK to `employee` |
| `annual_salary` | FLOAT | Annual salary amount |
| `currency` | STRING | Currency code (default: "USD") |
| `start_date` | DATE | When this salary started |
| `end_date` | DATE | NULL if current, date if ended |

### `employee_performance`

Annual performance review snapshots (not continuous like other satellites).

| Column | Type | Description |
|--------|------|-------------|
| `employee_id` | STRING | FK to `employee` |
| `review_period_year` | INT | Year of review |
| `review_date` | DATE | Date review was conducted (December 15) |
| `rating` | INT | 1-5 rating scale |
| `rating_label` | STRING | "Needs Improvement" to "Outstanding" |
| `manager_id` | STRING | FK to `employee` (reviewing manager) |

**Rating Distribution:**
- 1 (Needs Improvement): 5%
- 2 (Partially Meets): 15%
- 3 (Meets Expectations): 50%
- 4 (Exceeds Expectations): 25%
- 5 (Outstanding): 5%

## Reference/Dimension Tables

### `organization_unit`

Hierarchical organization structure.

| Column | Type | Description |
|--------|------|-------------|
| `org_id` | STRING | Primary key |
| `org_name` | STRING | Department name |
| `parent_org_id` | STRING | FK to self (NULL for root) |
| `cost_center` | STRING | Cost center code |
| `business_unit` | STRING | "Engineering" / "Sales" / "Corporate" |

### `job_role`

Job catalog with seniority levels.

| Column | Type | Description |
|--------|------|-------------|
| `job_id` | STRING | Primary key |
| `job_title` | STRING | Job title |
| `job_family` | STRING | "Engineering" / "Sales" / "Corporate" |
| `job_level` | STRING | "IC" / "Manager" / "Director" |
| `seniority_level` | INT | 1 (Junior) to 5 (Director) |

### `location`

Geographic locations in APJ region.

| Column | Type | Description |
|--------|------|-------------|
| `location_id` | STRING | Primary key |
| `city` | STRING | City name |
| `country` | STRING | Country name |
| `region` | STRING | Region (APJ) |
| `latitude` | FLOAT | Geographic latitude |
| `longitude` | FLOAT | Geographic longitude |

## Why This Pattern?

### Why Separate Job and Org Assignments?

This mirrors real SuccessFactors design where job and org are **independently changeable**:
- **Transfer without promotion**: Move to new department, keep same job level
- **Promotion without transfer**: Get promoted but stay in same department
- **Reorganizations**: Entire teams change orgs but keep their jobs

### Why Not 3NF (Normalized)?

3NF would require complex multi-union queries to reconstruct history. Current design uses simple date-range queries:

```sql
WHERE start_date <= @query_date
  AND (end_date IS NULL OR end_date >= @query_date)
```

### Why Not Pure Star Schema?

Star schema would need one row per employee per day/month (massive data explosion). Current design only stores records when changes occur — efficient for slowly-changing data.

## Common Query Patterns

### Get Current State for an Employee

```sql
SELECT e.first_name, e.last_name,
       j.job_title, j.seniority_level,
       o.org_name, c.annual_salary
FROM employee e
LEFT JOIN employee_job_assignment j
  ON e.employee_id = j.employee_id AND j.end_date IS NULL
LEFT JOIN employee_org_assignment o
  ON e.employee_id = o.employee_id AND o.end_date IS NULL
LEFT JOIN employee_compensation c
  ON e.employee_id = c.employee_id AND c.end_date IS NULL
WHERE e.employee_id = 'EMP000001';
```

### Time-Travel Query (Point-in-Time)

```sql
-- What was the employee's situation on June 1, 2022?
SELECT e.first_name, e.last_name,
       j.job_title, c.annual_salary
FROM employee e
JOIN employee_job_assignment j ON e.employee_id = j.employee_id
  AND '2022-06-01' BETWEEN j.start_date AND COALESCE(j.end_date, '9999-12-31')
JOIN employee_compensation c ON e.employee_id = c.employee_id
  AND '2022-06-01' BETWEEN c.start_date AND COALESCE(c.end_date, '9999-12-31')
WHERE e.employee_id = 'EMP000001';
```

### Calculate Tenure in Current Role

```sql
SELECT employee_id, job_title,
       DATEDIFF(day, start_date, CURRENT_DATE) / 365.25 AS years_in_role
FROM employee_job_assignment
WHERE end_date IS NULL;
```

### Count Promotions per Employee

```sql
SELECT employee_id, COUNT(*) - 1 AS promotions
FROM employee_job_assignment
GROUP BY employee_id
HAVING COUNT(*) > 1;
```

## ML Feature Engineering Examples

```python
import pandas as pd
from datetime import date

# Load generated data
data = generate_hr_data(n_employees=1000, seed=42)

# Calculate tenure
employees = data['employee']
employees['tenure_years'] = (
    (pd.Timestamp.today() - pd.to_datetime(employees['hire_date'])).dt.days / 365.25
)

# Get current seniority level
current_jobs = data['employee_job_assignment'][
    data['employee_job_assignment']['end_date'].isna()
]

# Get latest performance rating
latest_perf = data['employee_performance'].sort_values('review_date').groupby('employee_id').tail(1)

# Count promotions (number of job changes)
promo_count = data['employee_job_assignment'].groupby('employee_id').size() - 1

# Merge features for ML
features = employees.merge(current_jobs[['employee_id', 'seniority_level']], on='employee_id')
features = features.merge(latest_perf[['employee_id', 'rating']], on='employee_id', how='left')
features['promotion_count'] = features['employee_id'].map(promo_count).fillna(0)
```

## Data Integrity Guarantees

The generator enforces:
1. **Referential integrity**: All foreign keys point to valid records
2. **Hierarchy validation**: No circular manager references, proper seniority ordering
3. **Temporal consistency**: No overlapping date ranges, proper record closure on termination
4. **Business unit alignment**: Job family matches organization business unit

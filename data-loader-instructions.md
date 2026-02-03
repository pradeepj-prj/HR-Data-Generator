# HR Data Loader - Instructions for Local Agent

## Objective

Create a Python script that uses the existing hr-data-generator library to generate HR data and load it directly into a remote PostgreSQL database using psycopg2.

## Database Connection

| Property | Value |
|----------|-------|
| Host | 13.228.165.215 |
| Port | 5432 |
| Database | hr_data |
| Username | hr_app |
| Password | Retrieve from AWS Secrets Manager or environment variable `HR_DB_PASSWORD` |

**Connection approach:**
- Use `psycopg2` for database connectivity
- Read password from environment variable, never hardcode
- Use connection pooling if generating large datasets

```python
import os
import psycopg2

conn = psycopg2.connect(
    host="13.228.165.215",
    port=5432,
    database="hr_data",
    user="hr_app",
    password=os.environ.get("HR_DB_PASSWORD")
)
```

---

## Database Schema

The database has 8 tables organized as:

### Reference/Dimension Tables (load first, no dependencies)

**1. location**
| Column | Type | Constraints |
|--------|------|-------------|
| location_id | VARCHAR(10) | PRIMARY KEY |
| city | VARCHAR(100) | NOT NULL |
| country | VARCHAR(100) | NOT NULL |
| region | VARCHAR(50) | NOT NULL, DEFAULT 'APJ' |
| latitude | DECIMAL(9,6) | |
| longitude | DECIMAL(9,6) | |

**2. organization_unit**
| Column | Type | Constraints |
|--------|------|-------------|
| org_id | VARCHAR(10) | PRIMARY KEY |
| org_name | VARCHAR(200) | NOT NULL |
| parent_org_id | VARCHAR(10) | FK → organization_unit(org_id), nullable |
| cost_center | VARCHAR(20) | |
| business_unit | VARCHAR(50) | NOT NULL, CHECK IN ('Engineering', 'Sales', 'Corporate') |

*Note: Self-referencing table. Insert parent orgs before children.*

**3. job_role**
| Column | Type | Constraints |
|--------|------|-------------|
| job_id | VARCHAR(10) | PRIMARY KEY |
| job_title | VARCHAR(200) | NOT NULL |
| job_family | VARCHAR(50) | NOT NULL, CHECK IN ('Engineering', 'Sales', 'Corporate') |
| job_level | VARCHAR(20) | NOT NULL, CHECK IN ('IC', 'Manager', 'Director') |
| seniority_level | INTEGER | NOT NULL, CHECK 1-5 |

### Hub Table

**4. employee**
| Column | Type | Constraints |
|--------|------|-------------|
| employee_id | VARCHAR(20) | PRIMARY KEY |
| first_name | VARCHAR(100) | NOT NULL |
| last_name | VARCHAR(100) | NOT NULL |
| gender | VARCHAR(10) | CHECK IN ('male', 'female', 'na') or NULL |
| birth_date | DATE | NOT NULL |
| hire_date | DATE | NOT NULL, must be >= birth_date + 16 years |
| employment_type | VARCHAR(20) | NOT NULL, CHECK IN ('Full-time', 'Part-time', 'Contract') |
| employment_status | VARCHAR(20) | NOT NULL, DEFAULT 'Active', CHECK IN ('Active', 'Terminated', 'Retired') |
| location_id | VARCHAR(10) | NOT NULL, FK → location(location_id) |
| manager_id | VARCHAR(20) | FK → employee(employee_id), nullable, cannot equal employee_id |
| termination_date | DATE | NULL if Active, NOT NULL if Terminated/Retired |
| termination_reason | VARCHAR(200) | |

*Note: Self-referencing via manager_id. Insert managers before their reports, or insert all with manager_id=NULL first, then update manager_id.*

### Time-Variant Satellite Tables (SCD Type 2)

**5. employee_job_assignment**
| Column | Type | Constraints |
|--------|------|-------------|
| id | SERIAL | PRIMARY KEY (auto-generated) |
| employee_id | VARCHAR(20) | NOT NULL, FK → employee(employee_id) |
| job_id | VARCHAR(10) | NOT NULL, FK → job_role(job_id) |
| job_title | VARCHAR(200) | NOT NULL |
| job_family | VARCHAR(50) | NOT NULL |
| job_level | VARCHAR(20) | NOT NULL |
| seniority_level | INTEGER | NOT NULL, CHECK 1-5 |
| start_date | DATE | NOT NULL |
| end_date | DATE | NULL = current record |

**6. employee_org_assignment**
| Column | Type | Constraints |
|--------|------|-------------|
| id | SERIAL | PRIMARY KEY (auto-generated) |
| employee_id | VARCHAR(20) | NOT NULL, FK → employee(employee_id) |
| org_id | VARCHAR(10) | NOT NULL, FK → organization_unit(org_id) |
| org_name | VARCHAR(200) | NOT NULL |
| cost_center | VARCHAR(20) | |
| business_unit | VARCHAR(50) | NOT NULL, CHECK IN ('Engineering', 'Sales', 'Corporate') |
| start_date | DATE | NOT NULL |
| end_date | DATE | NULL = current record |

**7. employee_compensation**
| Column | Type | Constraints |
|--------|------|-------------|
| id | SERIAL | PRIMARY KEY (auto-generated) |
| employee_id | VARCHAR(20) | NOT NULL, FK → employee(employee_id) |
| base_salary | DECIMAL(12,2) | NOT NULL, must be > 0 |
| bonus_target_pct | DECIMAL(5,2) | NOT NULL, DEFAULT 0, CHECK 0-100 |
| currency | VARCHAR(3) | NOT NULL, DEFAULT 'USD' |
| start_date | DATE | NOT NULL |
| end_date | DATE | NULL = current record |
| change_reason | VARCHAR(50) | CHECK IN ('New Hire', 'Annual Merit', 'Promotion') or NULL |

**8. employee_performance**
| Column | Type | Constraints |
|--------|------|-------------|
| id | SERIAL | PRIMARY KEY (auto-generated) |
| employee_id | VARCHAR(20) | NOT NULL, FK → employee(employee_id) |
| review_period_year | INTEGER | NOT NULL, CHECK 2000-2100 |
| review_date | DATE | NOT NULL |
| rating | INTEGER | NOT NULL, CHECK 1-5 |
| rating_label | VARCHAR(50) | NOT NULL |
| manager_id | VARCHAR(20) | FK → employee(employee_id) |

*Unique constraint: (employee_id, review_period_year) - one review per employee per year*

---

## Required Load Order

Due to foreign key constraints, data MUST be loaded in this order:

```
1. location
2. organization_unit      (parents before children)
3. job_role
4. employee               (managers before direct reports)
5. employee_job_assignment
6. employee_org_assignment
7. employee_compensation
8. employee_performance
```

---

## Implementation Requirements

### 1. Bulk Insert Performance

Use `psycopg2.extras.execute_values` for bulk inserts:

```python
from psycopg2.extras import execute_values

execute_values(
    cursor,
    "INSERT INTO location (location_id, city, country, region, latitude, longitude) VALUES %s",
    list_of_tuples,
    page_size=1000
)
```

### 2. Handle Self-Referencing Tables

**organization_unit:** Sort by hierarchy level, insert parents first.

**employee:** Two approaches:
- Option A: Topological sort by manager hierarchy, insert in order
- Option B: Insert all employees with `manager_id=NULL`, then run UPDATE statements to set manager_id

### 3. Transaction Management

Wrap the entire load in a transaction for atomicity:

```python
try:
    # Load all tables in order
    conn.commit()
except Exception as e:
    conn.rollback()
    raise
```

### 4. Do NOT Include

- `id` column for SERIAL primary keys (auto-generated)
- `created_at` / `updated_at` columns (use database defaults)

### 5. Verification Queries

After loading, verify counts:

```python
tables = ['location', 'organization_unit', 'job_role', 'employee',
          'employee_job_assignment', 'employee_org_assignment',
          'employee_compensation', 'employee_performance']

for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"{table}: {cursor.fetchone()[0]} rows")
```

---

## Expected Output

The script should:
1. Connect to the remote database
2. Generate data using the hr-data-generator library
3. Insert data in the correct order
4. Print row counts for verification
5. Handle errors with rollback
6. Close connections cleanly

---

## Testing Connection

Before running the full load, test connectivity:

```python
cursor.execute("SELECT version();")
print(cursor.fetchone())
```

Expected: PostgreSQL 16.x response

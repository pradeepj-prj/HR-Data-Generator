# Mock SuccessFactors-Style HR Database generator
**Table Reference (BDC / Datasphere + HANA Cloud)**

This document lists the tables used in the mock HR dataset (SuccessFactors-style) designed for learning and demos with **SAP HANA Cloud**, **BDC/Datasphere**, and **AI use cases**.

The schema is:
- Realistic enough for presales demos
- Simple enough to generate synthetically
- Explicitly time-variant where it matters

---

## Design Notes

- `employee` is the **hub** table.
- Org, job, compensation, performance are **time-variant satellites**.
- Org assignment and job assignment are **separate by design**.
- `start_date` / `end_date` enable **time-travel analytics and ML feature engineering**.
- `location` is a reusable **dimension table**.
- `seniority_level` on jobs helps enforce **plausible synthetic assignments**.

---

## Table Catalog

---

## `employee`
**Purpose:** Core employee master (one row per person)  
**Primary key:** `employee_id`

| Column | Type | Description |
|---|---|---|
| employee_id | STRING | Unique person ID |
| manager_id | STRING | Manager (employee_id); NULL if top-level |
| hire_date | DATE | Start date |
| termination_date | DATE | NULL if active |
| employment_status | STRING | Active / Terminated / Leave |
| employment_type | STRING | Full-time / Part-time / Contract |
| gender | STRING | Optional |
| birth_date | DATE | Preferred over age |
| country | STRING | Country/territory |
| region | STRING | APJ / EMEA / AMER |
| location_id | STRING | FK → location.location_id |

---

## `organization_unit`
**Purpose:** Organizational hierarchy (departments, cost centers, BUs)  
**Primary key:** `org_id`

| Column | Type | Description |
|---|---|---|
| org_id | STRING | Org unit ID |
| org_name | STRING | Department name |
| parent_org_id | STRING | Parent org_id (hierarchy) |
| cost_center | STRING | Finance hook |
| business_unit | STRING | Corporate / Sales / Engineering |

---

## `employee_org_assignment`
**Purpose:** Time-variant org placement (transfers, restructures)  
**Primary key:** `(employee_id, start_date)`

| Column | Type | Description |
|---|---|---|
| employee_id | STRING | FK → employee.employee_id |
| org_id | STRING | FK → organization_unit.org_id |
| start_date | DATE | Validity start |
| end_date | DATE | Validity end (NULL if current) |
| is_primary_assignment | STRING | Y/N |

---

## `job_role`
**Purpose:** Standardized enterprise job catalog  
**Primary key:** `job_id`

| Column | Type | Description |
|---|---|---|
| job_id | STRING | Job code |
| job_title | STRING | Title |
| job_family | STRING | Engineering / Sales / Corporate |
| job_level | STRING | IC / Manager / Director |
| seniority_level | INTEGER | 1 (junior) → 5 (very senior) |

---

## `employee_job_assignment`
**Purpose:** Time-variant job placement (promotions, lateral moves)  
**Primary key:** `(employee_id, start_date)`

| Column | Type | Description |
|---|---|---|
| employee_id | STRING | FK → employee.employee_id |
| job_id | STRING | FK → job_role.job_id |
| start_date | DATE | Validity start |
| end_date | DATE | Validity end (NULL if current) |
| is_pri_



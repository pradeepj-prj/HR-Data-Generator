-- ============================================================================
-- HR Data Generator - PostgreSQL Schema
-- ============================================================================
-- This schema supports the SuccessFactors-style HR data model with:
--   - Hub table (employee) for core employee data
--   - Time-variant satellites for historical tracking (SCD Type 2)
--   - Reference/dimension tables for lookups
--
-- Generated for: HR Data Generator Project
-- Compatible with: PostgreSQL 12+
-- ============================================================================

-- Drop tables if they exist (in reverse dependency order)
DROP TABLE IF EXISTS employee_performance CASCADE;
DROP TABLE IF EXISTS employee_compensation CASCADE;
DROP TABLE IF EXISTS employee_org_assignment CASCADE;
DROP TABLE IF EXISTS employee_job_assignment CASCADE;
DROP TABLE IF EXISTS employee CASCADE;
DROP TABLE IF EXISTS job_role CASCADE;
DROP TABLE IF EXISTS organization_unit CASCADE;
DROP TABLE IF EXISTS location CASCADE;

-- ============================================================================
-- REFERENCE/DIMENSION TABLES
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Location: Geographic locations (44 cities in APJ region)
-- ----------------------------------------------------------------------------
CREATE TABLE location (
    location_id     VARCHAR(10)     PRIMARY KEY,
    city            VARCHAR(100)    NOT NULL,
    country         VARCHAR(100)    NOT NULL,
    region          VARCHAR(50)     NOT NULL DEFAULT 'APJ',
    latitude        DECIMAL(9,6),
    longitude       DECIMAL(9,6),

    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE location IS 'Geographic locations for employee assignments (APJ region)';
COMMENT ON COLUMN location.location_id IS 'Primary key (e.g., SG01, MLY23)';
COMMENT ON COLUMN location.region IS 'Geographic region - all records are APJ';

-- ----------------------------------------------------------------------------
-- Organization Unit: Hierarchical department structure (45 departments)
-- ----------------------------------------------------------------------------
CREATE TABLE organization_unit (
    org_id          VARCHAR(10)     PRIMARY KEY,
    org_name        VARCHAR(200)    NOT NULL,
    parent_org_id   VARCHAR(10)     REFERENCES organization_unit(org_id),
    cost_center     VARCHAR(20),
    business_unit   VARCHAR(50)     NOT NULL,

    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_org_business_unit
        CHECK (business_unit IN ('Engineering', 'Sales', 'Corporate'))
);

COMMENT ON TABLE organization_unit IS 'Hierarchical organization structure';
COMMENT ON COLUMN organization_unit.parent_org_id IS 'Self-reference for hierarchy (NULL for root)';
COMMENT ON COLUMN organization_unit.business_unit IS 'Top-level business unit classification';

CREATE INDEX idx_org_parent ON organization_unit(parent_org_id);
CREATE INDEX idx_org_business_unit ON organization_unit(business_unit);

-- ----------------------------------------------------------------------------
-- Job Role: Job catalog (46 roles across three business units)
-- ----------------------------------------------------------------------------
CREATE TABLE job_role (
    job_id          VARCHAR(10)     PRIMARY KEY,
    job_title       VARCHAR(200)    NOT NULL,
    job_family      VARCHAR(50)     NOT NULL,
    job_level       VARCHAR(20)     NOT NULL,
    seniority_level INTEGER         NOT NULL,

    created_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_job_family
        CHECK (job_family IN ('Engineering', 'Sales', 'Corporate')),
    CONSTRAINT chk_job_level
        CHECK (job_level IN ('IC', 'Manager', 'Director')),
    CONSTRAINT chk_seniority_level
        CHECK (seniority_level BETWEEN 1 AND 5)
);

COMMENT ON TABLE job_role IS 'Job catalog with titles, families, and seniority levels';
COMMENT ON COLUMN job_role.job_level IS 'IC=Individual Contributor, Manager, Director';
COMMENT ON COLUMN job_role.seniority_level IS '1=Junior, 2=Mid, 3=Senior, 4=Staff/Manager, 5=Director';

CREATE INDEX idx_job_family ON job_role(job_family);
CREATE INDEX idx_job_seniority ON job_role(seniority_level);

-- ============================================================================
-- HUB TABLE
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Employee: Central hub table with one row per person
-- ----------------------------------------------------------------------------
CREATE TABLE employee (
    employee_id         VARCHAR(20)     PRIMARY KEY,
    first_name          VARCHAR(100)    NOT NULL,
    last_name           VARCHAR(100)    NOT NULL,
    gender              VARCHAR(10),
    birth_date          DATE            NOT NULL,
    hire_date           DATE            NOT NULL,
    employment_type     VARCHAR(20)     NOT NULL,
    employment_status   VARCHAR(20)     NOT NULL DEFAULT 'Active',
    location_id         VARCHAR(10)     NOT NULL REFERENCES location(location_id),
    manager_id          VARCHAR(20)     REFERENCES employee(employee_id),
    termination_date    DATE,
    termination_reason  VARCHAR(200),

    created_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_emp_gender
        CHECK (gender IN ('male', 'female', 'na') OR gender IS NULL),
    CONSTRAINT chk_emp_type
        CHECK (employment_type IN ('Full-time', 'Part-time', 'Contract')),
    CONSTRAINT chk_emp_status
        CHECK (employment_status IN ('Active', 'Terminated', 'Retired')),
    CONSTRAINT chk_emp_no_self_manager
        CHECK (manager_id IS NULL OR manager_id != employee_id),
    CONSTRAINT chk_emp_termination_consistency
        CHECK (
            (employment_status = 'Active' AND termination_date IS NULL) OR
            (employment_status != 'Active' AND termination_date IS NOT NULL)
        ),
    CONSTRAINT chk_emp_dates
        CHECK (hire_date >= birth_date + INTERVAL '16 years')
);

COMMENT ON TABLE employee IS 'Hub table: one row per employee with core demographics';
COMMENT ON COLUMN employee.employee_id IS 'Unique identifier (e.g., EMP000001)';
COMMENT ON COLUMN employee.manager_id IS 'Self-reference to manager (NULL for CEO)';
COMMENT ON COLUMN employee.termination_date IS 'NULL if active; populated when employee departs';

CREATE INDEX idx_emp_manager ON employee(manager_id);
CREATE INDEX idx_emp_location ON employee(location_id);
CREATE INDEX idx_emp_status ON employee(employment_status);
CREATE INDEX idx_emp_hire_date ON employee(hire_date);
CREATE INDEX idx_emp_name ON employee(last_name, first_name);

-- ============================================================================
-- TIME-VARIANT SATELLITE TABLES (SCD Type 2)
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Employee Job Assignment: Tracks job changes and promotions over time
-- ----------------------------------------------------------------------------
CREATE TABLE employee_job_assignment (
    id                  SERIAL          PRIMARY KEY,
    employee_id         VARCHAR(20)     NOT NULL REFERENCES employee(employee_id) ON DELETE CASCADE,
    job_id              VARCHAR(10)     NOT NULL REFERENCES job_role(job_id),
    job_title           VARCHAR(200)    NOT NULL,
    job_family          VARCHAR(50)     NOT NULL,
    job_level           VARCHAR(20)     NOT NULL,
    seniority_level     INTEGER         NOT NULL,
    start_date          DATE            NOT NULL,
    end_date            DATE,

    created_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_job_asgn_dates
        CHECK (end_date IS NULL OR end_date >= start_date),
    CONSTRAINT chk_job_asgn_seniority
        CHECK (seniority_level BETWEEN 1 AND 5)
);

COMMENT ON TABLE employee_job_assignment IS 'Time-variant: tracks job history with SCD Type 2';
COMMENT ON COLUMN employee_job_assignment.end_date IS 'NULL indicates current/active record';

CREATE INDEX idx_job_asgn_employee ON employee_job_assignment(employee_id);
CREATE INDEX idx_job_asgn_job ON employee_job_assignment(job_id);
CREATE INDEX idx_job_asgn_current ON employee_job_assignment(employee_id) WHERE end_date IS NULL;
CREATE INDEX idx_job_asgn_dates ON employee_job_assignment(start_date, end_date);

-- ----------------------------------------------------------------------------
-- Employee Org Assignment: Tracks department transfers
-- ----------------------------------------------------------------------------
CREATE TABLE employee_org_assignment (
    id                  SERIAL          PRIMARY KEY,
    employee_id         VARCHAR(20)     NOT NULL REFERENCES employee(employee_id) ON DELETE CASCADE,
    org_id              VARCHAR(10)     NOT NULL REFERENCES organization_unit(org_id),
    org_name            VARCHAR(200)    NOT NULL,
    cost_center         VARCHAR(20),
    business_unit       VARCHAR(50)     NOT NULL,
    start_date          DATE            NOT NULL,
    end_date            DATE,

    created_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_org_asgn_dates
        CHECK (end_date IS NULL OR end_date >= start_date),
    CONSTRAINT chk_org_asgn_bu
        CHECK (business_unit IN ('Engineering', 'Sales', 'Corporate'))
);

COMMENT ON TABLE employee_org_assignment IS 'Time-variant: tracks org/department history';
COMMENT ON COLUMN employee_org_assignment.end_date IS 'NULL indicates current/active record';

CREATE INDEX idx_org_asgn_employee ON employee_org_assignment(employee_id);
CREATE INDEX idx_org_asgn_org ON employee_org_assignment(org_id);
CREATE INDEX idx_org_asgn_current ON employee_org_assignment(employee_id) WHERE end_date IS NULL;
CREATE INDEX idx_org_asgn_bu ON employee_org_assignment(business_unit);

-- ----------------------------------------------------------------------------
-- Employee Compensation: Tracks salary changes over time
-- ----------------------------------------------------------------------------
CREATE TABLE employee_compensation (
    id                  SERIAL          PRIMARY KEY,
    employee_id         VARCHAR(20)     NOT NULL REFERENCES employee(employee_id) ON DELETE CASCADE,
    base_salary         DECIMAL(12,2)   NOT NULL,
    bonus_target_pct    DECIMAL(5,2)    NOT NULL DEFAULT 0,
    currency            VARCHAR(3)      NOT NULL DEFAULT 'USD',
    start_date          DATE            NOT NULL,
    end_date            DATE,
    change_reason       VARCHAR(50),

    created_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_comp_dates
        CHECK (end_date IS NULL OR end_date >= start_date),
    CONSTRAINT chk_comp_salary
        CHECK (base_salary > 0),
    CONSTRAINT chk_comp_bonus
        CHECK (bonus_target_pct >= 0 AND bonus_target_pct <= 100),
    CONSTRAINT chk_comp_reason
        CHECK (change_reason IN ('New Hire', 'Annual Merit', 'Promotion') OR change_reason IS NULL)
);

COMMENT ON TABLE employee_compensation IS 'Time-variant: tracks compensation history';
COMMENT ON COLUMN employee_compensation.bonus_target_pct IS 'Target bonus as percentage of base salary';
COMMENT ON COLUMN employee_compensation.end_date IS 'NULL indicates current/active record';

CREATE INDEX idx_comp_employee ON employee_compensation(employee_id);
CREATE INDEX idx_comp_current ON employee_compensation(employee_id) WHERE end_date IS NULL;
CREATE INDEX idx_comp_dates ON employee_compensation(start_date, end_date);

-- ----------------------------------------------------------------------------
-- Employee Performance: Annual performance review records
-- ----------------------------------------------------------------------------
CREATE TABLE employee_performance (
    id                  SERIAL          PRIMARY KEY,
    employee_id         VARCHAR(20)     NOT NULL REFERENCES employee(employee_id) ON DELETE CASCADE,
    review_period_year  INTEGER         NOT NULL,
    review_date         DATE            NOT NULL,
    rating              INTEGER         NOT NULL,
    rating_label        VARCHAR(50)     NOT NULL,
    manager_id          VARCHAR(20)     REFERENCES employee(employee_id),

    created_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_perf_rating
        CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT chk_perf_year
        CHECK (review_period_year >= 2000 AND review_period_year <= 2100),
    CONSTRAINT uq_perf_employee_year
        UNIQUE (employee_id, review_period_year)
);

COMMENT ON TABLE employee_performance IS 'Annual performance reviews (one per employee per year)';
COMMENT ON COLUMN employee_performance.rating IS '1=Needs Improvement, 2=Partially Meets, 3=Meets, 4=Exceeds, 5=Outstanding';
COMMENT ON COLUMN employee_performance.manager_id IS 'Manager who conducted the review';

CREATE INDEX idx_perf_employee ON employee_performance(employee_id);
CREATE INDEX idx_perf_year ON employee_performance(review_period_year);
CREATE INDEX idx_perf_rating ON employee_performance(rating);
CREATE INDEX idx_perf_manager ON employee_performance(manager_id);

-- ============================================================================
-- USEFUL VIEWS
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Current Employee State: Denormalized view of active employee data
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_employee_current AS
SELECT
    e.employee_id,
    e.first_name,
    e.last_name,
    e.first_name || ' ' || e.last_name AS full_name,
    e.gender,
    e.birth_date,
    EXTRACT(YEAR FROM AGE(e.birth_date))::INTEGER AS age,
    e.hire_date,
    ROUND(EXTRACT(EPOCH FROM AGE(e.hire_date)) / (365.25 * 24 * 60 * 60), 2) AS tenure_years,
    e.employment_type,
    e.employment_status,
    e.termination_date,
    e.termination_reason,

    -- Location
    l.location_id,
    l.city,
    l.country,

    -- Manager
    e.manager_id,
    m.first_name || ' ' || m.last_name AS manager_name,

    -- Current Job
    ja.job_id,
    ja.job_title,
    ja.job_family,
    ja.job_level,
    ja.seniority_level,
    ja.start_date AS job_start_date,

    -- Current Org
    oa.org_id,
    oa.org_name,
    oa.cost_center,
    oa.business_unit,

    -- Current Compensation
    c.base_salary,
    c.bonus_target_pct,
    c.currency

FROM employee e
LEFT JOIN location l ON e.location_id = l.location_id
LEFT JOIN employee m ON e.manager_id = m.employee_id
LEFT JOIN employee_job_assignment ja ON e.employee_id = ja.employee_id AND ja.end_date IS NULL
LEFT JOIN employee_org_assignment oa ON e.employee_id = oa.employee_id AND oa.end_date IS NULL
LEFT JOIN employee_compensation c ON e.employee_id = c.employee_id AND c.end_date IS NULL;

COMMENT ON VIEW v_employee_current IS 'Denormalized view of current employee state with all active assignments';

-- ----------------------------------------------------------------------------
-- Employee Point-in-Time Function: Get employee state at specific date
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION get_employee_at_date(
    p_employee_id VARCHAR(20),
    p_date DATE
)
RETURNS TABLE (
    employee_id VARCHAR(20),
    full_name TEXT,
    job_title VARCHAR(200),
    org_name VARCHAR(200),
    base_salary DECIMAL(12,2),
    seniority_level INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.employee_id,
        e.first_name || ' ' || e.last_name,
        ja.job_title,
        oa.org_name,
        c.base_salary,
        ja.seniority_level
    FROM employee e
    LEFT JOIN employee_job_assignment ja ON e.employee_id = ja.employee_id
        AND ja.start_date <= p_date
        AND (ja.end_date IS NULL OR ja.end_date >= p_date)
    LEFT JOIN employee_org_assignment oa ON e.employee_id = oa.employee_id
        AND oa.start_date <= p_date
        AND (oa.end_date IS NULL OR oa.end_date >= p_date)
    LEFT JOIN employee_compensation c ON e.employee_id = c.employee_id
        AND c.start_date <= p_date
        AND (c.end_date IS NULL OR c.end_date >= p_date)
    WHERE e.employee_id = p_employee_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_employee_at_date IS 'Time-travel query: get employee state at any historical date';

-- ============================================================================
-- SAMPLE QUERIES
-- ============================================================================

/*
-- Get all current active employees
SELECT * FROM v_employee_current WHERE employment_status = 'Active';

-- Get employee state at a specific date (time-travel)
SELECT * FROM get_employee_at_date('EMP000001', '2023-06-15');

-- Count employees by department
SELECT business_unit, COUNT(*)
FROM v_employee_current
WHERE employment_status = 'Active'
GROUP BY business_unit;

-- Get promotion history for an employee
SELECT employee_id, job_title, seniority_level, start_date, end_date
FROM employee_job_assignment
WHERE employee_id = 'EMP000001'
ORDER BY start_date;

-- Calculate average tenure by seniority level
SELECT
    ja.seniority_level,
    AVG(EXTRACT(YEAR FROM AGE(e.hire_date))) AS avg_tenure_years
FROM employee e
JOIN employee_job_assignment ja ON e.employee_id = ja.employee_id AND ja.end_date IS NULL
WHERE e.employment_status = 'Active'
GROUP BY ja.seniority_level
ORDER BY ja.seniority_level;

-- Attrition analysis: terminated employees by reason
SELECT
    termination_reason,
    COUNT(*) AS count,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS percentage
FROM employee
WHERE employment_status != 'Active'
GROUP BY termination_reason
ORDER BY count DESC;
*/

-- ============================================================================
-- STREAMING LOAD SUPPORT
-- ============================================================================

-- ----------------------------------------------------------------------------
-- HR Data Load Checkpoint: Tracks streaming load progress for resumability
-- ----------------------------------------------------------------------------
-- This table is auto-created by the loader script if it doesn't exist.
-- It enables year-by-year commits with the ability to resume interrupted loads.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hr_data_load_checkpoint (
    id                      SERIAL          PRIMARY KEY,
    load_session_id         UUID            NOT NULL,
    simulation_year         INTEGER         NOT NULL,
    status                  VARCHAR(20)     NOT NULL DEFAULT 'pending',
    employees_loaded        INTEGER         DEFAULT 0,
    job_assignments_loaded  INTEGER         DEFAULT 0,
    org_assignments_loaded  INTEGER         DEFAULT 0,
    compensation_loaded     INTEGER         DEFAULT 0,
    performance_loaded      INTEGER         DEFAULT 0,
    started_at              TIMESTAMP,
    completed_at            TIMESTAMP,
    error_message           TEXT,
    config_snapshot         JSONB,
    created_at              TIMESTAMP       DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_checkpoint_status
        CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    CONSTRAINT uq_session_year
        UNIQUE (load_session_id, simulation_year)
);

COMMENT ON TABLE hr_data_load_checkpoint IS 'Tracks streaming load progress for year-by-year commits and resumability';
COMMENT ON COLUMN hr_data_load_checkpoint.load_session_id IS 'UUID identifying a single load session (can span multiple runs if resumed)';
COMMENT ON COLUMN hr_data_load_checkpoint.simulation_year IS 'The year being loaded';
COMMENT ON COLUMN hr_data_load_checkpoint.status IS 'pending=not started, in_progress=loading, completed=done, failed=error';
COMMENT ON COLUMN hr_data_load_checkpoint.config_snapshot IS 'JSON of generation config for validation on resume';

CREATE INDEX IF NOT EXISTS idx_checkpoint_session ON hr_data_load_checkpoint(load_session_id);
CREATE INDEX IF NOT EXISTS idx_checkpoint_status ON hr_data_load_checkpoint(status);

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================

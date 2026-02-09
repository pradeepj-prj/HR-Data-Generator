-- ============================================================================
-- Feature Materialization: attrition_features table
-- ============================================================================
-- Materializes v_attrition_features into a physical table for performance.
--
-- WHEN TO USE:
--   - The view re-computes all CTEs on every query. For large datasets
--     (10K+ employees × 10+ years = 100K+ rows), materializing once and
--     querying the table is significantly faster.
--   - Re-run this script whenever the underlying data changes (e.g., after
--     loading a new simulation year).
--
-- TRADE-OFF:
--   - View (01): always fresh, no storage cost, slower queries
--   - Table (02): snapshot in time, uses disk, fast queries + indexable
--
-- Compatible with: PostgreSQL 12+
-- Depends on: 01_create_feature_view.sql
-- ============================================================================

-- Drop existing table (preserves the view)
DROP TABLE IF EXISTS attrition_features;

-- Materialize the view into a table
CREATE TABLE attrition_features AS
SELECT * FROM v_attrition_features;

-- ============================================================================
-- Indexes for common query patterns
-- ============================================================================

-- Primary lookup: specific employee's history
CREATE INDEX idx_af_employee
    ON attrition_features (employee_id, observation_year);

-- ML training: filter by year range, then scan features
CREATE INDEX idx_af_year
    ON attrition_features (observation_year);

-- Target analysis: quickly find all departure rows
CREATE INDEX idx_af_left
    ON attrition_features (left_this_year)
    WHERE left_this_year = 1;

-- Cohort analysis by business unit
CREATE INDEX idx_af_business_unit
    ON attrition_features (business_unit, observation_year);

-- Compensation analysis by seniority band
CREATE INDEX idx_af_seniority
    ON attrition_features (seniority_level, observation_year);

-- ============================================================================
-- Table documentation
-- ============================================================================
COMMENT ON TABLE attrition_features IS
    'Materialized snapshot of v_attrition_features. '
    'Re-run this script after data changes to refresh. '
    'Indexed for common ML training and analysis query patterns.';

-- ============================================================================
-- Summary statistics after materialization
-- ============================================================================
SELECT
    COUNT(*)                                    AS total_rows,
    COUNT(DISTINCT employee_id)                 AS unique_employees,
    MIN(observation_year)                       AS first_year,
    MAX(observation_year)                       AS last_year,
    SUM(left_this_year)                         AS total_departures,
    ROUND(
        100.0 * SUM(left_this_year) / COUNT(*), 2
    )                                           AS departure_rate_pct
FROM attrition_features;

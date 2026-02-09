-- ============================================================================
-- Feature Materialization: ATTRITION_FEATURES table (SAP HANA Cloud)
-- ============================================================================
-- Materializes V_ATTRITION_FEATURES into a physical column table.
--
-- HANA Cloud notes:
--   - Uses COLUMN TABLE (default and recommended for analytics in HANA)
--   - HANA's columnar engine handles analytical queries efficiently, so
--     materialization is less critical than in PostgreSQL, but still useful
--     for repeated ML training runs.
--   - Re-run this script after data changes to refresh.
--
-- Compatible with: SAP HANA Cloud
-- Depends on: 01_create_feature_view.sql
-- ============================================================================

-- Drop existing table (preserves the view)
DROP TABLE ATTRITION_FEATURES;

-- Materialize the view into a column table
CREATE COLUMN TABLE ATTRITION_FEATURES AS (
    SELECT * FROM V_ATTRITION_FEATURES
);

-- ============================================================================
-- Summary statistics after materialization
-- ============================================================================
SELECT
    COUNT(*)                                    AS TOTAL_ROWS,
    COUNT(DISTINCT EMPLOYEE_ID)                 AS UNIQUE_EMPLOYEES,
    MIN(OBSERVATION_YEAR)                       AS FIRST_YEAR,
    MAX(OBSERVATION_YEAR)                       AS LAST_YEAR,
    SUM(LEFT_THIS_YEAR)                         AS TOTAL_DEPARTURES,
    ROUND(
        100.0 * SUM(LEFT_THIS_YEAR) / COUNT(*), 2
    )                                           AS DEPARTURE_RATE_PCT
FROM ATTRITION_FEATURES;

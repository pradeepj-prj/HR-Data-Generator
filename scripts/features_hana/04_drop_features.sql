-- ============================================================================
-- Feature Cleanup: Drop view and materialized table (SAP HANA Cloud)
-- ============================================================================
-- Run this to remove all feature extraction artifacts.
-- Order matters: table first (no dependencies), then view.
--
-- NOTE: HANA Cloud does not support IF EXISTS on DROP. If the object
-- does not exist, the statement will error. Run them individually
-- and ignore "object not found" errors, or wrap in a procedure.
-- ============================================================================

-- Drop materialized table (if created via 02_create_feature_table.sql)
DROP TABLE ATTRITION_FEATURES;

-- Drop the view
DROP VIEW V_ATTRITION_FEATURES;

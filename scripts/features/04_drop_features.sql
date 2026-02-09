-- ============================================================================
-- Feature Cleanup: Drop view and materialized table
-- ============================================================================
-- Run this to remove all feature extraction artifacts.
-- Safe to run multiple times (IF EXISTS).
--
-- Order matters: table first (no dependencies), then view.
-- ============================================================================

-- Drop materialized table (if created via 02_create_feature_table.sql)
DROP TABLE IF EXISTS attrition_features;

-- Drop the view
DROP VIEW IF EXISTS v_attrition_features;

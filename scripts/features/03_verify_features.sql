-- ============================================================================
-- Feature Verification Queries
-- ============================================================================
-- Run these queries after creating v_attrition_features (or the materialized
-- table) to validate data quality and consistency.
--
-- Each query is independent — run them individually and inspect results.
-- Expected outcomes are documented inline.
--
-- Compatible with: PostgreSQL 12+
-- Depends on: 01_create_feature_view.sql or 02_create_feature_table.sql
-- ============================================================================

-- ============================================================================
-- CHECK 1: Overall Shape
-- ============================================================================
-- EXPECT: total_rows >> unique_employees (panel data multiplication)
--         years_spanned matches your simulation range
--         departures should be ~12% of employee-years (base attrition rate)

SELECT
    'Overall shape'                             AS check_name,
    COUNT(*)                                    AS total_rows,
    COUNT(DISTINCT employee_id)                 AS unique_employees,
    MIN(observation_year)                       AS first_year,
    MAX(observation_year)                       AS last_year,
    MAX(observation_year) - MIN(observation_year) + 1
                                                AS years_spanned,
    SUM(left_this_year)                         AS total_departures,
    ROUND(100.0 * SUM(left_this_year) / NULLIF(COUNT(*), 0), 2)
                                                AS departure_rate_pct
FROM v_attrition_features;


-- ============================================================================
-- CHECK 2: Exactly One Departure Row per Terminated Employee
-- ============================================================================
-- EXPECT: 0 rows (no employee should have != 1 departure rows if terminated)
-- WHY:    If an employee has left_this_year=1 in multiple years, the target
--         variable is corrupted. If a terminated employee has 0 departure rows,
--         the year spine or target logic has a bug.

SELECT
    'Departure count mismatch'                  AS check_name,
    e.employee_id,
    e.termination_date,
    departure_count
FROM employee e
JOIN (
    SELECT
        employee_id,
        SUM(left_this_year) AS departure_count
    FROM v_attrition_features
    GROUP BY employee_id
) f ON e.employee_id = f.employee_id
WHERE e.termination_date IS NOT NULL
  AND departure_count != 1;


-- ============================================================================
-- CHECK 3: No Active Employees Marked as Departed
-- ============================================================================
-- EXPECT: 0 rows

SELECT
    'Active employee marked as departed'        AS check_name,
    f.employee_id,
    f.observation_year
FROM v_attrition_features f
JOIN employee e ON f.employee_id = e.employee_id
WHERE e.termination_date IS NULL
  AND f.left_this_year = 1;


-- ============================================================================
-- CHECK 4: No Rows After Termination Year
-- ============================================================================
-- EXPECT: 0 rows (the year spine should stop at termination year)

SELECT
    'Row after termination'                     AS check_name,
    f.employee_id,
    f.observation_year,
    e.termination_date
FROM v_attrition_features f
JOIN employee e ON f.employee_id = e.employee_id
WHERE e.termination_date IS NOT NULL
  AND f.observation_year > EXTRACT(YEAR FROM e.termination_date);


-- ============================================================================
-- CHECK 5: Feature Range Validation
-- ============================================================================
-- EXPECT: All zeros in the violation columns

SELECT
    'Range violations'                          AS check_name,
    COUNT(*) FILTER (WHERE tenure_years < 0 OR tenure_years > 50)
                                                AS bad_tenure,
    COUNT(*) FILTER (WHERE seniority_level IS NOT NULL
                       AND (seniority_level < 1 OR seniority_level > 5))
                                                AS bad_seniority,
    COUNT(*) FILTER (WHERE performance_rating IS NOT NULL
                       AND (performance_rating < 1 OR performance_rating > 5))
                                                AS bad_perf_rating,
    COUNT(*) FILTER (WHERE age < 16 OR age > 110)
                                                AS bad_age,
    COUNT(*) FILTER (WHERE current_salary IS NOT NULL AND current_salary <= 0)
                                                AS bad_salary,
    COUNT(*) FILTER (WHERE comp_ratio_in_role IS NOT NULL
                       AND (comp_ratio_in_role < 0.2 OR comp_ratio_in_role > 5.0))
                                                AS suspicious_comp_ratio,
    COUNT(*) FILTER (WHERE left_this_year NOT IN (0, 1))
                                                AS bad_target
FROM v_attrition_features;


-- ============================================================================
-- CHECK 6: Tenure Monotonicity
-- ============================================================================
-- EXPECT: 0 rows (tenure should increase each year for the same employee)

SELECT
    'Non-monotonic tenure'                      AS check_name,
    employee_id,
    observation_year,
    tenure_years,
    LAG(tenure_years) OVER (
        PARTITION BY employee_id ORDER BY observation_year
    ) AS prev_tenure
FROM v_attrition_features
WHERE tenure_years <= LAG(tenure_years) OVER (
    PARTITION BY employee_id ORDER BY observation_year
);


-- ============================================================================
-- CHECK 7: NULL Analysis — Performance Rating
-- ============================================================================
-- EXPECT: NULL rate decreases for later observation years (employees accumulate
--         reviews over time). First-year employees always have NULL rating.

SELECT
    'Performance NULL rate by year'             AS check_name,
    observation_year,
    COUNT(*)                                    AS total_rows,
    COUNT(*) FILTER (WHERE performance_rating IS NULL)
                                                AS null_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE performance_rating IS NULL) / COUNT(*), 1
    )                                           AS null_pct
FROM v_attrition_features
GROUP BY observation_year
ORDER BY observation_year;


-- ============================================================================
-- CHECK 8: Performance Rating Distribution
-- ============================================================================
-- EXPECT: Approximately 5% / 15% / 50% / 25% / 5% for ratings 1-5
--         (matching the generation probabilities in performance.py)

SELECT
    'Rating distribution'                       AS check_name,
    performance_rating,
    COUNT(*)                                    AS count,
    ROUND(
        100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2
    )                                           AS pct
FROM v_attrition_features
WHERE performance_rating IS NOT NULL
GROUP BY performance_rating
ORDER BY performance_rating;


-- ============================================================================
-- CHECK 9: Compensation Ratio Distribution
-- ============================================================================
-- EXPECT: Centered around 1.0, with most values between 0.5 and 2.0

SELECT
    'Comp ratio distribution'                   AS check_name,
    ROUND(comp_ratio_in_role::NUMERIC, 1)       AS comp_ratio_bucket,
    COUNT(*)                                    AS count
FROM v_attrition_features
WHERE comp_ratio_in_role IS NOT NULL
GROUP BY ROUND(comp_ratio_in_role::NUMERIC, 1)
ORDER BY comp_ratio_bucket;


-- ============================================================================
-- CHECK 10: Promotion Spot-Check
-- ============================================================================
-- EXPECT: Every had_recent_promotion=true row should have a verifiable
--         seniority increase in the job assignment history within the
--         prior-year window. This query returns rows to manually inspect.

SELECT
    'Promotion spot-check'                      AS check_name,
    f.employee_id,
    f.observation_year,
    f.had_recent_promotion,
    f.seniority_level                           AS current_seniority,
    f.total_promotions,
    ja.start_date                               AS job_change_date,
    ja.seniority_level                          AS new_seniority
FROM v_attrition_features f
JOIN employee_job_assignment ja
    ON  f.employee_id = ja.employee_id
    AND ja.start_date >= MAKE_DATE(f.observation_year - 1, 1, 1)
    AND ja.start_date <= MAKE_DATE(f.observation_year, 1, 1)
WHERE f.had_recent_promotion = TRUE
ORDER BY f.employee_id, f.observation_year
LIMIT 20;


-- ============================================================================
-- CHECK 11: Departure Year Matches Termination Date
-- ============================================================================
-- EXPECT: All departure rows should have observation_year = termination year

SELECT
    'Departure year alignment'                  AS check_name,
    f.employee_id,
    f.observation_year,
    e.termination_date,
    EXTRACT(YEAR FROM e.termination_date)       AS expected_year
FROM v_attrition_features f
JOIN employee e ON f.employee_id = e.employee_id
WHERE f.left_this_year = 1
  AND f.observation_year != EXTRACT(YEAR FROM e.termination_date);


-- ============================================================================
-- CHECK 12: Employment Type Distribution
-- ============================================================================
-- EXPECT: ~70% Full-time, ~10% Contract, ~20% Part-time
--         (matching generation probabilities)

SELECT
    'Employment type distribution'              AS check_name,
    employment_type,
    COUNT(DISTINCT employee_id)                 AS unique_employees,
    ROUND(
        100.0 * COUNT(DISTINCT employee_id)
        / SUM(COUNT(DISTINCT employee_id)) OVER (), 2
    )                                           AS pct
FROM v_attrition_features
GROUP BY employment_type
ORDER BY unique_employees DESC;


-- ============================================================================
-- CHECK 13: Seniority Level Distribution
-- ============================================================================
-- EXPECT: Pyramid shape — more level 1-2 than level 4-5

SELECT
    'Seniority distribution'                    AS check_name,
    seniority_level,
    COUNT(*)                                    AS row_count,
    COUNT(DISTINCT employee_id)                 AS unique_employees
FROM v_attrition_features
WHERE seniority_level IS NOT NULL
GROUP BY seniority_level
ORDER BY seniority_level;


-- ============================================================================
-- CHECK 14: Sample Rows — Quick Visual Inspection
-- ============================================================================
-- Pick a few employees and verify their panel looks reasonable

SELECT *
FROM v_attrition_features
WHERE employee_id IN (
    SELECT employee_id
    FROM v_attrition_features
    GROUP BY employee_id
    HAVING COUNT(*) >= 5
    LIMIT 3
)
ORDER BY employee_id, observation_year;

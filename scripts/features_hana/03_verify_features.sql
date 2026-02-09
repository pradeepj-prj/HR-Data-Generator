-- ============================================================================
-- Feature Verification Queries (SAP HANA Cloud)
-- ============================================================================
-- Run these queries after creating V_ATTRITION_FEATURES to validate data
-- quality and consistency.
--
-- HANA Cloud translation notes:
--   - COUNT(*) FILTER (WHERE ...) → SUM(CASE WHEN ... THEN 1 ELSE 0 END)
--   - PERCENTILE_CONT → HANA supports this syntax
--   - BOOL columns are INTEGER 0/1 in HANA
--   - LAG() and other window functions work identically
--
-- Compatible with: SAP HANA Cloud
-- Depends on: 01_create_feature_view.sql
-- ============================================================================

-- ============================================================================
-- CHECK 1: Overall Shape
-- ============================================================================
-- EXPECT: total_rows >> unique_employees (panel data multiplication)

SELECT
    'Overall shape'                             AS CHECK_NAME,
    COUNT(*)                                    AS TOTAL_ROWS,
    COUNT(DISTINCT EMPLOYEE_ID)                 AS UNIQUE_EMPLOYEES,
    MIN(OBSERVATION_YEAR)                       AS FIRST_YEAR,
    MAX(OBSERVATION_YEAR)                       AS LAST_YEAR,
    MAX(OBSERVATION_YEAR) - MIN(OBSERVATION_YEAR) + 1
                                                AS YEARS_SPANNED,
    SUM(LEFT_THIS_YEAR)                         AS TOTAL_DEPARTURES,
    ROUND(100.0 * SUM(LEFT_THIS_YEAR) / COUNT(*), 2)
                                                AS DEPARTURE_RATE_PCT
FROM V_ATTRITION_FEATURES;


-- ============================================================================
-- CHECK 2: Exactly One Departure Row per Terminated Employee
-- ============================================================================
-- EXPECT: 0 rows

SELECT
    'Departure count mismatch'                  AS CHECK_NAME,
    E.EMPLOYEE_ID,
    E.TERMINATION_DATE,
    F.DEPARTURE_COUNT
FROM EMPLOYEE E
INNER JOIN (
    SELECT
        EMPLOYEE_ID,
        SUM(LEFT_THIS_YEAR) AS DEPARTURE_COUNT
    FROM V_ATTRITION_FEATURES
    GROUP BY EMPLOYEE_ID
) F ON E.EMPLOYEE_ID = F.EMPLOYEE_ID
WHERE E.TERMINATION_DATE IS NOT NULL
  AND F.DEPARTURE_COUNT != 1;


-- ============================================================================
-- CHECK 3: No Active Employees Marked as Departed
-- ============================================================================
-- EXPECT: 0 rows

SELECT
    'Active employee marked as departed'        AS CHECK_NAME,
    F.EMPLOYEE_ID,
    F.OBSERVATION_YEAR
FROM V_ATTRITION_FEATURES F
INNER JOIN EMPLOYEE E ON F.EMPLOYEE_ID = E.EMPLOYEE_ID
WHERE E.TERMINATION_DATE IS NULL
  AND F.LEFT_THIS_YEAR = 1;


-- ============================================================================
-- CHECK 4: No Rows After Termination Year
-- ============================================================================
-- EXPECT: 0 rows

SELECT
    'Row after termination'                     AS CHECK_NAME,
    F.EMPLOYEE_ID,
    F.OBSERVATION_YEAR,
    E.TERMINATION_DATE
FROM V_ATTRITION_FEATURES F
INNER JOIN EMPLOYEE E ON F.EMPLOYEE_ID = E.EMPLOYEE_ID
WHERE E.TERMINATION_DATE IS NOT NULL
  AND F.OBSERVATION_YEAR > YEAR(E.TERMINATION_DATE);


-- ============================================================================
-- CHECK 5: Feature Range Validation
-- ============================================================================
-- EXPECT: All zeros in violation columns

SELECT
    'Range violations'                          AS CHECK_NAME,
    SUM(CASE WHEN TENURE_YEARS < 0 OR TENURE_YEARS > 50
        THEN 1 ELSE 0 END)                     AS BAD_TENURE,
    SUM(CASE WHEN SENIORITY_LEVEL IS NOT NULL
             AND (SENIORITY_LEVEL < 1 OR SENIORITY_LEVEL > 5)
        THEN 1 ELSE 0 END)                     AS BAD_SENIORITY,
    SUM(CASE WHEN PERFORMANCE_RATING IS NOT NULL
             AND (PERFORMANCE_RATING < 1 OR PERFORMANCE_RATING > 5)
        THEN 1 ELSE 0 END)                     AS BAD_PERF_RATING,
    SUM(CASE WHEN AGE < 16 OR AGE > 110
        THEN 1 ELSE 0 END)                     AS BAD_AGE,
    SUM(CASE WHEN CURRENT_SALARY IS NOT NULL AND CURRENT_SALARY <= 0
        THEN 1 ELSE 0 END)                     AS BAD_SALARY,
    SUM(CASE WHEN LEFT_THIS_YEAR NOT IN (0, 1)
        THEN 1 ELSE 0 END)                     AS BAD_TARGET
FROM V_ATTRITION_FEATURES;


-- ============================================================================
-- CHECK 6: Tenure Monotonicity
-- ============================================================================
-- EXPECT: 0 rows

SELECT
    'Non-monotonic tenure'                      AS CHECK_NAME,
    EMPLOYEE_ID,
    OBSERVATION_YEAR,
    TENURE_YEARS,
    PREV_TENURE
FROM (
    SELECT
        EMPLOYEE_ID,
        OBSERVATION_YEAR,
        TENURE_YEARS,
        LAG(TENURE_YEARS) OVER (
            PARTITION BY EMPLOYEE_ID ORDER BY OBSERVATION_YEAR
        ) AS PREV_TENURE
    FROM V_ATTRITION_FEATURES
)
WHERE PREV_TENURE IS NOT NULL
  AND TENURE_YEARS <= PREV_TENURE;


-- ============================================================================
-- CHECK 7: NULL Analysis — Performance Rating
-- ============================================================================
-- EXPECT: NULL rate decreases for later observation years

SELECT
    'Performance NULL rate by year'             AS CHECK_NAME,
    OBSERVATION_YEAR,
    COUNT(*)                                    AS TOTAL_ROWS,
    SUM(CASE WHEN PERFORMANCE_RATING IS NULL THEN 1 ELSE 0 END)
                                                AS NULL_COUNT,
    ROUND(
        100.0 * SUM(CASE WHEN PERFORMANCE_RATING IS NULL THEN 1 ELSE 0 END)
        / COUNT(*), 1
    )                                           AS NULL_PCT
FROM V_ATTRITION_FEATURES
GROUP BY OBSERVATION_YEAR
ORDER BY OBSERVATION_YEAR;


-- ============================================================================
-- CHECK 8: Performance Rating Distribution
-- ============================================================================
-- EXPECT: Approximately 5% / 15% / 50% / 25% / 5% for ratings 1-5

SELECT
    'Rating distribution'                       AS CHECK_NAME,
    PERFORMANCE_RATING,
    COUNT(*)                                    AS COUNT,
    ROUND(
        100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2
    )                                           AS PCT
FROM V_ATTRITION_FEATURES
WHERE PERFORMANCE_RATING IS NOT NULL
GROUP BY PERFORMANCE_RATING
ORDER BY PERFORMANCE_RATING;


-- ============================================================================
-- CHECK 9: Compensation Ratio Distribution
-- ============================================================================
-- EXPECT: Centered around 1.0, most values between 0.5 and 2.0

SELECT
    'Comp ratio distribution'                   AS CHECK_NAME,
    ROUND(COMP_RATIO_IN_ROLE, 1)                AS COMP_RATIO_BUCKET,
    COUNT(*)                                    AS COUNT
FROM V_ATTRITION_FEATURES
WHERE COMP_RATIO_IN_ROLE IS NOT NULL
GROUP BY ROUND(COMP_RATIO_IN_ROLE, 1)
ORDER BY COMP_RATIO_BUCKET;


-- ============================================================================
-- CHECK 10: Promotion Spot-Check
-- ============================================================================

SELECT
    'Promotion spot-check'                      AS CHECK_NAME,
    F.EMPLOYEE_ID,
    F.OBSERVATION_YEAR,
    F.HAD_RECENT_PROMOTION,
    F.SENIORITY_LEVEL                           AS CURRENT_SENIORITY,
    F.TOTAL_PROMOTIONS,
    JA.START_DATE                               AS JOB_CHANGE_DATE,
    JA.SENIORITY_LEVEL                          AS NEW_SENIORITY
FROM V_ATTRITION_FEATURES F
INNER JOIN EMPLOYEE_JOB_ASSIGNMENT JA
    ON  F.EMPLOYEE_ID = JA.EMPLOYEE_ID
    AND JA.START_DATE >= TO_DATE((F.OBSERVATION_YEAR - 1) || '-01-01', 'YYYY-MM-DD')
    AND JA.START_DATE <= TO_DATE(F.OBSERVATION_YEAR || '-01-01', 'YYYY-MM-DD')
WHERE F.HAD_RECENT_PROMOTION = 1
ORDER BY F.EMPLOYEE_ID, F.OBSERVATION_YEAR
LIMIT 20;


-- ============================================================================
-- CHECK 11: Departure Year Matches Termination Date
-- ============================================================================
-- EXPECT: 0 rows

SELECT
    'Departure year alignment'                  AS CHECK_NAME,
    F.EMPLOYEE_ID,
    F.OBSERVATION_YEAR,
    E.TERMINATION_DATE,
    YEAR(E.TERMINATION_DATE)                    AS EXPECTED_YEAR
FROM V_ATTRITION_FEATURES F
INNER JOIN EMPLOYEE E ON F.EMPLOYEE_ID = E.EMPLOYEE_ID
WHERE F.LEFT_THIS_YEAR = 1
  AND F.OBSERVATION_YEAR != YEAR(E.TERMINATION_DATE);


-- ============================================================================
-- CHECK 12: Employment Type Distribution
-- ============================================================================
-- EXPECT: ~70% Full-time, ~10% Contract, ~20% Part-time

SELECT
    'Employment type distribution'              AS CHECK_NAME,
    EMPLOYMENT_TYPE,
    COUNT(DISTINCT EMPLOYEE_ID)                 AS UNIQUE_EMPLOYEES,
    ROUND(
        100.0 * COUNT(DISTINCT EMPLOYEE_ID)
        / SUM(COUNT(DISTINCT EMPLOYEE_ID)) OVER (), 2
    )                                           AS PCT
FROM V_ATTRITION_FEATURES
GROUP BY EMPLOYMENT_TYPE
ORDER BY UNIQUE_EMPLOYEES DESC;


-- ============================================================================
-- CHECK 13: Seniority Level Distribution
-- ============================================================================
-- EXPECT: Pyramid shape — more level 1-2 than level 4-5

SELECT
    'Seniority distribution'                    AS CHECK_NAME,
    SENIORITY_LEVEL,
    COUNT(*)                                    AS ROW_COUNT,
    COUNT(DISTINCT EMPLOYEE_ID)                 AS UNIQUE_EMPLOYEES
FROM V_ATTRITION_FEATURES
WHERE SENIORITY_LEVEL IS NOT NULL
GROUP BY SENIORITY_LEVEL
ORDER BY SENIORITY_LEVEL;


-- ============================================================================
-- CHECK 14: Sample Rows — Quick Visual Inspection
-- ============================================================================

SELECT *
FROM V_ATTRITION_FEATURES
WHERE EMPLOYEE_ID IN (
    SELECT EMPLOYEE_ID
    FROM V_ATTRITION_FEATURES
    GROUP BY EMPLOYEE_ID
    HAVING COUNT(*) >= 5
    LIMIT 3
)
ORDER BY EMPLOYEE_ID, OBSERVATION_YEAR;

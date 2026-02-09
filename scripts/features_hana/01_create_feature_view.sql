-- ============================================================================
-- Feature Extraction: V_ATTRITION_FEATURES (SAP HANA Cloud)
-- ============================================================================
-- Creates a panel dataset (one row per employee per observation year) with
-- 25 features + 2 identifiers + 1 target for ML attrition prediction.
--
-- This is the HANA Cloud translation of the PostgreSQL version in
-- scripts/features/01_create_feature_view.sql. All PostgreSQL-specific
-- constructs have been replaced with HANA equivalents:
--
--   PostgreSQL                →  HANA Cloud
--   ─────────────────────────────────────────────────
--   DISTINCT ON              →  ROW_NUMBER() WHERE rn = 1
--   generate_series + LATERAL→  SERIES_GENERATE_INTEGER + WHERE BETWEEN
--   MAKE_DATE()              →  TO_DATE(year || '-MM-DD')
--   BOOL_OR()                →  MAX(CASE ... 1/0)
--   COUNT(*) FILTER (WHERE)  →  SUM(CASE ... 1/0)
--   ::INT, ::NUMERIC         →  TO_INTEGER(), TO_DECIMAL()
--   date1 - date2            →  DAYS_BETWEEN(date2, date1)
--   AGE(d1, d2)              →  YEARS_BETWEEN(d1, d2)
--   TRUE/FALSE               →  1/0 (no SQL BOOLEAN in HANA)
--
-- Compatible with: SAP HANA Cloud
-- Depends on: Same 8 tables as PostgreSQL version
-- ============================================================================

DROP VIEW V_ATTRITION_FEATURES;

CREATE VIEW V_ATTRITION_FEATURES AS
WITH

-- ============================================================================
-- STEP 1: Year Spine — one row per employee per active year
-- ============================================================================
-- WHAT: Generates (employee_id, observation_year, reference_date) tuples
-- WHY:  Panel data requires one row per employee per year they were active.
-- HOW:  SERIES_GENERATE_INTEGER creates a static year range (1985-2030).
--       CROSS JOIN pairs every employee with every year, then WHERE filters
--       to only years the employee was actually active.
-- NOTE: PostgreSQL used CROSS JOIN LATERAL generate_series() which is
--       per-row dynamic. HANA requires the static range + filter approach.
-- MATCHES: attrition.py lines 392-412 (year loop + tenure check)
-- ============================================================================
EMPLOYEE_YEARS AS (
    SELECT
        E.EMPLOYEE_ID,
        Y.GENERATED_PERIOD_START            AS OBSERVATION_YEAR,
        TO_DATE(
            Y.GENERATED_PERIOD_START || '-12-31', 'YYYY-MM-DD'
        )                                   AS REFERENCE_DATE
    FROM EMPLOYEE E
    CROSS JOIN SERIES_GENERATE_INTEGER(1, 1985, 2031) Y
    WHERE Y.GENERATED_PERIOD_START BETWEEN
        YEAR(E.HIRE_DATE)
        AND COALESCE(YEAR(E.TERMINATION_DATE), YEAR(CURRENT_DATE))
    -- Skip years where tenure < ~90 days (0.25 years)
    -- Matches attrition.py line 412: if tenure_years < 0.25: continue
    AND DAYS_BETWEEN(
        E.HIRE_DATE,
        TO_DATE(Y.GENERATED_PERIOD_START || '-12-31', 'YYYY-MM-DD')
    ) > 90
),

-- ============================================================================
-- STEP 2: Current Job — latest job assignment as of each year-end
-- ============================================================================
-- WHAT: For each (employee, year), finds the job assignment active on Dec 31.
-- WHY:  The attrition model uses current seniority_level as a factor input.
-- HOW:  ROW_NUMBER picks the most recent assignment that started <= reference_date.
--       PostgreSQL used DISTINCT ON; HANA uses ROW_NUMBER() WHERE rn = 1.
-- MATCHES: attrition.py lines 426-437 (current job lookup with start_date <= year_end)
-- ============================================================================
YEARLY_JOB AS (
    SELECT EMPLOYEE_ID, OBSERVATION_YEAR,
           SENIORITY_LEVEL, JOB_LEVEL, JOB_FAMILY, JOB_TITLE, JOB_START_DATE
    FROM (
        SELECT
            EY.EMPLOYEE_ID,
            EY.OBSERVATION_YEAR,
            JA.SENIORITY_LEVEL,
            JA.JOB_LEVEL,
            JA.JOB_FAMILY,
            JA.JOB_TITLE,
            JA.START_DATE                   AS JOB_START_DATE,
            ROW_NUMBER() OVER (
                PARTITION BY EY.EMPLOYEE_ID, EY.OBSERVATION_YEAR
                ORDER BY JA.START_DATE DESC
            ) AS RN
        FROM EMPLOYEE_YEARS EY
        INNER JOIN EMPLOYEE_JOB_ASSIGNMENT JA
            ON  EY.EMPLOYEE_ID = JA.EMPLOYEE_ID
            AND JA.START_DATE <= EY.REFERENCE_DATE
    )
    WHERE RN = 1
),

-- ============================================================================
-- STEP 3: Job Transitions — detect seniority increases using LAG()
-- ============================================================================
-- WHAT: Adds previous seniority_level to each job assignment via LAG().
-- WHY:  A "promotion" is defined as a job change where seniority_level increased.
-- HOW:  LAG works identically in HANA and PostgreSQL.
-- ============================================================================
JOB_TRANSITIONS AS (
    SELECT
        JA.EMPLOYEE_ID,
        JA.SENIORITY_LEVEL,
        JA.START_DATE,
        LAG(JA.SENIORITY_LEVEL) OVER (
            PARTITION BY JA.EMPLOYEE_ID
            ORDER BY JA.START_DATE
        ) AS PREV_SENIORITY_LEVEL
    FROM EMPLOYEE_JOB_ASSIGNMENT JA
),

-- ============================================================================
-- STEP 4: Job History Aggregates — per employee-year
-- ============================================================================
-- WHAT: Counts job changes and promotions up to each year-end.
-- WHY:  Employees with many job changes or promotions have different attrition
--       risk profiles. These are enrichment features beyond the core 5.
-- HOW:  SUM(CASE...) replaces PostgreSQL's COUNT(*) FILTER (WHERE ...).
-- ============================================================================
YEARLY_JOB_HISTORY AS (
    SELECT
        EY.EMPLOYEE_ID,
        EY.OBSERVATION_YEAR,
        -- Job changes = total assignments minus the initial one
        COUNT(JA.ID) - 1                    AS JOB_CHANGES_COUNT,
        -- Promotions = assignments where seniority increased over predecessor
        SUM(CASE
            WHEN JT.PREV_SENIORITY_LEVEL IS NOT NULL
             AND JT.SENIORITY_LEVEL > JT.PREV_SENIORITY_LEVEL
            THEN 1 ELSE 0
        END)                                AS TOTAL_PROMOTIONS
    FROM EMPLOYEE_YEARS EY
    INNER JOIN EMPLOYEE_JOB_ASSIGNMENT JA
        ON  EY.EMPLOYEE_ID = JA.EMPLOYEE_ID
        AND JA.START_DATE <= EY.REFERENCE_DATE
    LEFT OUTER JOIN JOB_TRANSITIONS JT
        ON  JA.EMPLOYEE_ID = JT.EMPLOYEE_ID
        AND JA.START_DATE  = JT.START_DATE
    GROUP BY EY.EMPLOYEE_ID, EY.OBSERVATION_YEAR
),

-- ============================================================================
-- STEP 5: Recent Promotion Flag — per employee-year
-- ============================================================================
-- WHAT: Checks if a seniority-increasing job change occurred in the prior year.
-- WHY:  Recent promotions reduce attrition probability by 60% (factor = 0.4).
-- HOW:  MAX(CASE...) returns 1 if any promotion found, 0 otherwise.
--       Replaces PostgreSQL's BOOL_OR().
-- MATCHES: attrition.py lines 443-456 (prev_year_start <= job_start <= year_start)
-- ============================================================================
YEARLY_RECENT_PROMOTION AS (
    SELECT
        EY.EMPLOYEE_ID,
        EY.OBSERVATION_YEAR,
        MAX(CASE
            WHEN JT.PREV_SENIORITY_LEVEL IS NOT NULL
             AND JT.SENIORITY_LEVEL > JT.PREV_SENIORITY_LEVEL
            THEN 1 ELSE 0
        END)                                AS HAD_RECENT_PROMOTION
    FROM EMPLOYEE_YEARS EY
    LEFT OUTER JOIN JOB_TRANSITIONS JT
        ON  EY.EMPLOYEE_ID = JT.EMPLOYEE_ID
        -- Window: Jan 1 of (year-1) to Jan 1 of (year), inclusive on both ends
        AND JT.START_DATE >= TO_DATE((EY.OBSERVATION_YEAR - 1) || '-01-01', 'YYYY-MM-DD')
        AND JT.START_DATE <= TO_DATE(EY.OBSERVATION_YEAR || '-01-01', 'YYYY-MM-DD')
    GROUP BY EY.EMPLOYEE_ID, EY.OBSERVATION_YEAR
),

-- ============================================================================
-- STEP 6: Current Org — latest org assignment as of each year-end
-- ============================================================================
-- WHAT: For each (employee, year), finds the org assignment active on Dec 31.
-- WHY:  Business unit and cost center are useful features for attrition modeling.
-- HOW:  ROW_NUMBER replaces PostgreSQL's DISTINCT ON.
-- ============================================================================
YEARLY_ORG AS (
    SELECT EMPLOYEE_ID, OBSERVATION_YEAR, BUSINESS_UNIT, COST_CENTER, ORG_NAME
    FROM (
        SELECT
            EY.EMPLOYEE_ID,
            EY.OBSERVATION_YEAR,
            OA.BUSINESS_UNIT,
            OA.COST_CENTER,
            OA.ORG_NAME,
            ROW_NUMBER() OVER (
                PARTITION BY EY.EMPLOYEE_ID, EY.OBSERVATION_YEAR
                ORDER BY OA.START_DATE DESC
            ) AS RN
        FROM EMPLOYEE_YEARS EY
        INNER JOIN EMPLOYEE_ORG_ASSIGNMENT OA
            ON  EY.EMPLOYEE_ID = OA.EMPLOYEE_ID
            AND OA.START_DATE <= EY.REFERENCE_DATE
    )
    WHERE RN = 1
),

-- ============================================================================
-- STEP 7: Org History Aggregates — per employee-year
-- ============================================================================
-- WHAT: Counts org changes (transfers) up to each year-end.
-- WHY:  Frequent transfers may indicate instability or career exploration.
-- HOW:  COUNT assignments minus 1 (initial assignment isn't a "change").
-- ============================================================================
YEARLY_ORG_HISTORY AS (
    SELECT
        EY.EMPLOYEE_ID,
        EY.OBSERVATION_YEAR,
        COUNT(OA.ID) - 1                    AS ORG_CHANGES_COUNT
    FROM EMPLOYEE_YEARS EY
    INNER JOIN EMPLOYEE_ORG_ASSIGNMENT OA
        ON  EY.EMPLOYEE_ID = OA.EMPLOYEE_ID
        AND OA.START_DATE <= EY.REFERENCE_DATE
    GROUP BY EY.EMPLOYEE_ID, EY.OBSERVATION_YEAR
),

-- ============================================================================
-- STEP 8: Current Compensation — latest comp record as of each year-end
-- ============================================================================
-- WHAT: For each (employee, year), finds the compensation record active on Dec 31.
-- WHY:  Salary and bonus target are strong attrition predictors.
-- HOW:  ROW_NUMBER replaces PostgreSQL's DISTINCT ON.
-- ============================================================================
YEARLY_COMP AS (
    SELECT EMPLOYEE_ID, OBSERVATION_YEAR, CURRENT_SALARY, BONUS_TARGET_PCT
    FROM (
        SELECT
            EY.EMPLOYEE_ID,
            EY.OBSERVATION_YEAR,
            EC.BASE_SALARY                  AS CURRENT_SALARY,
            EC.BONUS_TARGET_PCT,
            ROW_NUMBER() OVER (
                PARTITION BY EY.EMPLOYEE_ID, EY.OBSERVATION_YEAR
                ORDER BY EC.START_DATE DESC
            ) AS RN
        FROM EMPLOYEE_YEARS EY
        INNER JOIN EMPLOYEE_COMPENSATION EC
            ON  EY.EMPLOYEE_ID = EC.EMPLOYEE_ID
            AND EC.START_DATE <= EY.REFERENCE_DATE
    )
    WHERE RN = 1
),

-- ============================================================================
-- STEP 9: First Compensation — for salary growth calculation
-- ============================================================================
-- WHAT: Gets the initial (hire-date) salary for each employee.
-- WHY:  salary_growth_pct = (current - first) / first.
-- HOW:  ROW_NUMBER with ASC order replaces PostgreSQL's DISTINCT ON ... ASC.
-- ============================================================================
FIRST_COMP AS (
    SELECT EMPLOYEE_ID, FIRST_SALARY
    FROM (
        SELECT
            EC.EMPLOYEE_ID,
            EC.BASE_SALARY                  AS FIRST_SALARY,
            ROW_NUMBER() OVER (
                PARTITION BY EC.EMPLOYEE_ID
                ORDER BY EC.START_DATE ASC
            ) AS RN
        FROM EMPLOYEE_COMPENSATION EC
    )
    WHERE RN = 1
),

-- ============================================================================
-- STEP 10: Average Salary by Seniority Band — for comp_ratio calculation
-- ============================================================================
-- WHAT: Computes AVG(salary) per (seniority_level, observation_year).
-- WHY:  comp_ratio = employee salary / peer average.
-- HOW:  Standard aggregation — identical to PostgreSQL version.
-- ============================================================================
YEARLY_SENIORITY_AVG AS (
    SELECT
        YJ.SENIORITY_LEVEL,
        YC.OBSERVATION_YEAR,
        AVG(YC.CURRENT_SALARY)              AS AVG_SALARY_FOR_BAND
    FROM YEARLY_COMP YC
    INNER JOIN YEARLY_JOB YJ
        ON  YC.EMPLOYEE_ID = YJ.EMPLOYEE_ID
        AND YC.OBSERVATION_YEAR = YJ.OBSERVATION_YEAR
    GROUP BY YJ.SENIORITY_LEVEL, YC.OBSERVATION_YEAR
),

-- ============================================================================
-- STEP 11: Latest Performance Rating — before each observation year
-- ============================================================================
-- WHAT: Gets the most recent performance rating BEFORE the observation year.
-- WHY:  One of the 5 core attrition factors. Strict "< year" because reviews
--       happen in December, after the attrition decision.
-- HOW:  ROW_NUMBER replaces PostgreSQL's DISTINCT ON.
-- MATCHES: attrition.py lines 417-423 (review_period_year < year)
-- ============================================================================
YEARLY_PERF AS (
    SELECT EMPLOYEE_ID, OBSERVATION_YEAR, PERFORMANCE_RATING
    FROM (
        SELECT
            EY.EMPLOYEE_ID,
            EY.OBSERVATION_YEAR,
            EP.RATING                       AS PERFORMANCE_RATING,
            ROW_NUMBER() OVER (
                PARTITION BY EY.EMPLOYEE_ID, EY.OBSERVATION_YEAR
                ORDER BY EP.REVIEW_PERIOD_YEAR DESC
            ) AS RN
        FROM EMPLOYEE_YEARS EY
        INNER JOIN EMPLOYEE_PERFORMANCE EP
            ON  EY.EMPLOYEE_ID = EP.EMPLOYEE_ID
            AND EP.REVIEW_PERIOD_YEAR < EY.OBSERVATION_YEAR
    )
    WHERE RN = 1
),

-- ============================================================================
-- STEP 12: Second-Latest Performance Rating — for trend calculation
-- ============================================================================
-- WHAT: Gets the second most recent rating before each observation year.
-- WHY:  performance_trend = latest_rating - second_latest_rating.
-- HOW:  ROW_NUMBER WHERE rn = 2. Same pattern as PostgreSQL version.
-- ============================================================================
YEARLY_PREV_PERF AS (
    SELECT EMPLOYEE_ID, OBSERVATION_YEAR, PREV_RATING
    FROM (
        SELECT
            EY.EMPLOYEE_ID,
            EY.OBSERVATION_YEAR,
            EP.RATING                       AS PREV_RATING,
            ROW_NUMBER() OVER (
                PARTITION BY EY.EMPLOYEE_ID, EY.OBSERVATION_YEAR
                ORDER BY EP.REVIEW_PERIOD_YEAR DESC
            ) AS RN
        FROM EMPLOYEE_YEARS EY
        INNER JOIN EMPLOYEE_PERFORMANCE EP
            ON  EY.EMPLOYEE_ID = EP.EMPLOYEE_ID
            AND EP.REVIEW_PERIOD_YEAR < EY.OBSERVATION_YEAR
    )
    WHERE RN = 2
),

-- ============================================================================
-- STEP 13: Performance History Aggregates — per employee-year
-- ============================================================================
-- WHAT: Computes avg_rating, had_low_rating, review_count across all prior reviews.
-- WHY:  Aggregate features capture long-term performance patterns.
-- HOW:  MAX(CASE...) replaces PostgreSQL's BOOL_OR for had_low_rating.
-- ============================================================================
YEARLY_PERF_HISTORY AS (
    SELECT
        EY.EMPLOYEE_ID,
        EY.OBSERVATION_YEAR,
        ROUND(AVG(TO_DECIMAL(EP.RATING)), 2)    AS AVG_RATING,
        MAX(CASE WHEN EP.RATING <= 2 THEN 1 ELSE 0 END)
                                                 AS HAD_LOW_RATING,
        COUNT(*)                                 AS REVIEW_COUNT
    FROM EMPLOYEE_YEARS EY
    INNER JOIN EMPLOYEE_PERFORMANCE EP
        ON  EY.EMPLOYEE_ID = EP.EMPLOYEE_ID
        AND EP.REVIEW_PERIOD_YEAR < EY.OBSERVATION_YEAR
    GROUP BY EY.EMPLOYEE_ID, EY.OBSERVATION_YEAR
)

-- ============================================================================
-- FINAL SELECT: Assemble all features into one row per employee-year
-- ============================================================================
SELECT
    -- Identifiers
    EY.EMPLOYEE_ID,
    EY.OBSERVATION_YEAR,

    -- Demographics (3)
    YEARS_BETWEEN(E.BIRTH_DATE, EY.REFERENCE_DATE)
                                        AS AGE,
    E.GENDER,
    L.COUNTRY,

    -- Core Attrition Model Features (5)
    YP.PERFORMANCE_RATING,
    ROUND(
        TO_DECIMAL(DAYS_BETWEEN(E.HIRE_DATE, EY.REFERENCE_DATE)) / 365.25, 2
    )                                   AS TENURE_YEARS,
    E.EMPLOYMENT_TYPE,
    YJ.SENIORITY_LEVEL,
    COALESCE(YRP.HAD_RECENT_PROMOTION, 0)
                                        AS HAD_RECENT_PROMOTION,

    -- Job History Features (4)
    YJ.JOB_LEVEL,
    COALESCE(YJH.JOB_CHANGES_COUNT, 0) AS JOB_CHANGES_COUNT,
    ROUND(
        TO_DECIMAL(DAYS_BETWEEN(YJ.JOB_START_DATE, EY.REFERENCE_DATE)) / 365.25, 2
    )                                   AS TIME_IN_CURRENT_ROLE_YEARS,
    COALESCE(YJH.TOTAL_PROMOTIONS, 0)  AS TOTAL_PROMOTIONS,

    -- Organization Features (3)
    YO.BUSINESS_UNIT,
    COALESCE(YOH.ORG_CHANGES_COUNT, 0) AS ORG_CHANGES_COUNT,
    YO.COST_CENTER,

    -- Compensation Features (4)
    YC.CURRENT_SALARY,
    CASE
        WHEN FC.FIRST_SALARY IS NOT NULL AND FC.FIRST_SALARY > 0
        THEN ROUND(
            (YC.CURRENT_SALARY - FC.FIRST_SALARY) / FC.FIRST_SALARY, 4
        )
    END                                 AS SALARY_GROWTH_PCT,
    CASE
        WHEN YSA.AVG_SALARY_FOR_BAND IS NOT NULL AND YSA.AVG_SALARY_FOR_BAND > 0
        THEN ROUND(
            YC.CURRENT_SALARY / YSA.AVG_SALARY_FOR_BAND, 4
        )
    END                                 AS COMP_RATIO_IN_ROLE,
    YC.BONUS_TARGET_PCT,

    -- Performance Features (4)
    YPH.AVG_RATING,
    CASE
        WHEN YP.PERFORMANCE_RATING IS NOT NULL AND YPP.PREV_RATING IS NOT NULL
        THEN YP.PERFORMANCE_RATING - YPP.PREV_RATING
    END                                 AS PERFORMANCE_TREND,
    COALESCE(YPH.HAD_LOW_RATING, 0)    AS HAD_LOW_RATING,
    COALESCE(YPH.REVIEW_COUNT, 0)      AS REVIEW_COUNT,

    -- Target Variable
    CASE
        WHEN E.TERMINATION_DATE IS NOT NULL
         AND YEAR(E.TERMINATION_DATE) = EY.OBSERVATION_YEAR
        THEN 1
        ELSE 0
    END                                 AS LEFT_THIS_YEAR,
    CASE
        WHEN E.TERMINATION_DATE IS NOT NULL
         AND YEAR(E.TERMINATION_DATE) = EY.OBSERVATION_YEAR
        THEN E.TERMINATION_REASON
    END                                 AS TERMINATION_REASON

FROM EMPLOYEE_YEARS EY
-- Hub table for demographics and target
INNER JOIN EMPLOYEE E
    ON EY.EMPLOYEE_ID = E.EMPLOYEE_ID
-- Location for country
LEFT OUTER JOIN LOCATION L
    ON E.LOCATION_ID = L.LOCATION_ID
-- Current job as of year-end
LEFT OUTER JOIN YEARLY_JOB YJ
    ON  EY.EMPLOYEE_ID = YJ.EMPLOYEE_ID
    AND EY.OBSERVATION_YEAR = YJ.OBSERVATION_YEAR
-- Job history aggregates
LEFT OUTER JOIN YEARLY_JOB_HISTORY YJH
    ON  EY.EMPLOYEE_ID = YJH.EMPLOYEE_ID
    AND EY.OBSERVATION_YEAR = YJH.OBSERVATION_YEAR
-- Recent promotion flag
LEFT OUTER JOIN YEARLY_RECENT_PROMOTION YRP
    ON  EY.EMPLOYEE_ID = YRP.EMPLOYEE_ID
    AND EY.OBSERVATION_YEAR = YRP.OBSERVATION_YEAR
-- Current org as of year-end
LEFT OUTER JOIN YEARLY_ORG YO
    ON  EY.EMPLOYEE_ID = YO.EMPLOYEE_ID
    AND EY.OBSERVATION_YEAR = YO.OBSERVATION_YEAR
-- Org history aggregates
LEFT OUTER JOIN YEARLY_ORG_HISTORY YOH
    ON  EY.EMPLOYEE_ID = YOH.EMPLOYEE_ID
    AND EY.OBSERVATION_YEAR = YOH.OBSERVATION_YEAR
-- Current compensation as of year-end
LEFT OUTER JOIN YEARLY_COMP YC
    ON  EY.EMPLOYEE_ID = YC.EMPLOYEE_ID
    AND EY.OBSERVATION_YEAR = YC.OBSERVATION_YEAR
-- First compensation (for salary growth)
LEFT OUTER JOIN FIRST_COMP FC
    ON EY.EMPLOYEE_ID = FC.EMPLOYEE_ID
-- Seniority band average salary (for comp ratio)
LEFT OUTER JOIN YEARLY_SENIORITY_AVG YSA
    ON  YJ.SENIORITY_LEVEL = YSA.SENIORITY_LEVEL
    AND EY.OBSERVATION_YEAR = YSA.OBSERVATION_YEAR
-- Latest performance rating
LEFT OUTER JOIN YEARLY_PERF YP
    ON  EY.EMPLOYEE_ID = YP.EMPLOYEE_ID
    AND EY.OBSERVATION_YEAR = YP.OBSERVATION_YEAR
-- Second-latest performance rating (for trend)
LEFT OUTER JOIN YEARLY_PREV_PERF YPP
    ON  EY.EMPLOYEE_ID = YPP.EMPLOYEE_ID
    AND EY.OBSERVATION_YEAR = YPP.OBSERVATION_YEAR
-- Performance history aggregates
LEFT OUTER JOIN YEARLY_PERF_HISTORY YPH
    ON  EY.EMPLOYEE_ID = YPH.EMPLOYEE_ID
    AND EY.OBSERVATION_YEAR = YPH.OBSERVATION_YEAR;

-- View documentation
COMMENT ON VIEW V_ATTRITION_FEATURES IS 'Panel dataset for ML attrition prediction: one row per employee per active year. Features mirror attrition.py factor inputs exactly. Use OBSERVATION_YEAR to filter training windows; LEFT_THIS_YEAR is the target.';

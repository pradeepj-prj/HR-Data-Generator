-- ============================================================================
-- Feature Extraction: v_attrition_features
-- ============================================================================
-- Creates a panel dataset (one row per employee per observation year) with
-- 25 features + 2 identifiers + 1 target for ML attrition prediction.
--
-- This view mirrors the exact feature extraction logic from attrition.py's
-- apply_attrition_for_year() function, translating Python → SQL.
--
-- Compatible with: PostgreSQL 12+
-- Depends on: postgres_schema.sql (all 8 tables)
-- ============================================================================

DROP VIEW IF EXISTS v_attrition_features CASCADE;

CREATE OR REPLACE VIEW v_attrition_features AS
WITH

-- ============================================================================
-- STEP 1: Year Spine — one row per employee per active year
-- ============================================================================
-- WHAT: Generates (employee_id, observation_year, reference_date) tuples
-- WHY:  Panel data requires one row per employee per year they were active.
--       This is the "backbone" that all other CTEs join onto.
-- HOW:  CROSS JOIN with generate_series from hire year to termination/current year.
--       Filters out years where tenure < 90 days (matches attrition.py line 412).
-- MATCHES: attrition.py lines 392-412 (year loop + tenure check)
-- ============================================================================
employee_years AS (
    SELECT
        e.employee_id,
        y.year                          AS observation_year,
        MAKE_DATE(y.year, 12, 31)       AS reference_date
    FROM employee e
    CROSS JOIN LATERAL generate_series(
        EXTRACT(YEAR FROM e.hire_date)::INT,
        COALESCE(
            EXTRACT(YEAR FROM e.termination_date)::INT,
            EXTRACT(YEAR FROM CURRENT_DATE)::INT
        )
    ) AS y(year)
    -- Skip years where tenure < ~90 days (0.25 years)
    -- Matches attrition.py line 412: if tenure_years < 0.25: continue
    WHERE (MAKE_DATE(y.year, 12, 31) - e.hire_date) > 90
),

-- ============================================================================
-- STEP 2: Current Job — latest job assignment as of each year-end
-- ============================================================================
-- WHAT: For each (employee, year), finds the job assignment active on Dec 31.
-- WHY:  The attrition model uses current seniority_level as a factor input.
--       We also extract job_level, job_family, job_title for additional features.
-- HOW:  DISTINCT ON picks the most recent assignment that started <= reference_date.
-- MATCHES: attrition.py lines 426-437 (current job lookup with start_date <= year_end)
-- ============================================================================
yearly_job AS (
    SELECT DISTINCT ON (ey.employee_id, ey.observation_year)
        ey.employee_id,
        ey.observation_year,
        ja.seniority_level,
        ja.job_level,
        ja.job_family,
        ja.job_title,
        ja.start_date                   AS job_start_date
    FROM employee_years ey
    JOIN employee_job_assignment ja
        ON  ey.employee_id = ja.employee_id
        AND ja.start_date <= ey.reference_date
    ORDER BY ey.employee_id, ey.observation_year, ja.start_date DESC
),

-- ============================================================================
-- STEP 3: Job Transitions — detect seniority increases using LAG()
-- ============================================================================
-- WHAT: Adds previous seniority_level to each job assignment via LAG().
-- WHY:  A "promotion" is defined as a job change where seniority_level increased.
--       We need this to calculate total_promotions and had_recent_promotion.
-- HOW:  LAG(seniority_level) OVER (PARTITION BY employee_id ORDER BY start_date)
-- ============================================================================
job_transitions AS (
    SELECT
        ja.employee_id,
        ja.seniority_level,
        ja.start_date,
        LAG(ja.seniority_level) OVER (
            PARTITION BY ja.employee_id
            ORDER BY ja.start_date
        ) AS prev_seniority_level
    FROM employee_job_assignment ja
),

-- ============================================================================
-- STEP 4: Job History Aggregates — per employee-year
-- ============================================================================
-- WHAT: Counts job changes and promotions up to each year-end.
-- WHY:  Employees with many job changes or promotions have different attrition
--       risk profiles. These are enrichment features beyond the core 5.
-- HOW:  COUNT assignments (minus 1 for initial) and COUNT seniority increases.
-- ============================================================================
yearly_job_history AS (
    SELECT
        ey.employee_id,
        ey.observation_year,
        -- Job changes = total assignments minus the initial one
        COUNT(ja.id) - 1                AS job_changes_count,
        -- Promotions = assignments where seniority increased over predecessor
        COUNT(*) FILTER (
            WHERE jt.prev_seniority_level IS NOT NULL
              AND jt.seniority_level > jt.prev_seniority_level
        )                               AS total_promotions
    FROM employee_years ey
    JOIN employee_job_assignment ja
        ON  ey.employee_id = ja.employee_id
        AND ja.start_date <= ey.reference_date
    LEFT JOIN job_transitions jt
        ON  ja.employee_id = jt.employee_id
        AND ja.start_date  = jt.start_date
    GROUP BY ey.employee_id, ey.observation_year
),

-- ============================================================================
-- STEP 5: Recent Promotion Flag — per employee-year
-- ============================================================================
-- WHAT: Checks if a seniority-increasing job change occurred in the prior year.
-- WHY:  Recent promotions reduce attrition probability by 60% (factor = 0.4).
--       This is one of the 5 core factors in the attrition model.
-- HOW:  Look for job transitions in window [Jan 1 of year-1, Jan 1 of year]
--       where seniority_level > prev_seniority_level.
-- MATCHES: attrition.py lines 443-456 (prev_year_start <= job_start <= year_start)
-- ============================================================================
yearly_recent_promotion AS (
    SELECT
        ey.employee_id,
        ey.observation_year,
        BOOL_OR(
            jt.prev_seniority_level IS NOT NULL
            AND jt.seniority_level > jt.prev_seniority_level
        )                               AS had_recent_promotion
    FROM employee_years ey
    LEFT JOIN job_transitions jt
        ON  ey.employee_id = jt.employee_id
        -- Window: Jan 1 of (year-1) to Jan 1 of (year), inclusive on both ends
        AND jt.start_date >= MAKE_DATE(ey.observation_year - 1, 1, 1)
        AND jt.start_date <= MAKE_DATE(ey.observation_year, 1, 1)
    GROUP BY ey.employee_id, ey.observation_year
),

-- ============================================================================
-- STEP 6: Current Org — latest org assignment as of each year-end
-- ============================================================================
-- WHAT: For each (employee, year), finds the org assignment active on Dec 31.
-- WHY:  Business unit and cost center are useful features for attrition modeling
--       (some departments have higher turnover than others).
-- HOW:  Same DISTINCT ON pattern as yearly_job.
-- ============================================================================
yearly_org AS (
    SELECT DISTINCT ON (ey.employee_id, ey.observation_year)
        ey.employee_id,
        ey.observation_year,
        oa.business_unit,
        oa.cost_center,
        oa.org_name
    FROM employee_years ey
    JOIN employee_org_assignment oa
        ON  ey.employee_id = oa.employee_id
        AND oa.start_date <= ey.reference_date
    ORDER BY ey.employee_id, ey.observation_year, oa.start_date DESC
),

-- ============================================================================
-- STEP 7: Org History Aggregates — per employee-year
-- ============================================================================
-- WHAT: Counts org changes (transfers) up to each year-end.
-- WHY:  Frequent transfers may indicate instability or career exploration.
-- HOW:  COUNT assignments minus 1 (initial assignment isn't a "change").
-- ============================================================================
yearly_org_history AS (
    SELECT
        ey.employee_id,
        ey.observation_year,
        COUNT(oa.id) - 1                AS org_changes_count
    FROM employee_years ey
    JOIN employee_org_assignment oa
        ON  ey.employee_id = oa.employee_id
        AND oa.start_date <= ey.reference_date
    GROUP BY ey.employee_id, ey.observation_year
),

-- ============================================================================
-- STEP 8: Current Compensation — latest comp record as of each year-end
-- ============================================================================
-- WHAT: For each (employee, year), finds the compensation record active on Dec 31.
-- WHY:  Salary and bonus target are strong attrition predictors (pay competitiveness).
-- HOW:  Same DISTINCT ON pattern, ordered by start_date DESC.
-- ============================================================================
yearly_comp AS (
    SELECT DISTINCT ON (ey.employee_id, ey.observation_year)
        ey.employee_id,
        ey.observation_year,
        ec.base_salary                  AS current_salary,
        ec.bonus_target_pct
    FROM employee_years ey
    JOIN employee_compensation ec
        ON  ey.employee_id = ec.employee_id
        AND ec.start_date <= ey.reference_date
    ORDER BY ey.employee_id, ey.observation_year, ec.start_date DESC
),

-- ============================================================================
-- STEP 9: First Compensation — for salary growth calculation
-- ============================================================================
-- WHAT: Gets the initial (hire-date) salary for each employee.
-- WHY:  salary_growth_pct = (current - first) / first. We need the baseline.
-- HOW:  DISTINCT ON with ASC order (earliest record per employee).
-- ============================================================================
first_comp AS (
    SELECT DISTINCT ON (ec.employee_id)
        ec.employee_id,
        ec.base_salary                  AS first_salary
    FROM employee_compensation ec
    ORDER BY ec.employee_id, ec.start_date ASC
),

-- ============================================================================
-- STEP 10: Average Salary by Seniority Band — for comp_ratio calculation
-- ============================================================================
-- WHAT: Computes AVG(salary) per (seniority_level, observation_year).
-- WHY:  comp_ratio = employee salary / peer average. Values > 1.0 mean above-average
--       pay; values < 1.0 may signal retention risk.
-- HOW:  Join yearly_comp with yearly_job to get seniority, then AVG by group.
-- ============================================================================
yearly_seniority_avg AS (
    SELECT
        yj.seniority_level,
        yc.observation_year,
        AVG(yc.current_salary)          AS avg_salary_for_band
    FROM yearly_comp yc
    JOIN yearly_job yj
        ON  yc.employee_id = yj.employee_id
        AND yc.observation_year = yj.observation_year
    GROUP BY yj.seniority_level, yc.observation_year
),

-- ============================================================================
-- STEP 11: Latest Performance Rating — before each observation year
-- ============================================================================
-- WHAT: Gets the most recent performance rating BEFORE the observation year.
-- WHY:  This is one of the 5 core attrition factors. Using "< year" (not "<=")
--       because reviews happen in December and the attrition decision uses only
--       prior-year reviews.
-- HOW:  DISTINCT ON ordered by review_period_year DESC, filtered to < observation_year.
-- MATCHES: attrition.py lines 417-423 (review_period_year < year)
-- ============================================================================
yearly_perf AS (
    SELECT DISTINCT ON (ey.employee_id, ey.observation_year)
        ey.employee_id,
        ey.observation_year,
        ep.rating                       AS performance_rating
    FROM employee_years ey
    JOIN employee_performance ep
        ON  ey.employee_id = ep.employee_id
        AND ep.review_period_year < ey.observation_year
    ORDER BY ey.employee_id, ey.observation_year, ep.review_period_year DESC
),

-- ============================================================================
-- STEP 12: Second-Latest Performance Rating — for trend calculation
-- ============================================================================
-- WHAT: Gets the second most recent rating before each observation year.
-- WHY:  performance_trend = latest_rating - second_latest_rating.
--       A positive trend (improving) may reduce attrition; negative may increase it.
-- HOW:  Uses a subquery with ROW_NUMBER to pick the 2nd-ranked review.
-- ============================================================================
yearly_prev_perf AS (
    SELECT
        employee_id,
        observation_year,
        rating                          AS prev_rating
    FROM (
        SELECT
            ey.employee_id,
            ey.observation_year,
            ep.rating,
            ROW_NUMBER() OVER (
                PARTITION BY ey.employee_id, ey.observation_year
                ORDER BY ep.review_period_year DESC
            ) AS rn
        FROM employee_years ey
        JOIN employee_performance ep
            ON  ey.employee_id = ep.employee_id
            AND ep.review_period_year < ey.observation_year
    ) ranked
    WHERE rn = 2
),

-- ============================================================================
-- STEP 13: Performance History Aggregates — per employee-year
-- ============================================================================
-- WHAT: Computes avg_rating, had_low_rating, review_count across all prior reviews.
-- WHY:  These aggregate features capture long-term performance patterns that a
--       single latest-rating misses (e.g., consistently low performers).
-- HOW:  Standard aggregations on reviews where review_period_year < observation_year.
-- ============================================================================
yearly_perf_history AS (
    SELECT
        ey.employee_id,
        ey.observation_year,
        ROUND(AVG(ep.rating)::NUMERIC, 2)   AS avg_rating,
        BOOL_OR(ep.rating <= 2)              AS had_low_rating,
        COUNT(*)                             AS review_count
    FROM employee_years ey
    JOIN employee_performance ep
        ON  ey.employee_id = ep.employee_id
        AND ep.review_period_year < ey.observation_year
    GROUP BY ey.employee_id, ey.observation_year
)

-- ============================================================================
-- FINAL SELECT: Assemble all features into one row per employee-year
-- ============================================================================
SELECT
    -- ── Identifiers ──────────────────────────────────────────────────────
    ey.employee_id,
    ey.observation_year,

    -- ── Demographics (3) ─────────────────────────────────────────────────
    EXTRACT(YEAR FROM AGE(ey.reference_date, e.birth_date))::INT
                                        AS age,
    e.gender,
    l.country,

    -- ── Core Attrition Model Features (5) ────────────────────────────────
    -- These are the exact 5 inputs to AttritionModel.will_leave_this_year()
    yp.performance_rating,
    ROUND(
        (ey.reference_date - e.hire_date)::NUMERIC / 365.25, 2
    )                                   AS tenure_years,
    e.employment_type,
    yj.seniority_level,
    COALESCE(yrp.had_recent_promotion, FALSE)
                                        AS had_recent_promotion,

    -- ── Job History Features (4) ─────────────────────────────────────────
    yj.job_level,
    COALESCE(yjh.job_changes_count, 0)  AS job_changes_count,
    ROUND(
        (ey.reference_date - yj.job_start_date)::NUMERIC / 365.25, 2
    )                                   AS time_in_current_role_years,
    COALESCE(yjh.total_promotions, 0)   AS total_promotions,

    -- ── Organization Features (3) ────────────────────────────────────────
    yo.business_unit,
    COALESCE(yoh.org_changes_count, 0)  AS org_changes_count,
    yo.cost_center,

    -- ── Compensation Features (4) ────────────────────────────────────────
    yc.current_salary,
    CASE
        WHEN fc.first_salary IS NOT NULL AND fc.first_salary > 0
        THEN ROUND(
            (yc.current_salary - fc.first_salary) / fc.first_salary, 4
        )
    END                                 AS salary_growth_pct,
    CASE
        WHEN ysa.avg_salary_for_band IS NOT NULL AND ysa.avg_salary_for_band > 0
        THEN ROUND(
            yc.current_salary / ysa.avg_salary_for_band, 4
        )
    END                                 AS comp_ratio_in_role,
    yc.bonus_target_pct,

    -- ── Performance Features (4) ─────────────────────────────────────────
    yph.avg_rating,
    CASE
        WHEN yp.performance_rating IS NOT NULL AND ypp.prev_rating IS NOT NULL
        THEN yp.performance_rating - ypp.prev_rating
    END                                 AS performance_trend,
    COALESCE(yph.had_low_rating, FALSE) AS had_low_rating,
    COALESCE(yph.review_count, 0)       AS review_count,

    -- ── Target Variable ──────────────────────────────────────────────────
    CASE
        WHEN e.termination_date IS NOT NULL
         AND EXTRACT(YEAR FROM e.termination_date) = ey.observation_year
        THEN 1
        ELSE 0
    END                                 AS left_this_year,
    CASE
        WHEN e.termination_date IS NOT NULL
         AND EXTRACT(YEAR FROM e.termination_date) = ey.observation_year
        THEN e.termination_reason
    END                                 AS termination_reason

FROM employee_years ey
-- Hub table for demographics and target
JOIN employee e
    ON ey.employee_id = e.employee_id
-- Location for country
LEFT JOIN location l
    ON e.location_id = l.location_id
-- Current job as of year-end
LEFT JOIN yearly_job yj
    ON  ey.employee_id = yj.employee_id
    AND ey.observation_year = yj.observation_year
-- Job history aggregates
LEFT JOIN yearly_job_history yjh
    ON  ey.employee_id = yjh.employee_id
    AND ey.observation_year = yjh.observation_year
-- Recent promotion flag
LEFT JOIN yearly_recent_promotion yrp
    ON  ey.employee_id = yrp.employee_id
    AND ey.observation_year = yrp.observation_year
-- Current org as of year-end
LEFT JOIN yearly_org yo
    ON  ey.employee_id = yo.employee_id
    AND ey.observation_year = yo.observation_year
-- Org history aggregates
LEFT JOIN yearly_org_history yoh
    ON  ey.employee_id = yoh.employee_id
    AND ey.observation_year = yoh.observation_year
-- Current compensation as of year-end
LEFT JOIN yearly_comp yc
    ON  ey.employee_id = yc.employee_id
    AND ey.observation_year = yc.observation_year
-- First compensation (for salary growth)
LEFT JOIN first_comp fc
    ON ey.employee_id = fc.employee_id
-- Seniority band average salary (for comp ratio)
LEFT JOIN yearly_seniority_avg ysa
    ON  yj.seniority_level = ysa.seniority_level
    AND ey.observation_year = ysa.observation_year
-- Latest performance rating
LEFT JOIN yearly_perf yp
    ON  ey.employee_id = yp.employee_id
    AND ey.observation_year = yp.observation_year
-- Second-latest performance rating (for trend)
LEFT JOIN yearly_prev_perf ypp
    ON  ey.employee_id = ypp.employee_id
    AND ey.observation_year = ypp.observation_year
-- Performance history aggregates
LEFT JOIN yearly_perf_history yph
    ON  ey.employee_id = yph.employee_id
    AND ey.observation_year = yph.observation_year
;

-- ============================================================================
-- View documentation
-- ============================================================================
COMMENT ON VIEW v_attrition_features IS
    'Panel dataset for ML attrition prediction: one row per employee per active year. '
    'Features mirror attrition.py factor inputs exactly. '
    'Use observation_year to filter training windows; left_this_year is the target.';

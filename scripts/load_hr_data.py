#!/usr/bin/env python3
"""
HR Data Loader - Generate and load HR data into PostgreSQL

This script generates synthetic HR data using the hr-data-generator library
and loads it directly into a remote PostgreSQL database.

Usage:
    # Batch mode (default)
    python scripts/load_hr_data.py --employees 500 --years 5 --seed 42 --verbose
    python scripts/load_hr_data.py -n 1000 --attrition-rate 0.15 --noise-std 0.3
    python scripts/load_hr_data.py --dry-run --employees 100  # Test without inserting

    # Streaming mode (year-by-year commits with resumability)
    python scripts/load_hr_data.py --streaming -n 5000 --years 5 --seed 42 -v
    python scripts/load_hr_data.py --resume --session-id <uuid>
    python scripts/load_hr_data.py --status --session-id <uuid>

Environment:
    HR_DB_PASSWORD: Database password (required, or use .env file)
"""

import argparse
import json
import os
import signal
import sys
import uuid
from datetime import date, datetime, timedelta
from typing import Any

# Add src to path for local development
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, use shell env vars

import psycopg2
from psycopg2.extras import execute_values

from hr_data_generator import generate_hr_data
from hr_data_generator.streaming import generate_hr_data_streaming, YearlyDataChunk


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================

DB_CONFIG = {
    "host": "13.228.165.215",
    "port": 5432,
    "database": "hr_data",
    "user": "hr_app",
}

# Tables in load order (respects foreign key dependencies)
LOAD_ORDER = [
    "location",
    "organization_unit",
    "job_role",
    "employee",
    "employee_job_assignment",
    "employee_org_assignment",
    "employee_compensation",
    "employee_performance",
]


# =============================================================================
# ARGUMENT PARSING
# =============================================================================

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate HR data and load into PostgreSQL",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Basic generation (100 employees, 3 years):
    python scripts/load_hr_data.py

  Large dataset with custom settings:
    python scripts/load_hr_data.py -n 1000 --years 5 --seed 42 --verbose

  High attrition with noise for ML training:
    python scripts/load_hr_data.py -n 500 --attrition-rate 0.20 --noise-std 0.3

  Test run without database insertion:
    python scripts/load_hr_data.py --dry-run -n 100

  Clear existing data and reload:
    python scripts/load_hr_data.py --truncate -n 500
        """
    )

    # -------------------------------------------------------------------------
    # Core Generation Settings
    # -------------------------------------------------------------------------
    core = parser.add_argument_group("Core Generation")
    core.add_argument(
        "-n", "--employees",
        type=int,
        default=100,
        help="Number of employees to generate (default: 100)"
    )
    core.add_argument(
        "--years",
        type=int,
        default=3,
        help="Years of history to simulate (default: 3)"
    )
    core.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (default: None)"
    )
    core.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Simulation start date YYYY-MM-DD (default: <years> ago from today)"
    )
    core.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="Simulation end date YYYY-MM-DD (default: today)"
    )

    # -------------------------------------------------------------------------
    # Feature Toggles
    # -------------------------------------------------------------------------
    features = parser.add_argument_group("Feature Toggles")
    features.add_argument(
        "--no-performance",
        action="store_true",
        help="Disable performance review generation"
    )
    features.add_argument(
        "--no-compensation",
        action="store_true",
        help="Disable compensation record generation"
    )
    features.add_argument(
        "--no-attrition",
        action="store_true",
        help="Disable employee attrition/turnover"
    )
    features.add_argument(
        "--include-hiring",
        action="store_true",
        help="Enable hiring simulation (new hires over time)"
    )

    # -------------------------------------------------------------------------
    # Attrition Model Settings
    # -------------------------------------------------------------------------
    attrition = parser.add_argument_group("Attrition Model (ML Settings)")
    attrition.add_argument(
        "--attrition-rate",
        type=float,
        default=0.12,
        help="Base annual attrition rate (default: 0.12 = 12%%)"
    )
    attrition.add_argument(
        "--noise-std",
        type=float,
        default=0.2,
        help="Noise std dev for ML difficulty: 0.1=easy ~90%%, 0.2=medium ~80%%, 0.3=hard ~70%% (default: 0.2)"
    )
    attrition.add_argument(
        "--unexplained-departure-rate",
        type=float,
        default=0.025,
        help="Rate of unexplained departures (default: 0.025 = 2.5%%)"
    )
    attrition.add_argument(
        "--unexplained-retention-rate",
        type=float,
        default=0.05,
        help="Rate of unexplained retention for high-risk employees (default: 0.05 = 5%%)"
    )

    # -------------------------------------------------------------------------
    # Hiring Model Settings
    # -------------------------------------------------------------------------
    hiring = parser.add_argument_group("Hiring Model (requires --include-hiring)")
    hiring.add_argument(
        "--base-growth-rate",
        type=float,
        default=0.05,
        help="Base annual workforce growth rate (default: 0.05 = 5%%)"
    )
    hiring.add_argument(
        "--backfill-rate",
        type=float,
        default=0.85,
        help="Fraction of attrition to backfill (default: 0.85 = 85%%)"
    )
    hiring.add_argument(
        "--engineering-growth",
        type=float,
        default=0.08,
        help="Engineering business unit growth rate (default: 0.08 = 8%%)"
    )
    hiring.add_argument(
        "--sales-growth",
        type=float,
        default=0.05,
        help="Sales business unit growth rate (default: 0.05 = 5%%)"
    )
    hiring.add_argument(
        "--corporate-growth",
        type=float,
        default=0.02,
        help="Corporate business unit growth rate (default: 0.02 = 2%%)"
    )

    # -------------------------------------------------------------------------
    # Business Unit Distribution
    # -------------------------------------------------------------------------
    bu_dist = parser.add_argument_group("Business Unit Distribution (must sum to 1.0)")
    bu_dist.add_argument(
        "--engineering-pct",
        type=float,
        default=0.50,
        help="Engineering workforce percentage (default: 0.50 = 50%%)"
    )
    bu_dist.add_argument(
        "--sales-pct",
        type=float,
        default=0.30,
        help="Sales workforce percentage (default: 0.30 = 30%%)"
    )
    bu_dist.add_argument(
        "--corporate-pct",
        type=float,
        default=0.20,
        help="Corporate workforce percentage (default: 0.20 = 20%%)"
    )

    # -------------------------------------------------------------------------
    # Database Options
    # -------------------------------------------------------------------------
    db_opts = parser.add_argument_group("Database Options")
    db_opts.add_argument(
        "--truncate",
        action="store_true",
        help="Clear existing data before loading (DANGER: deletes all data)"
    )
    db_opts.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate data and show counts, but don't insert into database"
    )
    db_opts.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed progress messages"
    )

    # -------------------------------------------------------------------------
    # Streaming Mode Options
    # -------------------------------------------------------------------------
    streaming_opts = parser.add_argument_group("Streaming Mode (year-by-year commits)")
    streaming_opts.add_argument(
        "--streaming",
        action="store_true",
        help="Use streaming mode with year-by-year commits for progress visibility and resumability"
    )
    streaming_opts.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted streaming load (requires --session-id)"
    )
    streaming_opts.add_argument(
        "--session-id",
        type=str,
        default=None,
        help="Session ID for resume or status check (UUID format)"
    )
    streaming_opts.add_argument(
        "--status",
        action="store_true",
        help="Show status of a load session (requires --session-id)"
    )

    args = parser.parse_args()

    # Validate business unit distribution
    bu_total = args.engineering_pct + args.sales_pct + args.corporate_pct
    if abs(bu_total - 1.0) > 0.001:
        parser.error(f"Business unit percentages must sum to 1.0 (got {bu_total:.3f})")

    # Validate streaming mode arguments
    if args.resume and not args.session_id:
        parser.error("--resume requires --session-id")
    if args.status and not args.session_id:
        parser.error("--status requires --session-id")
    if args.resume and not args.streaming:
        args.streaming = True  # Implicitly enable streaming for resume

    # Validate session ID format if provided
    if args.session_id:
        try:
            uuid.UUID(args.session_id)
        except ValueError:
            parser.error(f"Invalid session ID format: {args.session_id} (must be UUID)")

    return args


# =============================================================================
# DATA GENERATION
# =============================================================================

def generate_data(args: argparse.Namespace) -> dict:
    """Generate HR data using the hr-data-generator library."""

    # Calculate date range
    end_date = date.today() if args.end_date is None else date.fromisoformat(args.end_date)
    start_date = (
        end_date - timedelta(days=args.years * 365)
        if args.start_date is None
        else date.fromisoformat(args.start_date)
    )

    # Build business unit configurations
    bu_distribution = {
        "Engineering": args.engineering_pct,
        "Sales": args.sales_pct,
        "Corporate": args.corporate_pct,
    }

    bu_growth_rates = {
        "Engineering": args.engineering_growth,
        "Sales": args.sales_growth,
        "Corporate": args.corporate_growth,
    }

    # Progress callback for verbose mode
    def progress_callback(info):
        if args.verbose:
            pct = f"{info.progress:.0%}" if hasattr(info, 'progress') else f"{info.step}/{info.total_steps}"
            sub = f" ({info.sub_step}/{info.sub_total})" if info.sub_step else ""
            print(f"  [{pct}]{sub} {info.message}")

    if args.verbose:
        print(f"\nGenerating HR data...")
        print(f"  Employees: {args.employees}")
        print(f"  Date range: {start_date} to {end_date}")
        print(f"  Attrition: {args.attrition_rate:.0%} (noise: {args.noise_std})")
        print(f"  Hiring: {'enabled' if args.include_hiring else 'disabled'}")
        print()

    # Generate data
    data = generate_hr_data(
        n_employees=args.employees,
        start_date=start_date,
        end_date=end_date,
        seed=args.seed,
        include_performance=not args.no_performance,
        include_compensation=not args.no_compensation,
        include_attrition=not args.no_attrition,
        include_hiring=args.include_hiring,
        attrition_rate=args.attrition_rate,
        noise_std=args.noise_std,
        base_growth_rate=args.base_growth_rate,
        backfill_rate=args.backfill_rate,
        bu_distribution=bu_distribution,
        bu_growth_rates=bu_growth_rates,
        progress_callback=progress_callback if args.verbose else None,
    )

    return data


# =============================================================================
# DATABASE OPERATIONS
# =============================================================================

def get_connection():
    """Create database connection."""
    password = os.environ.get("HR_DB_PASSWORD")
    if not password:
        raise ValueError(
            "HR_DB_PASSWORD environment variable not set.\n"
            "Set it with: export HR_DB_PASSWORD='your_password'\n"
            "Or create a .env file with: HR_DB_PASSWORD='your_password'"
        )

    return psycopg2.connect(**DB_CONFIG, password=password)


def truncate_tables(cursor, verbose: bool = False):
    """Truncate all tables in reverse order (respects FK constraints)."""
    if verbose:
        print("\nTruncating existing data...")

    # Truncate in reverse order to respect FK constraints
    for table in reversed(LOAD_ORDER):
        cursor.execute(f"TRUNCATE TABLE {table} CASCADE")
        if verbose:
            print(f"  Truncated: {table}")


def load_location(cursor, df, verbose: bool = False):
    """Load location reference data."""
    columns = ["location_id", "city", "country", "region", "latitude", "longitude"]
    values = [
        (
            row["location_id"],
            row["city"],
            row["country"],
            row.get("region", "APJ"),
            row.get("latitude"),
            row.get("longitude"),
        )
        for _, row in df.iterrows()
    ]

    execute_values(
        cursor,
        """INSERT INTO location (location_id, city, country, region, latitude, longitude)
           VALUES %s ON CONFLICT (location_id) DO NOTHING""",
        values,
        page_size=1000
    )

    if verbose:
        print(f"  Loaded location: {len(values)} rows")


def load_organization_unit(cursor, df, verbose: bool = False):
    """Load organization unit data (sorted by hierarchy)."""
    # Sort by parent_org_id to ensure parents are inserted before children
    # NULL parents first, then by parent_org_id
    df_sorted = df.copy()
    df_sorted["_sort_key"] = df_sorted["parent_org_id"].fillna("")
    df_sorted = df_sorted.sort_values("_sort_key")

    values = [
        (
            row["org_id"],
            row["org_name"],
            row["parent_org_id"] if row["parent_org_id"] and str(row["parent_org_id"]) != "nan" else None,
            row.get("cost_center"),
            row["business_unit"],
        )
        for _, row in df_sorted.iterrows()
    ]

    execute_values(
        cursor,
        """INSERT INTO organization_unit (org_id, org_name, parent_org_id, cost_center, business_unit)
           VALUES %s ON CONFLICT (org_id) DO NOTHING""",
        values,
        page_size=1000
    )

    if verbose:
        print(f"  Loaded organization_unit: {len(values)} rows")


def load_job_role(cursor, df, verbose: bool = False):
    """Load job role reference data."""
    values = [
        (
            row["job_id"],
            row["job_title"],
            row["job_family"],
            row["job_level"],
            int(row["seniority_level"]),
        )
        for _, row in df.iterrows()
    ]

    execute_values(
        cursor,
        """INSERT INTO job_role (job_id, job_title, job_family, job_level, seniority_level)
           VALUES %s ON CONFLICT (job_id) DO NOTHING""",
        values,
        page_size=1000
    )

    if verbose:
        print(f"  Loaded job_role: {len(values)} rows")


def load_employee(cursor, df, verbose: bool = False):
    """Load employee data using two-pass approach for self-referencing manager_id."""

    # Pass 1: Insert all employees with manager_id = NULL
    values = [
        (
            row["employee_id"],
            row["first_name"],
            row["last_name"],
            row.get("gender"),
            row["birth_date"],
            row["hire_date"],
            row["employment_type"],
            row.get("employment_status", "Active"),
            row["location_id"],
            None,  # manager_id set to NULL initially
            row.get("termination_date") if row.get("termination_date") and str(row.get("termination_date")) != "NaT" else None,
            row.get("termination_reason"),
        )
        for _, row in df.iterrows()
    ]

    execute_values(
        cursor,
        """INSERT INTO employee
           (employee_id, first_name, last_name, gender, birth_date, hire_date,
            employment_type, employment_status, location_id, manager_id,
            termination_date, termination_reason)
           VALUES %s""",
        values,
        page_size=1000
    )

    if verbose:
        print(f"  Loaded employee (pass 1): {len(values)} rows")

    # Pass 2: Update manager_id references
    manager_updates = [
        (row["manager_id"], row["employee_id"])
        for _, row in df.iterrows()
        if row.get("manager_id") and str(row.get("manager_id")) != "nan"
    ]

    if manager_updates:
        execute_values(
            cursor,
            """UPDATE employee SET manager_id = data.manager_id
               FROM (VALUES %s) AS data(manager_id, employee_id)
               WHERE employee.employee_id = data.employee_id""",
            manager_updates,
            page_size=1000
        )

        if verbose:
            print(f"  Updated employee manager_id: {len(manager_updates)} rows")


def load_employee_job_assignment(cursor, df, verbose: bool = False):
    """Load employee job assignment history."""
    values = [
        (
            row["employee_id"],
            row["job_id"],
            row["job_title"],
            row["job_family"],
            row["job_level"],
            int(row["seniority_level"]),
            row["start_date"],
            row["end_date"] if row.get("end_date") and str(row.get("end_date")) != "NaT" else None,
        )
        for _, row in df.iterrows()
    ]

    execute_values(
        cursor,
        """INSERT INTO employee_job_assignment
           (employee_id, job_id, job_title, job_family, job_level, seniority_level, start_date, end_date)
           VALUES %s""",
        values,
        page_size=1000
    )

    if verbose:
        print(f"  Loaded employee_job_assignment: {len(values)} rows")


def load_employee_org_assignment(cursor, df, verbose: bool = False):
    """Load employee org assignment history."""
    values = [
        (
            row["employee_id"],
            row["org_id"],
            row["org_name"],
            row.get("cost_center"),
            row["business_unit"],
            row["start_date"],
            row["end_date"] if row.get("end_date") and str(row.get("end_date")) != "NaT" else None,
        )
        for _, row in df.iterrows()
    ]

    execute_values(
        cursor,
        """INSERT INTO employee_org_assignment
           (employee_id, org_id, org_name, cost_center, business_unit, start_date, end_date)
           VALUES %s""",
        values,
        page_size=1000
    )

    if verbose:
        print(f"  Loaded employee_org_assignment: {len(values)} rows")


def load_employee_compensation(cursor, df, verbose: bool = False):
    """Load employee compensation history."""
    values = [
        (
            row["employee_id"],
            float(row["base_salary"]),
            float(row.get("bonus_target_pct", 0)),
            row.get("currency", "USD"),
            row["start_date"],
            row["end_date"] if row.get("end_date") and str(row.get("end_date")) != "NaT" else None,
            row.get("change_reason"),
        )
        for _, row in df.iterrows()
    ]

    execute_values(
        cursor,
        """INSERT INTO employee_compensation
           (employee_id, base_salary, bonus_target_pct, currency, start_date, end_date, change_reason)
           VALUES %s""",
        values,
        page_size=1000
    )

    if verbose:
        print(f"  Loaded employee_compensation: {len(values)} rows")


def load_employee_performance(cursor, df, verbose: bool = False):
    """Load employee performance reviews."""
    values = [
        (
            row["employee_id"],
            int(row["review_period_year"]),
            row["review_date"],
            int(row["rating"]),
            row["rating_label"],
            row.get("manager_id") if row.get("manager_id") and str(row.get("manager_id")) != "nan" else None,
        )
        for _, row in df.iterrows()
    ]

    execute_values(
        cursor,
        """INSERT INTO employee_performance
           (employee_id, review_period_year, review_date, rating, rating_label, manager_id)
           VALUES %s""",
        values,
        page_size=1000
    )

    if verbose:
        print(f"  Loaded employee_performance: {len(values)} rows")


def verify_counts(cursor, verbose: bool = False) -> dict:
    """Verify row counts in all tables."""
    counts = {}
    for table in LOAD_ORDER:
        cursor.execute(f"SELECT COUNT(*) FROM {table}")
        counts[table] = cursor.fetchone()[0]

    if verbose:
        print("\nDatabase row counts:")
        for table, count in counts.items():
            print(f"  {table}: {count:,} rows")

    return counts


# =============================================================================
# STREAMING MODE - CHECKPOINT MANAGEMENT
# =============================================================================

class CheckpointManager:
    """Manages checkpoint table for streaming load resumability."""

    # SQL to create checkpoint table (if not exists)
    CREATE_TABLE_SQL = """
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
    CREATE INDEX IF NOT EXISTS idx_checkpoint_session ON hr_data_load_checkpoint(load_session_id);
    CREATE INDEX IF NOT EXISTS idx_checkpoint_status ON hr_data_load_checkpoint(status);
    """

    def __init__(self, conn, session_id: str | None = None):
        """
        Initialize checkpoint manager.

        Args:
            conn: Database connection
            session_id: Existing session ID for resume, or None for new session
        """
        self.conn = conn
        self.cursor = conn.cursor()
        self.session_id = session_id or str(uuid.uuid4())
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Create checkpoint table if it doesn't exist."""
        self.cursor.execute(self.CREATE_TABLE_SQL)
        self.conn.commit()

    def create_session(self, config: dict, years: list[int]) -> str:
        """
        Create a new load session with checkpoints for each year.

        Args:
            config: Generation configuration to store for resume validation
            years: List of simulation years

        Returns:
            Session ID
        """
        config_json = json.dumps(config)

        for year in years:
            self.cursor.execute(
                """INSERT INTO hr_data_load_checkpoint
                   (load_session_id, simulation_year, status, config_snapshot)
                   VALUES (%s, %s, 'pending', %s)
                   ON CONFLICT (load_session_id, simulation_year) DO NOTHING""",
                (self.session_id, year, config_json)
            )

        self.conn.commit()
        return self.session_id

    def get_last_completed_year(self) -> int | None:
        """
        Get the last successfully completed year for this session.

        Returns:
            Last completed year, or None if no years completed
        """
        self.cursor.execute(
            """SELECT MAX(simulation_year) FROM hr_data_load_checkpoint
               WHERE load_session_id = %s AND status = 'completed'""",
            (self.session_id,)
        )
        result = self.cursor.fetchone()
        return result[0] if result and result[0] else None

    def get_config(self) -> dict | None:
        """
        Get the stored configuration for this session.

        Returns:
            Config dict, or None if session not found
        """
        self.cursor.execute(
            """SELECT config_snapshot FROM hr_data_load_checkpoint
               WHERE load_session_id = %s LIMIT 1""",
            (self.session_id,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else None

    def get_session_status(self) -> list[dict]:
        """
        Get status of all years in this session.

        Returns:
            List of dicts with year status information
        """
        self.cursor.execute(
            """SELECT simulation_year, status, employees_loaded, job_assignments_loaded,
                      org_assignments_loaded, compensation_loaded, performance_loaded,
                      started_at, completed_at, error_message
               FROM hr_data_load_checkpoint
               WHERE load_session_id = %s
               ORDER BY simulation_year""",
            (self.session_id,)
        )
        columns = [
            'year', 'status', 'employees', 'job_assignments', 'org_assignments',
            'compensation', 'performance', 'started_at', 'completed_at', 'error'
        ]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def mark_year_started(self, year: int):
        """Mark a year as in progress."""
        self.cursor.execute(
            """UPDATE hr_data_load_checkpoint
               SET status = 'in_progress', started_at = %s
               WHERE load_session_id = %s AND simulation_year = %s""",
            (datetime.now(), self.session_id, year)
        )

    def mark_year_completed(self, year: int, counts: dict):
        """
        Mark a year as completed with row counts.

        Args:
            year: Simulation year
            counts: Dict with row counts for each table
        """
        self.cursor.execute(
            """UPDATE hr_data_load_checkpoint
               SET status = 'completed',
                   completed_at = %s,
                   employees_loaded = %s,
                   job_assignments_loaded = %s,
                   org_assignments_loaded = %s,
                   compensation_loaded = %s,
                   performance_loaded = %s
               WHERE load_session_id = %s AND simulation_year = %s""",
            (
                datetime.now(),
                counts.get('employees', 0),
                counts.get('job_assignments', 0),
                counts.get('org_assignments', 0),
                counts.get('compensation', 0),
                counts.get('performance', 0),
                self.session_id,
                year
            )
        )

    def mark_year_failed(self, year: int, error: str):
        """Mark a year as failed with error message."""
        self.cursor.execute(
            """UPDATE hr_data_load_checkpoint
               SET status = 'failed', error_message = %s
               WHERE load_session_id = %s AND simulation_year = %s""",
            (error, self.session_id, year)
        )
        self.conn.commit()

    def session_exists(self) -> bool:
        """Check if this session exists in the database."""
        self.cursor.execute(
            """SELECT COUNT(*) FROM hr_data_load_checkpoint
               WHERE load_session_id = %s""",
            (self.session_id,)
        )
        return self.cursor.fetchone()[0] > 0


def load_chunk(cursor, chunk: YearlyDataChunk, verbose: bool = False) -> dict:
    """
    Load a single yearly data chunk into the database.

    Args:
        cursor: Database cursor
        chunk: YearlyDataChunk to load
        verbose: Print progress messages

    Returns:
        Dict with row counts for each loaded table
    """
    counts = {}

    # Load reference data (only in initial year)
    if chunk.is_initial_year:
        if chunk.location is not None:
            load_location(cursor, chunk.location, verbose)
            counts['location'] = len(chunk.location)
        if chunk.organization_unit is not None:
            load_organization_unit(cursor, chunk.organization_unit, verbose)
            counts['organization_unit'] = len(chunk.organization_unit)
        if chunk.job_role is not None:
            load_job_role(cursor, chunk.job_role, verbose)
            counts['job_role'] = len(chunk.job_role)

    # For streaming mode with workforce dynamics, we need to handle
    # the cumulative nature of the data differently
    # The chunk contains ALL employees up to this point, so we use upsert logic

    # Load employees (upsert for streaming mode)
    if len(chunk.employees) > 0:
        load_employee_streaming(cursor, chunk.employees, verbose)
        counts['employees'] = len(chunk.employees)

    # Load job assignments (delete and reinsert for simplicity)
    if len(chunk.job_assignments) > 0:
        load_job_assignment_streaming(cursor, chunk.job_assignments, verbose)
        counts['job_assignments'] = len(chunk.job_assignments)

    # Load org assignments
    if len(chunk.org_assignments) > 0:
        load_org_assignment_streaming(cursor, chunk.org_assignments, verbose)
        counts['org_assignments'] = len(chunk.org_assignments)

    # Load compensation
    if chunk.compensation is not None and len(chunk.compensation) > 0:
        load_compensation_streaming(cursor, chunk.compensation, verbose)
        counts['compensation'] = len(chunk.compensation)

    # Load performance (only in final year)
    if chunk.performance is not None and len(chunk.performance) > 0:
        load_performance_streaming(cursor, chunk.performance, verbose)
        counts['performance'] = len(chunk.performance)

    return counts


def load_employee_streaming(cursor, df, verbose: bool = False):
    """Load employees with upsert logic for streaming mode."""
    # Use INSERT ... ON CONFLICT DO UPDATE for upsert
    values = [
        (
            row["employee_id"],
            row["first_name"],
            row["last_name"],
            row.get("gender"),
            row["birth_date"],
            row["hire_date"],
            row["employment_type"],
            row.get("employment_status", "Active"),
            row["location_id"],
            row.get("termination_date") if row.get("termination_date") and str(row.get("termination_date")) != "NaT" else None,
            row.get("termination_reason"),
        )
        for _, row in df.iterrows()
    ]

    execute_values(
        cursor,
        """INSERT INTO employee
           (employee_id, first_name, last_name, gender, birth_date, hire_date,
            employment_type, employment_status, location_id,
            termination_date, termination_reason)
           VALUES %s
           ON CONFLICT (employee_id) DO UPDATE SET
               employment_status = EXCLUDED.employment_status,
               termination_date = EXCLUDED.termination_date,
               termination_reason = EXCLUDED.termination_reason,
               updated_at = CURRENT_TIMESTAMP""",
        values,
        page_size=1000
    )

    # Update manager_id references
    manager_updates = [
        (row["manager_id"], row["employee_id"])
        for _, row in df.iterrows()
        if row.get("manager_id") and str(row.get("manager_id")) != "nan"
    ]

    if manager_updates:
        execute_values(
            cursor,
            """UPDATE employee SET manager_id = data.manager_id
               FROM (VALUES %s) AS data(manager_id, employee_id)
               WHERE employee.employee_id = data.employee_id""",
            manager_updates,
            page_size=1000
        )

    if verbose:
        print(f"    Upserted employee: {len(values)} rows")


def load_job_assignment_streaming(cursor, df, verbose: bool = False):
    """Load job assignments for streaming mode (clear and reload)."""
    # Get unique employee IDs in this chunk
    employee_ids = df["employee_id"].unique().tolist()

    # Delete existing assignments for these employees
    cursor.execute(
        "DELETE FROM employee_job_assignment WHERE employee_id = ANY(%s)",
        (employee_ids,)
    )

    # Insert all assignments
    load_employee_job_assignment(cursor, df, verbose)


def load_org_assignment_streaming(cursor, df, verbose: bool = False):
    """Load org assignments for streaming mode (clear and reload)."""
    # Get unique employee IDs in this chunk
    employee_ids = df["employee_id"].unique().tolist()

    # Delete existing assignments for these employees
    cursor.execute(
        "DELETE FROM employee_org_assignment WHERE employee_id = ANY(%s)",
        (employee_ids,)
    )

    # Insert all assignments
    load_employee_org_assignment(cursor, df, verbose)


def load_compensation_streaming(cursor, df, verbose: bool = False):
    """Load compensation for streaming mode (clear and reload)."""
    # Get unique employee IDs in this chunk
    employee_ids = df["employee_id"].unique().tolist()

    # Delete existing compensation for these employees
    cursor.execute(
        "DELETE FROM employee_compensation WHERE employee_id = ANY(%s)",
        (employee_ids,)
    )

    # Insert all compensation records
    load_employee_compensation(cursor, df, verbose)


def load_performance_streaming(cursor, df, verbose: bool = False):
    """Load performance for streaming mode (clear and reload)."""
    # Get unique employee IDs in this chunk
    employee_ids = df["employee_id"].unique().tolist()

    # Delete existing performance for these employees
    cursor.execute(
        "DELETE FROM employee_performance WHERE employee_id = ANY(%s)",
        (employee_ids,)
    )

    # Insert all performance records
    load_employee_performance(cursor, df, verbose)


def streaming_load(args: argparse.Namespace) -> int:
    """
    Execute streaming load with year-by-year commits and checkpoint support.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Calculate date range
    end_date = date.today() if args.end_date is None else date.fromisoformat(args.end_date)
    start_date = (
        end_date - timedelta(days=args.years * 365)
        if args.start_date is None
        else date.fromisoformat(args.start_date)
    )
    years = list(range(start_date.year, end_date.year + 1))

    # Build configuration dict
    config = {
        "n_employees": args.employees,
        "start_date": str(start_date),
        "end_date": str(end_date),
        "seed": args.seed,
        "include_performance": not args.no_performance,
        "include_compensation": not args.no_compensation,
        "include_attrition": not args.no_attrition,
        "include_hiring": args.include_hiring,
        "attrition_rate": args.attrition_rate,
        "noise_std": args.noise_std,
        "base_growth_rate": args.base_growth_rate,
        "backfill_rate": args.backfill_rate,
        "bu_distribution": {
            "Engineering": args.engineering_pct,
            "Sales": args.sales_pct,
            "Corporate": args.corporate_pct,
        },
        "bu_growth_rates": {
            "Engineering": args.engineering_growth,
            "Sales": args.sales_growth,
            "Corporate": args.corporate_growth,
        },
    }

    # Connect to database
    conn = get_connection()
    cursor = conn.cursor()

    # Initialize checkpoint manager
    checkpoint = CheckpointManager(conn, args.session_id)
    session_id = checkpoint.session_id

    # Track for signal handler
    current_year = None
    interrupted = False

    def sigint_handler(signum, frame):
        nonlocal interrupted
        interrupted = True
        print(f"\n\n⚠️  Interrupted!")
        print(f"To resume: python scripts/load_hr_data.py --resume --session-id {session_id}")
        conn.rollback()
        sys.exit(1)

    signal.signal(signal.SIGINT, sigint_handler)

    try:
        # Resume mode: validate config and find last completed year
        if args.resume:
            if not checkpoint.session_exists():
                print(f"ERROR: Session {session_id} not found")
                return 1

            stored_config = checkpoint.get_config()
            last_completed = checkpoint.get_last_completed_year()

            # Validate critical config matches
            if stored_config:
                if stored_config.get('seed') != args.seed and args.seed is not None:
                    print(f"WARNING: Seed mismatch. Stored: {stored_config.get('seed')}, Provided: {args.seed}")
                    print("Using stored seed for deterministic resume.")

                # Use stored config for generation
                config = stored_config

            print(f"\n[Session: {session_id}] Resuming streaming load...")
            if last_completed:
                print(f"Last completed year: {last_completed}")
            else:
                print("No years completed yet.")
        else:
            # New session
            if args.truncate:
                truncate_tables(cursor, args.verbose)
                conn.commit()

            checkpoint.create_session(config, years)
            print(f"\n[Session: {session_id}] Starting streaming load...")

        print(f"Years to process: {years[0]} - {years[-1]}")
        print()

        # Generate data in streaming mode
        last_completed = checkpoint.get_last_completed_year() if args.resume else None

        generator = generate_hr_data_streaming(
            n_employees=config["n_employees"],
            start_date=config["start_date"],
            end_date=config["end_date"],
            seed=config["seed"],
            include_performance=config["include_performance"],
            include_compensation=config["include_compensation"],
            include_attrition=config["include_attrition"],
            include_hiring=config["include_hiring"],
            attrition_rate=config["attrition_rate"],
            noise_std=config["noise_std"],
            bu_distribution=config["bu_distribution"],
            base_growth_rate=config["base_growth_rate"],
            backfill_rate=config["backfill_rate"],
            bu_growth_rates=config["bu_growth_rates"],
        )

        for chunk in generator:
            current_year = chunk.year

            # Skip already completed years on resume
            if last_completed and chunk.year <= last_completed:
                print(f"Year {chunk.year}: Skipping (already loaded) ✓")
                continue

            try:
                checkpoint.mark_year_started(chunk.year)

                if args.verbose:
                    print(f"\nYear {chunk.year}:")
                    print(f"  Headcount: {chunk.active_headcount:,}")
                    print(f"  New hires: {chunk.new_hires_count:,}")
                    print(f"  Terminations: {chunk.terminations_count:,}")

                # Load chunk data
                counts = load_chunk(cursor, chunk, args.verbose)

                # Mark year complete and commit
                checkpoint.mark_year_completed(chunk.year, counts)
                conn.commit()

                # Print summary
                status = "✓" if not chunk.is_final_year else "✓ (final)"
                print(f"Year {chunk.year}: {chunk.active_headcount:,} active employees, "
                      f"+{chunk.new_hires_count:,} hires, -{chunk.terminations_count:,} terms {status}")

            except Exception as e:
                conn.rollback()
                checkpoint.mark_year_failed(chunk.year, str(e))
                print(f"\nERROR loading year {chunk.year}: {e}")
                print(f"To resume: python scripts/load_hr_data.py --resume --session-id {session_id}")
                return 1

        # Verify final counts
        print("\n" + "-" * 40)
        verify_counts(cursor, verbose=True)

        print("\n" + "=" * 60)
        print(f"Streaming load completed successfully!")
        print(f"Session ID: {session_id}")
        print("=" * 60)

        return 0

    except Exception as e:
        print(f"\nERROR: {e}")
        if not interrupted:
            conn.rollback()
            if current_year:
                checkpoint.mark_year_failed(current_year, str(e))
        print(f"To resume: python scripts/load_hr_data.py --resume --session-id {session_id}")
        return 1

    finally:
        cursor.close()
        conn.close()


def show_session_status(args: argparse.Namespace) -> int:
    """
    Show status of a load session.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    conn = get_connection()

    try:
        checkpoint = CheckpointManager(conn, args.session_id)

        if not checkpoint.session_exists():
            print(f"Session {args.session_id} not found")
            return 1

        status = checkpoint.get_session_status()
        config = checkpoint.get_config()

        print(f"\nSession: {args.session_id}")
        print("=" * 60)

        if config:
            print(f"Employees: {config.get('n_employees', 'N/A')}")
            print(f"Date range: {config.get('start_date')} to {config.get('end_date')}")
            print(f"Seed: {config.get('seed', 'None')}")
            print()

        print(f"{'Year':<8} {'Status':<12} {'Employees':<10} {'Jobs':<8} {'Orgs':<8} {'Comp':<8} {'Perf':<8}")
        print("-" * 60)

        for row in status:
            print(f"{row['year']:<8} {row['status']:<12} {row['employees']:<10} "
                  f"{row['job_assignments']:<8} {row['org_assignments']:<8} "
                  f"{row['compensation']:<8} {row['performance']:<8}")

            if row['error']:
                print(f"         Error: {row['error'][:50]}...")

        # Summary
        completed = sum(1 for r in status if r['status'] == 'completed')
        failed = sum(1 for r in status if r['status'] == 'failed')
        pending = sum(1 for r in status if r['status'] == 'pending')

        print("-" * 60)
        print(f"Summary: {completed} completed, {failed} failed, {pending} pending")

        if failed > 0 or pending > 0:
            print(f"\nTo resume: python scripts/load_hr_data.py --resume --session-id {args.session_id}")

        return 0

    finally:
        conn.close()


# =============================================================================
# MAIN EXECUTION
# =============================================================================

def main():
    """Main execution flow."""
    args = parse_args()

    print("=" * 60)
    print("HR Data Loader")
    print("=" * 60)

    # Handle status command
    if args.status:
        return show_session_status(args)

    # Handle streaming mode (including resume)
    if args.streaming or args.resume:
        return streaming_load(args)

    # -------------------------------------------------------------------------
    # Batch mode (original behavior)
    # -------------------------------------------------------------------------

    # Step 1: Generate data
    print("\n[1/3] Generating HR data...")
    data = generate_data(args)

    # Show generated data summary
    print("\nGenerated data summary:")
    for table_name, df in data.items():
        print(f"  {table_name}: {len(df):,} rows")

    # Dry run: stop here
    if args.dry_run:
        print("\n[DRY RUN] Skipping database insertion.")
        print("=" * 60)
        return 0

    # Step 2: Connect and load
    print("\n[2/3] Loading data into PostgreSQL...")
    if args.verbose:
        print(f"  Host: {DB_CONFIG['host']}")
        print(f"  Database: {DB_CONFIG['database']}")
        print(f"  User: {DB_CONFIG['user']}")

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Test connection
        cursor.execute("SELECT version();")
        pg_version = cursor.fetchone()[0]
        if args.verbose:
            print(f"  Connected: {pg_version.split(',')[0]}")

        # Truncate if requested
        if args.truncate:
            truncate_tables(cursor, args.verbose)

        # Load tables in order
        print("\nLoading tables...")

        load_location(cursor, data["location"], args.verbose)
        load_organization_unit(cursor, data["organization_unit"], args.verbose)
        load_job_role(cursor, data["job_role"], args.verbose)
        load_employee(cursor, data["employee"], args.verbose)
        load_employee_job_assignment(cursor, data["employee_job_assignment"], args.verbose)
        load_employee_org_assignment(cursor, data["employee_org_assignment"], args.verbose)

        if "employee_compensation" in data and not args.no_compensation:
            load_employee_compensation(cursor, data["employee_compensation"], args.verbose)

        if "employee_performance" in data and not args.no_performance:
            load_employee_performance(cursor, data["employee_performance"], args.verbose)

        # Commit transaction
        conn.commit()
        print("\nTransaction committed successfully.")

        # Step 3: Verify
        print("\n[3/3] Verifying data...")
        verify_counts(cursor, verbose=True)

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"\nERROR: {e}")
        if 'conn' in locals():
            conn.rollback()
            print("Transaction rolled back.")
            conn.close()
        return 1

    print("\n" + "=" * 60)
    print("Data load completed successfully!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

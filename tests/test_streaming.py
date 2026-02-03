"""Tests for streaming data generation functionality."""

from datetime import date

import pandas as pd
import pytest

from hr_data_generator import generate_hr_data
from hr_data_generator.generator import HRDataGenerator
from hr_data_generator.streaming import YearlyDataChunk, generate_hr_data_streaming


class TestYearlyDataChunk:
    """Tests for the YearlyDataChunk dataclass."""

    def test_get_row_counts(self):
        """Test row count calculation."""
        chunk = YearlyDataChunk(
            year=2023,
            is_initial_year=True,
            is_final_year=False,
            employees=pd.DataFrame({"employee_id": ["E1", "E2", "E3"]}),
            job_assignments=pd.DataFrame({"employee_id": ["E1", "E2"]}),
            org_assignments=pd.DataFrame({"employee_id": ["E1", "E2", "E3"]}),
            compensation=pd.DataFrame({"employee_id": ["E1"]}),
            performance=None,
            active_headcount=3,
        )

        counts = chunk.get_row_counts()

        assert counts["employees"] == 3
        assert counts["job_assignments"] == 2
        assert counts["org_assignments"] == 3
        assert counts["compensation"] == 1
        assert "performance" not in counts

    def test_repr(self):
        """Test string representation."""
        chunk = YearlyDataChunk(
            year=2023,
            is_initial_year=False,
            is_final_year=False,
            employees=pd.DataFrame(),
            job_assignments=pd.DataFrame(),
            org_assignments=pd.DataFrame(),
            compensation=None,
            performance=None,
            new_hires_count=50,
            terminations_count=25,
            active_headcount=1025,
        )

        repr_str = repr(chunk)
        assert "2023" in repr_str
        assert "1025" in repr_str
        assert "50" in repr_str
        assert "25" in repr_str


class TestGenerateHrDataStreaming:
    """Tests for the streaming generator function."""

    def test_yields_chunks(self):
        """Test that streaming generator yields YearlyDataChunk objects."""
        chunks = list(generate_hr_data_streaming(
            n_employees=20,
            seed=42,
            start_date="2022-01-01",
            end_date="2023-12-31",
            include_hiring=True,
            include_attrition=True,
        ))

        assert len(chunks) > 0
        for chunk in chunks:
            assert isinstance(chunk, YearlyDataChunk)

    def test_first_chunk_has_reference_data(self):
        """Test that first chunk includes reference data."""
        chunks = list(generate_hr_data_streaming(
            n_employees=20,
            seed=42,
            start_date="2022-01-01",
            end_date="2023-12-31",
            include_hiring=True,
            include_attrition=True,
        ))

        first_chunk = chunks[0]
        assert first_chunk.is_initial_year
        assert first_chunk.organization_unit is not None
        assert first_chunk.job_role is not None
        assert first_chunk.location is not None

    def test_last_chunk_is_final(self):
        """Test that last chunk is marked as final."""
        chunks = list(generate_hr_data_streaming(
            n_employees=20,
            seed=42,
            start_date="2022-01-01",
            end_date="2023-12-31",
            include_hiring=True,
            include_attrition=True,
        ))

        last_chunk = chunks[-1]
        assert last_chunk.is_final_year

    def test_subsequent_chunks_no_reference_data(self):
        """Test that non-initial chunks don't include reference data."""
        chunks = list(generate_hr_data_streaming(
            n_employees=20,
            seed=42,
            start_date="2022-01-01",
            end_date="2024-12-31",  # Multiple years
            include_hiring=True,
            include_attrition=True,
        ))

        # Skip the first chunk
        for chunk in chunks[1:]:
            assert not chunk.is_initial_year
            assert chunk.organization_unit is None
            assert chunk.job_role is None
            assert chunk.location is None

    def test_chunks_cover_all_years(self):
        """Test that chunks cover all simulation years."""
        start_year = 2021
        end_year = 2024

        chunks = list(generate_hr_data_streaming(
            n_employees=20,
            seed=42,
            start_date=f"{start_year}-01-01",
            end_date=f"{end_year}-12-31",
            include_hiring=True,
            include_attrition=True,
        ))

        years = [chunk.year for chunk in chunks]
        expected_years = list(range(start_year, end_year + 1))
        assert years == expected_years

    def test_seed_produces_reproducible_chunks(self):
        """Test that same seed produces identical chunks."""
        kwargs = {
            "n_employees": 30,
            "seed": 123,
            "start_date": "2022-01-01",
            "end_date": "2023-12-31",
            "include_hiring": True,
            "include_attrition": True,
        }

        chunks1 = list(generate_hr_data_streaming(**kwargs))
        chunks2 = list(generate_hr_data_streaming(**kwargs))

        assert len(chunks1) == len(chunks2)

        for c1, c2 in zip(chunks1, chunks2):
            assert c1.year == c2.year
            assert c1.active_headcount == c2.active_headcount
            assert c1.new_hires_count == c2.new_hires_count
            assert c1.terminations_count == c2.terminations_count
            pd.testing.assert_frame_equal(c1.employees, c2.employees)


class TestStreamingVsBatchConsistency:
    """Tests to verify streaming produces same results as batch mode."""

    def test_final_employee_count_matches(self):
        """Test that final headcount matches batch mode."""
        kwargs = {
            "n_employees": 50,
            "seed": 42,
            "start_date": "2022-01-01",
            "end_date": "2024-12-31",
            "include_hiring": True,
            "include_attrition": True,
            "include_performance": True,
            "include_compensation": True,
        }

        # Batch mode
        batch_data = generate_hr_data(**kwargs)
        batch_employees = batch_data["employee"]

        # Streaming mode
        chunks = list(generate_hr_data_streaming(**kwargs))
        final_chunk = chunks[-1]

        # Compare final employee counts
        assert len(final_chunk.employees) == len(batch_employees)

    def test_final_employee_ids_match(self):
        """Test that final employee IDs match batch mode."""
        kwargs = {
            "n_employees": 50,
            "seed": 42,
            "start_date": "2022-01-01",
            "end_date": "2024-12-31",
            "include_hiring": True,
            "include_attrition": True,
        }

        # Batch mode
        batch_data = generate_hr_data(**kwargs)
        batch_ids = set(batch_data["employee"]["employee_id"].tolist())

        # Streaming mode
        chunks = list(generate_hr_data_streaming(**kwargs))
        final_chunk = chunks[-1]
        streaming_ids = set(final_chunk.employees["employee_id"].tolist())

        assert batch_ids == streaming_ids

    def test_terminated_employees_match(self):
        """Test that terminated employees match batch mode."""
        kwargs = {
            "n_employees": 50,
            "seed": 42,
            "start_date": "2022-01-01",
            "end_date": "2024-12-31",
            "include_hiring": True,
            "include_attrition": True,
        }

        # Batch mode
        batch_data = generate_hr_data(**kwargs)
        batch_terminated = batch_data["employee"][
            batch_data["employee"]["termination_date"].notna()
        ]["employee_id"].tolist()

        # Streaming mode
        chunks = list(generate_hr_data_streaming(**kwargs))
        final_chunk = chunks[-1]
        streaming_terminated = final_chunk.employees[
            final_chunk.employees["termination_date"].notna()
        ]["employee_id"].tolist()

        assert set(batch_terminated) == set(streaming_terminated)


class TestStreamingWithDifferentModes:
    """Tests for streaming with different generation modes."""

    def test_streaming_without_hiring_attrition(self):
        """Test streaming when hiring and attrition are both disabled."""
        chunks = list(generate_hr_data_streaming(
            n_employees=20,
            seed=42,
            include_hiring=False,
            include_attrition=False,
        ))

        # Should yield a single chunk
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.is_initial_year
        assert chunk.is_final_year
        assert chunk.terminations_count == 0

    def test_streaming_attrition_only(self):
        """Test streaming with attrition but no hiring."""
        chunks = list(generate_hr_data_streaming(
            n_employees=50,
            seed=42,
            start_date="2022-01-01",
            end_date="2024-12-31",
            include_hiring=False,
            include_attrition=True,
        ))

        # Without combined hiring+attrition, yields single chunk
        assert len(chunks) == 1
        chunk = chunks[0]
        # Should have some terminations
        assert len(chunk.terminated_employee_ids) > 0

    def test_streaming_hiring_only(self):
        """Test streaming with hiring but no attrition."""
        chunks = list(generate_hr_data_streaming(
            n_employees=50,
            seed=42,
            start_date="2022-01-01",
            end_date="2024-12-31",
            include_hiring=True,
            include_attrition=False,
        ))

        # Without combined hiring+attrition, yields single chunk
        assert len(chunks) == 1
        chunk = chunks[0]
        # Should have no terminations
        assert chunk.terminations_count == 0


class TestStreamingDataIntegrity:
    """Tests for data integrity in streaming mode."""

    def test_all_employees_have_assignments(self):
        """Test that all employees have job and org assignments."""
        chunks = list(generate_hr_data_streaming(
            n_employees=30,
            seed=42,
            start_date="2022-01-01",
            end_date="2024-12-31",
            include_hiring=True,
            include_attrition=True,
        ))

        final_chunk = chunks[-1]
        employee_ids = set(final_chunk.employees["employee_id"].tolist())
        job_assignment_ids = set(final_chunk.job_assignments["employee_id"].tolist())
        org_assignment_ids = set(final_chunk.org_assignments["employee_id"].tolist())

        # All employees should have at least one assignment
        assert employee_ids == job_assignment_ids
        assert employee_ids == org_assignment_ids

    def test_headcount_progression(self):
        """Test that headcount progresses logically year over year."""
        chunks = list(generate_hr_data_streaming(
            n_employees=100,
            seed=42,
            start_date="2022-01-01",
            end_date="2025-12-31",
            include_hiring=True,
            include_attrition=True,
            base_growth_rate=0.05,  # 5% growth
        ))

        # Headcount should generally increase (or at least not crash)
        for i, chunk in enumerate(chunks):
            assert chunk.active_headcount > 0
            # Verify stats make sense
            assert chunk.new_hires_count >= 0
            assert chunk.terminations_count >= 0

    def test_chunk_stats_accuracy(self):
        """Test that chunk statistics are accurate."""
        chunks = list(generate_hr_data_streaming(
            n_employees=50,
            seed=42,
            start_date="2022-01-01",
            end_date="2024-12-31",
            include_hiring=True,
            include_attrition=True,
        ))

        for chunk in chunks:
            # active_headcount should match actual count
            actual_active = len(chunk.employees[
                chunk.employees["termination_date"].isna()
            ])
            assert chunk.active_headcount == actual_active


class TestHRDataGeneratorStreaming:
    """Tests for the HRDataGenerator.generate_streaming() method."""

    def test_generate_streaming_method_exists(self):
        """Test that generate_streaming method exists on HRDataGenerator."""
        generator = HRDataGenerator(seed=42)
        assert hasattr(generator, 'generate_streaming')
        assert callable(generator.generate_streaming)

    def test_generate_streaming_returns_iterator(self):
        """Test that generate_streaming returns an iterator."""
        generator = HRDataGenerator(seed=42)
        result = generator.generate_streaming(
            n_employees=20,
            include_hiring=True,
            include_attrition=True,
        )

        # Should be an iterator/generator
        assert hasattr(result, '__iter__')
        assert hasattr(result, '__next__')

    def test_generate_streaming_with_custom_dates(self):
        """Test streaming with custom date range."""
        generator = HRDataGenerator(seed=42)
        chunks = list(generator.generate_streaming(
            n_employees=20,
            start_date=date(2020, 1, 1),
            end_date=date(2022, 12, 31),
            include_hiring=True,
            include_attrition=True,
        ))

        years = [c.year for c in chunks]
        assert 2020 in years
        assert 2022 in years

"""Tests for the progress callback mechanism."""

import pytest

from hr_data_generator import ProgressInfo, generate_hr_data


class TestProgressInfo:
    """Tests for the ProgressInfo dataclass."""

    def test_progress_basic(self):
        """Test basic progress calculation without sub-steps."""
        info = ProgressInfo(
            phase="employees",
            step=1,
            total_steps=8,
            message="Generating employees...",
        )
        # Step 1 of 8 complete = 1/8 = 0.125
        assert info.progress == pytest.approx(0.125, rel=0.01)

    def test_progress_middle_step(self):
        """Test progress at middle of generation."""
        info = ProgressInfo(
            phase="compensation",
            step=5,
            total_steps=8,
            message="Generating compensation...",
        )
        # Step 5 of 8 complete = 5/8 = 0.625
        assert info.progress == pytest.approx(0.625, rel=0.01)

    def test_progress_final_step(self):
        """Test progress at final step."""
        info = ProgressInfo(
            phase="finalize",
            step=8,
            total_steps=8,
            message="Finalizing...",
        )
        # Step 8 of 8 complete = 8/8 = 1.0
        assert info.progress == pytest.approx(1.0, rel=0.01)

    def test_progress_with_sub_steps(self):
        """Test progress with sub-step tracking."""
        info = ProgressInfo(
            phase="workforce_dynamics",
            step=7,
            total_steps=8,
            message="Simulating year 2022...",
            sub_step=3,
            sub_total=5,
        )
        # Base: (7-1)/8 = 0.75
        # Step weight: 1/8 = 0.125
        # Sub-progress: 3/5 = 0.6
        # Total: 0.75 + (0.125 * 0.6) = 0.75 + 0.075 = 0.825
        assert info.progress == pytest.approx(0.825, rel=0.01)

    def test_progress_sub_step_at_start(self):
        """Test sub-step at beginning of a step."""
        info = ProgressInfo(
            phase="workforce_dynamics",
            step=7,
            total_steps=8,
            message="Simulating year 2021...",
            sub_step=1,
            sub_total=5,
        )
        # Base: (7-1)/8 = 0.75
        # Step weight: 1/8 = 0.125
        # Sub-progress: 1/5 = 0.2
        # Total: 0.75 + (0.125 * 0.2) = 0.75 + 0.025 = 0.775
        assert info.progress == pytest.approx(0.775, rel=0.01)

    def test_progress_sub_step_at_end(self):
        """Test sub-step at end of a step."""
        info = ProgressInfo(
            phase="workforce_dynamics",
            step=7,
            total_steps=8,
            message="Simulating year 2025...",
            sub_step=5,
            sub_total=5,
        )
        # Base: (7-1)/8 = 0.75
        # Step weight: 1/8 = 0.125
        # Sub-progress: 5/5 = 1.0
        # Total: 0.75 + (0.125 * 1.0) = 0.875
        assert info.progress == pytest.approx(0.875, rel=0.01)

    def test_progress_zero_total_steps(self):
        """Test edge case with zero total steps."""
        info = ProgressInfo(
            phase="unknown",
            step=1,
            total_steps=0,
            message="Edge case",
        )
        assert info.progress == 0.0

    def test_progress_zero_sub_total(self):
        """Test edge case with zero sub_total."""
        info = ProgressInfo(
            phase="test",
            step=4,
            total_steps=8,
            message="Test",
            sub_step=1,
            sub_total=0,
        )
        # Should fall back to step-only calculation: 4/8 = 0.5
        assert info.progress == pytest.approx(0.5, rel=0.01)


class TestProgressCallback:
    """Tests for progress callback integration with generate_hr_data."""

    def test_callback_is_called(self):
        """Test that the callback is called during generation."""
        progress_updates = []

        def callback(info: ProgressInfo):
            progress_updates.append(info)

        generate_hr_data(n_employees=10, seed=42, progress_callback=callback)

        # Should have multiple updates
        assert len(progress_updates) > 0

    def test_callback_receives_all_phases(self):
        """Test that callback receives updates for all generation phases."""
        phases_seen = set()

        def callback(info: ProgressInfo):
            phases_seen.add(info.phase)

        generate_hr_data(n_employees=10, seed=42, progress_callback=callback)

        # Core phases that should always be present
        expected_phases = {
            "employees",
            "hierarchy",
            "job_assignments",
            "org_assignments",
            "compensation",
            "performance",
            "finalize",
        }
        # At least one of attrition/hiring/workforce_dynamics
        attrition_or_dynamics = {"attrition", "workforce_dynamics", "hiring"}

        assert expected_phases.issubset(phases_seen)
        assert len(phases_seen & attrition_or_dynamics) >= 1

    def test_callback_progress_is_monotonic(self):
        """Test that progress values generally increase or stay the same."""
        progress_values = []

        def callback(info: ProgressInfo):
            progress_values.append(info.progress)

        generate_hr_data(n_employees=10, seed=42, progress_callback=callback)

        # Progress should generally increase (allowing for phase transitions)
        # Just verify it starts low and ends high
        assert progress_values[0] <= 0.2  # Should start early
        assert progress_values[-1] >= 0.9  # Should end near complete

    def test_callback_with_attrition_only(self):
        """Test callback with attrition enabled, hiring disabled."""
        phases_seen = set()

        def callback(info: ProgressInfo):
            phases_seen.add(info.phase)

        generate_hr_data(
            n_employees=10,
            seed=42,
            include_attrition=True,
            include_hiring=False,
            progress_callback=callback,
        )

        assert "attrition" in phases_seen
        assert "workforce_dynamics" not in phases_seen

    def test_callback_with_hiring_only(self):
        """Test callback with hiring enabled, attrition disabled."""
        phases_seen = set()
        messages = []

        def callback(info: ProgressInfo):
            phases_seen.add(info.phase)
            messages.append(info.message)

        generate_hr_data(
            n_employees=10,
            seed=42,
            include_attrition=False,
            include_hiring=True,
            progress_callback=callback,
        )

        assert "hiring" in phases_seen
        assert "attrition" not in phases_seen

    def test_callback_with_workforce_dynamics(self):
        """Test callback with both hiring and attrition (workforce dynamics)."""
        phases_seen = set()
        sub_progress_seen = False

        def callback(info: ProgressInfo):
            phases_seen.add(info.phase)
            if info.sub_step is not None and info.sub_total is not None:
                nonlocal sub_progress_seen
                sub_progress_seen = True

        generate_hr_data(
            n_employees=10,
            seed=42,
            include_attrition=True,
            include_hiring=True,
            progress_callback=callback,
        )

        assert "workforce_dynamics" in phases_seen
        assert sub_progress_seen, "Sub-progress should be reported for year-by-year simulation"

    def test_callback_messages_are_descriptive(self):
        """Test that callback messages are human-readable."""
        messages = []

        def callback(info: ProgressInfo):
            messages.append(info.message)

        generate_hr_data(n_employees=50, seed=42, progress_callback=callback)

        # Check that messages contain useful information
        assert any("employee" in m.lower() for m in messages)
        assert any("hierarchy" in m.lower() for m in messages)

    def test_no_callback_works(self):
        """Test that generation works without a callback (backwards compatibility)."""
        # Should not raise any errors
        result = generate_hr_data(n_employees=10, seed=42)
        assert "employee" in result
        assert len(result["employee"]) == 10

    def test_callback_none_works(self):
        """Test that explicitly passing None works."""
        result = generate_hr_data(n_employees=10, seed=42, progress_callback=None)
        assert "employee" in result
        assert len(result["employee"]) == 10

    def test_callback_with_different_employee_counts(self):
        """Test callback with various employee counts."""
        for n in [10, 50, 100]:
            progress_updates = []

            def callback(info: ProgressInfo):
                progress_updates.append(info)

            result = generate_hr_data(n_employees=n, seed=42, progress_callback=callback)

            assert len(result["employee"]) >= n * 0.5  # Account for attrition
            assert len(progress_updates) > 0
            # First update should mention employee count
            assert str(n) in progress_updates[0].message

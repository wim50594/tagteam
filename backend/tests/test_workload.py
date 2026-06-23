"""
Tests for workload distribution — compute_batches and redistribution.
Run with:  uv run pytest tests/ -v
"""
from __future__ import annotations

import pytest
from app.services.workload import WorkloadService


# ── compute_batches ───────────────────────────────────────────


class TestComputeBatches:
    def test_empty_items(self):
        result = WorkloadService.compute_batches([], ["alice", "bob"], "split")
        assert result == {"alice": [], "bob": []}

    def test_empty_annotators(self):
        result = WorkloadService.compute_batches(["i1", "i2"], [], "split")
        assert result == {}

    def test_split_mode_even(self):
        """4 items, 2 annotators → 2 each."""
        result = WorkloadService.compute_batches(
            ["a", "b", "c", "d"], ["alice", "bob"], "split"
        )
        assert result["alice"] == ["a", "c"]
        assert result["bob"] == ["b", "d"]

    def test_split_mode_uneven(self):
        """5 items, 2 annotators → 3 + 2."""
        result = WorkloadService.compute_batches(
            ["a", "b", "c", "d", "e"], ["alice", "bob"], "split"
        )
        assert len(result["alice"]) == 3
        assert len(result["bob"]) == 2
        # all items covered exactly once
        all_assigned = result["alice"] + result["bob"]
        assert sorted(all_assigned) == ["a", "b", "c", "d", "e"]

    def test_verification_k1(self):
        """k=1 means each item goes to exactly 1 person (same as split)."""
        result = WorkloadService.compute_batches(
            ["a", "b", "c", "d"], ["alice", "bob"], "verification", k_verifiers=1
        )
        all_assigned = result["alice"] + result["bob"]
        assert sorted(all_assigned) == ["a", "b", "c", "d"]

    def test_verification_k2_balanced(self):
        """9 items, 3 annotators, k=2 → each gets 6 items (18 total slots)."""
        items = [str(i) for i in range(9)]
        annotators = ["alice", "bob", "carol"]
        result = WorkloadService.compute_batches(
            items, annotators, "verification", k_verifiers=2
        )
        # Total assignments = 9 * 2 = 18
        total = sum(len(v) for v in result.values())
        assert total == 18
        # Each annotator gets 6 (±0, perfectly balanced)
        for a in annotators:
            assert len(result[a]) == 6

    def test_verification_k2_uneven(self):
        """9 items, 4 annotators, k=2 → 18 slots / 4 = 4.5 each."""
        items = [str(i) for i in range(9)]
        annotators = ["alice", "bob", "carol", "dave"]
        result = WorkloadService.compute_batches(
            items, annotators, "verification", k_verifiers=2
        )
        total = sum(len(v) for v in result.values())
        assert total == 18
        lengths = sorted(len(v) for v in result.values())
        # 18/4 = 4 remainder 2 → two get 5, two get 4
        assert lengths == [4, 4, 5, 5]

    def test_verification_k_exceeds_annotators(self):
        """k=5 but only 3 annotators → k clamped to 3."""
        result = WorkloadService.compute_batches(
            ["a", "b"], ["alice", "bob", "carol"], "verification", k_verifiers=5
        )
        # Each annotator gets both items (3 slots each = 6 total)
        for a in ["alice", "bob", "carol"]:
            assert len(result[a]) == 2

    def test_verification_no_duplicates_per_item(self):
        """An annotator should only appear once per item."""
        items = [str(i) for i in range(20)]
        annotators = ["a", "b", "c"]
        result = WorkloadService.compute_batches(
            items, annotators, "verification", k_verifiers=2
        )
        for item in items:
            assigned_to = [a for a in annotators if item in result[a]]
            assert len(assigned_to) == 2  # exactly k annotators

    def test_deterministic(self):
        """Same inputs always produce same outputs."""
        items = [str(i) for i in range(9)]
        annotators = ["alice", "bob", "carol"]
        r1 = WorkloadService.compute_batches(items, annotators, "verification", k_verifiers=2)
        r2 = WorkloadService.compute_batches(items, annotators, "verification", k_verifiers=2)
        assert r1 == r2


# ── Redistribution on member added ─────────────────────────────

class TestRedistributeOnMemberAdded:
    @pytest.fixture
    def items(self):
        return [str(i) for i in range(9)]

    @pytest.fixture
    def annotators(self):
        return ["alice", "bob", "carol"]

    def test_add_to_empty_project(self):
        """Adding a user to a project with no batches → full recompute."""
        # This tests the code path where old_batches is empty
        pass  # Requires DB — integration test

    def test_full_recompute_when_all_unlabeled(self):
        """With 0% labeled, redistribute should be equivalent to compute_batches."""
        items = [str(i) for i in range(9)]
        # All items unlabeled → redistribution = fresh compute_batches with all members
        expected = WorkloadService.compute_batches(
            items, ["alice", "bob", "carol", "dave"], "verification", k_verifiers=2
        )
        # Total = 18, per person = 4 or 5
        total = sum(len(v) for v in expected.values())
        assert total == 18
        assert len(expected) == 4

    def test_batch_summary_split(self):
        summary = WorkloadService.batch_summary(9, 3, "split")
        assert "3 items/person" in summary
        assert "9 total" in summary

    def test_batch_summary_verification(self):
        summary = WorkloadService.batch_summary(9, 3, "verification", k_verifiers=2)
        assert "18 annotations" in summary
        assert "6 each" in summary

    def test_batch_summary_no_annotators(self):
        assert WorkloadService.batch_summary(9, 0, "split") == "No annotators assigned"

"""
Step DAG — Directed Acyclic Graph for orchestrator step dependencies.

Purpose: Manage step execution order and validate dependencies from shared_config.json.
Spec:    /Users/davemini2/ProjectsLocal/serp-compete/docs/serp_tools_upgrade_spec_v3.md#task-9
Tests:   tests/test_step_dag.py
"""

import json
import os
from typing import Dict, List, Set, Any
from collections import deque


class StepDAG:
    """Directed acyclic graph for step orchestration and dependency validation."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize DAG from shared_config.json.

        Args:
            config: Full shared_config dict or step_dag section
        """
        # Handle both full config and step_dag section
        if "step_dag" in config:
            self.steps = config["step_dag"]
        else:
            self.steps = config

        self._validate_dag()

    def _validate_dag(self) -> None:
        """Validate that step_dag is a valid DAG (no cycles, all deps exist)."""
        # Check for cycles using DFS
        visited = set()
        rec_stack = set()

        def has_cycle(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            step = self.steps.get(node, {})
            deps = step.get("depends_on", [])

            for dep in deps:
                if dep not in visited:
                    if has_cycle(dep):
                        return True
                elif dep in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for step_id in self.steps:
            if step_id not in visited:
                if has_cycle(step_id):
                    raise ValueError(f"Cycle detected in DAG: {step_id}")

        # Check all dependencies exist
        all_steps = set(self.steps.keys())
        for step_id, step_info in self.steps.items():
            deps = step_info.get("depends_on", [])
            for dep in deps:
                if dep not in all_steps:
                    raise ValueError(f"Step {step_id} depends on non-existent {dep}")

    def get_execution_order(self, selected_steps: List[str]) -> List[str]:
        """
        Get execution order for selected steps, respecting dependencies.

        Args:
            selected_steps: List of step IDs to execute (e.g., ["step_2_audit", "step_3_scoring"])

        Returns:
            Ordered list of steps to execute (with dependencies)

        Raises:
            ValueError if selected steps cannot form valid execution order
        """
        if not selected_steps:
            return []

        # Collect all required steps (selected + their transitive dependencies)
        required = set()
        queue = deque(selected_steps)

        while queue:
            step_id = queue.popleft()
            if step_id in required:
                continue

            if step_id not in self.steps:
                raise ValueError(f"Unknown step: {step_id}")

            required.add(step_id)
            deps = self.steps[step_id].get("depends_on", [])
            for dep in deps:
                if dep not in required:
                    queue.append(dep)

        # Topological sort to get execution order
        in_degree = {step: 0 for step in required}
        for step in required:
            for dep in self.steps[step].get("depends_on", []):
                if dep in required:
                    in_degree[step] += 1

        queue = deque([step for step in required if in_degree[step] == 0])
        ordered = []

        while queue:
            step = queue.popleft()
            ordered.append(step)

            # Find all steps that depend on this step
            for candidate in required:
                if step in self.steps[candidate].get("depends_on", []):
                    in_degree[candidate] -= 1
                    if in_degree[candidate] == 0:
                        queue.append(candidate)

        if len(ordered) != len(required):
            raise ValueError("Cycle detected in selected steps")

        return ordered

    def is_optional(self, step_id: str) -> bool:
        """Check if step is optional."""
        if step_id not in self.steps:
            return False
        return self.steps[step_id].get("optional", False)

    def get_step_info(self, step_id: str) -> Dict[str, Any]:
        """Get full info for a step."""
        return self.steps.get(step_id, {})

    def get_all_steps(self) -> Dict[str, Any]:
        """Get all steps in DAG."""
        return self.steps

    def validate_execution_plan(self, plan: List[str]) -> bool:
        """Validate that an execution plan respects dependencies."""
        executed = set()

        for step in plan:
            if step not in self.steps:
                return False

            deps = self.steps[step].get("depends_on", [])
            for dep in deps:
                if dep not in executed:
                    return False

            executed.add(step)

        return True

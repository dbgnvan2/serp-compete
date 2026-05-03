"""Tests for step DAG module."""

import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Serp-compete'))

from src.step_dag import StepDAG


@pytest.fixture
def valid_dag_config():
    """Valid step DAG configuration."""
    return {
        "step_1_mining": {"name": "Mining", "depends_on": [], "optional": True},
        "step_2_audit": {"name": "Audit", "depends_on": ["step_1_mining"], "optional": False},
        "step_3_scoring": {"name": "Scoring", "depends_on": ["step_2_audit"], "optional": False},
        "step_4_gsc": {"name": "GSC", "depends_on": [], "optional": True},
        "step_5_strike": {"name": "Strike", "depends_on": ["step_4_gsc"], "optional": True},
    }


def test_dag_initialization(valid_dag_config):
    """Test DAG initializes correctly."""
    dag = StepDAG(valid_dag_config)
    assert dag is not None
    assert len(dag.get_all_steps()) == 5


def test_dag_with_config_section(valid_dag_config):
    """Test DAG accepts full config dict with step_dag key."""
    config = {"step_dag": valid_dag_config, "other_key": "value"}
    dag = StepDAG(config)
    assert len(dag.get_all_steps()) == 5


def test_execution_order_single_step(valid_dag_config):
    """Test execution order for single step includes dependencies."""
    dag = StepDAG(valid_dag_config)
    order = dag.get_execution_order(["step_2_audit"])
    assert order == ["step_1_mining", "step_2_audit"]


def test_execution_order_transitive_deps(valid_dag_config):
    """Test execution order resolves transitive dependencies."""
    dag = StepDAG(valid_dag_config)
    order = dag.get_execution_order(["step_3_scoring"])
    assert order == ["step_1_mining", "step_2_audit", "step_3_scoring"]


def test_execution_order_independent_branches(valid_dag_config):
    """Test execution order handles independent branches."""
    dag = StepDAG(valid_dag_config)
    order = dag.get_execution_order(["step_5_strike"])
    assert "step_4_gsc" in order
    assert "step_5_strike" in order
    assert order.index("step_4_gsc") < order.index("step_5_strike")


def test_execution_order_multiple_steps(valid_dag_config):
    """Test execution order for multiple user-selected steps."""
    dag = StepDAG(valid_dag_config)
    order = dag.get_execution_order(["step_3_scoring", "step_5_strike"])
    # Should include all deps from both branches
    assert "step_1_mining" in order
    assert "step_2_audit" in order
    assert "step_3_scoring" in order
    assert "step_4_gsc" in order
    assert "step_5_strike" in order


def test_is_optional(valid_dag_config):
    """Test optional step detection."""
    dag = StepDAG(valid_dag_config)
    assert dag.is_optional("step_1_mining") is True
    assert dag.is_optional("step_2_audit") is False
    assert dag.is_optional("step_4_gsc") is True


def test_validate_execution_plan_valid(valid_dag_config):
    """Test validation passes for valid plan."""
    dag = StepDAG(valid_dag_config)
    plan = ["step_1_mining", "step_2_audit", "step_3_scoring"]
    assert dag.validate_execution_plan(plan) is True


def test_validate_execution_plan_invalid_order(valid_dag_config):
    """Test validation fails for invalid order."""
    dag = StepDAG(valid_dag_config)
    plan = ["step_3_scoring", "step_2_audit", "step_1_mining"]
    assert dag.validate_execution_plan(plan) is False


def test_get_step_info(valid_dag_config):
    """Test retrieving step information."""
    dag = StepDAG(valid_dag_config)
    info = dag.get_step_info("step_2_audit")
    assert info["name"] == "Audit"
    assert info["depends_on"] == ["step_1_mining"]
    assert info["optional"] is False


def test_dag_with_missing_dependency():
    """Test DAG raises error for missing dependency."""
    bad_config = {
        "step_1": {"depends_on": ["step_999"], "optional": False}
    }
    with pytest.raises(ValueError, match="non-existent"):
        StepDAG(bad_config)


def test_dag_with_cycle():
    """Test DAG raises error for circular dependencies."""
    bad_config = {
        "step_1": {"depends_on": ["step_2"]},
        "step_2": {"depends_on": ["step_1"]},
    }
    with pytest.raises(ValueError, match="Cycle"):
        StepDAG(bad_config)


def test_execution_order_with_nonexistent_step(valid_dag_config):
    """Test execution order raises error for non-existent step."""
    dag = StepDAG(valid_dag_config)
    with pytest.raises(ValueError, match="Unknown step"):
        dag.get_execution_order(["step_999"])

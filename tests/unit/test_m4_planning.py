import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from src.workflows.planning.state import PlanningState
from src.workflows.planning.agents.pattern_selector import PatternSelectorAgent
from src.workflows.planning.agents.researcher import ResearcherAgent
from src.workflows.planning.agents.architect import ArchitectAgent
from src.workflows.planning.agents.planner import PlannerAgent
from src.workflows.planning.agents.critic import CriticAgent


class TestPlanningState:
    def test_state_schema_has_required_fields(self):
        required_fields = [
            "project_id", "run_id", "messages",
            "requirements_md", "requirements_json",
            "selected_patterns", "pattern_rationale",
            "research_findings", "research_log",
            "architecture_md", "architecture_json",
            "tasks", "task_validation",
            "current_phase", "iteration_count", "max_iterations",
            "feedback", "error", "approval_result",
        ]
        for field in required_fields:
            assert field in PlanningState.__annotations__


class TestPatternSelectorAgent:
    @pytest.mark.asyncio
    async def test_select_patterns_with_rules(self):
        agent = PatternSelectorAgent()
        agent.llm = None

        state = {
            "project_id": "test-project",
            "requirements_json": {
                "functional_requirements": [
                    {"id": "FR-001", "title": "User Management", "content": "Users can register and login"},
                    {"id": "FR-002", "title": "Data Storage", "content": "Store data in database"},
                ],
            },
        }

        with patch.object(agent, '_select_with_rules') as mock_rules:
            mock_rules.return_value = {
                "selected_patterns": [
                    {"name": "ReAct", "rationale": "For reasoning", "requirement_mapping": ["FR-001"]},
                ],
                "overall_rationale": "Selected for reasoning capabilities",
            }

            result = await agent.select_patterns(state)

            assert "selected_patterns" in result
            assert "pattern_rationale" in result
            assert result["current_phase"] == "patterns_selected"

    def test_build_search_query(self):
        agent = PatternSelectorAgent()
        requirements_json = {
            "functional_requirements": [
                {"id": "FR-001", "title": "Auth", "content": "User authentication"},
            ],
            "non_functional_requirements": [
                {"id": "NFR-001", "title": "Performance"},
            ],
        }

        query = agent._build_search_query(requirements_json)
        assert isinstance(query, str)
        assert len(query) > 0


class TestResearcherAgent:
    @pytest.mark.asyncio
    async def test_research_with_fallback(self):
        agent = ResearcherAgent()
        agent.llm = None

        state = {
            "project_id": "test-project",
            "requirements_json": {
                "functional_requirements": [
                    {"id": "FR-001", "title": "Feature", "content": "Test feature"},
                ],
            },
            "selected_patterns": [{"name": "ReAct"}],
        }

        with patch.object(agent, '_research_documents', new_callable=AsyncMock) as mock_doc:
            mock_doc.return_value = [{"id": "doc_1", "claim": "Test", "source_type": "doc"}]

            with patch.object(agent, '_research_knowledge_base', new_callable=AsyncMock) as mock_kb:
                mock_kb.return_value = [{"id": "kb_1", "claim": "Test", "source_type": "kb"}]

                with patch.object(agent, '_research_web', new_callable=AsyncMock) as mock_web:
                    mock_web.return_value = []

                    result = await agent.research(state)

                    assert "research_findings" in result
                    assert "research_log" in result
                    assert result["current_phase"] == "research_complete"


class TestArchitectAgent:
    @pytest.mark.asyncio
    async def test_design_architecture_without_llm(self):
        agent = ArchitectAgent()
        agent.llm = None

        state = {
            "requirements_json": {
                "functional_requirements": [
                    {"id": "FR-001", "title": "Feature", "content": "Test feature"},
                ],
            },
            "selected_patterns": [{"name": "ReAct", "rationale": "For reasoning"}],
            "research_findings": [],
        }

        result = await agent.design_architecture(state)

        assert "architecture_md" in result
        assert "architecture_json" in result
        assert result["current_phase"] == "architecture_designed"
        assert isinstance(result["architecture_json"], dict)
        assert "components" in result["architecture_json"]


class TestPlannerAgent:
    @pytest.mark.asyncio
    async def test_create_task_plan_without_llm(self):
        agent = PlannerAgent()
        agent.llm = None

        state = {
            "requirements_json": {
                "functional_requirements": [
                    {"id": "FR-001", "title": "Feature", "content": "Test feature"},
                ],
            },
            "architecture_json": {"components": [{"name": "Comp1"}]},
            "selected_patterns": [{"name": "ReAct"}],
        }

        result = await agent.create_task_plan(state)

        assert "tasks" in result
        assert result["current_phase"] == "tasks_planned"
        assert len(result["tasks"]) > 0
        assert all("task_id" in t for t in result["tasks"])


class TestCriticAgent:
    @pytest.mark.asyncio
    async def test_validate_plan_without_llm(self):
        agent = CriticAgent()
        agent.llm = None

        state = {
            "tasks": [
                {
                    "task_id": "task_001",
                    "title": "Task 1",
                    "description": "Test task",
                    "dependencies": [],
                    "pattern_refs": ["ReAct"],
                },
            ],
            "requirements_json": {
                "functional_requirements": [
                    {"id": "FR-001", "title": "Feature", "content": "Test"},
                ],
            },
            "selected_patterns": [{"name": "ReAct"}],
        }

        result = await agent.validate_plan(state)

        assert "task_validation" in result
        assert result["current_phase"] == "validation_complete"
        assert "valid" in result["task_validation"]
        assert "score" in result["task_validation"]


class TestGraphBuilding:
    @pytest.mark.asyncio
    async def test_build_planning_graph(self):
        from src.workflows.planning.graph import build_planning_graph

        graph = await build_planning_graph()

        assert graph is not None
        assert hasattr(graph, 'ainvoke')
        assert hasattr(graph, 'aget_state')

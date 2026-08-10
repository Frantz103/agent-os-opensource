from __future__ import annotations

import inspect

from nooa import Agent

from agent_os.definitions import BuilderAgent, CoordinatorAgent, PlannerAgent, ReviewerAgent
from agent_os.models import FinalOutcome, ReviewVerdict, TaskPlan, WorkResult


def test_roles_are_nooa_agents_with_typed_generation_contracts() -> None:
    expectations = {
        CoordinatorAgent: ("orchestrate", FinalOutcome),
        PlannerAgent: ("plan", TaskPlan),
        BuilderAgent: ("execute", WorkResult),
        ReviewerAgent: ("review", ReviewVerdict),
    }
    for agent_type, (method_name, return_type) in expectations.items():
        assert issubclass(agent_type, Agent)
        signature = inspect.signature(getattr(agent_type, method_name))
        assert signature.return_annotation in {return_type, return_type.__name__}
        assert inspect.getdoc(agent_type)

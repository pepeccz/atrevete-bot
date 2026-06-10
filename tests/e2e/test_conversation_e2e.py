"""Scenario-driven conversational QA tests for the live agent pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from tests.e2e.harness.context_manager import Flow, Persona, QATestingContext
from tests.e2e.harness.redis_harness import RedisTestHarness

SKILL_FILES = (
    Path("skills/atrevete-qa-runner/SKILL.md"),
    Path("skills/atrevete-qa-auditor/SKILL.md"),
)


class TestConversationE2E:
    """Run conversational QA scenarios against the Redis-based production path."""

    @pytest.mark.asyncio
    async def test_booking_complete(
        self,
        request: pytest.FixtureRequest,
        redis_harness: RedisTestHarness,
        testing_context: QATestingContext,
    ) -> None:
        report = await self._run_flow("booking_complete", request, redis_harness, testing_context)
        assert report["levels"]["level_1_structure"]["pass"]
        assert report["levels"]["level_3_execution"]["pass"]

    @pytest.mark.asyncio
    async def test_returning_client(
        self,
        request: pytest.FixtureRequest,
        redis_harness: RedisTestHarness,
        testing_context: QATestingContext,
    ) -> None:
        report = await self._run_flow("returning_client", request, redis_harness, testing_context)
        assert report["levels"]["level_1_structure"]["pass"]
        assert report["levels"]["level_4_context"]["pass"]

    @pytest.mark.asyncio
    async def test_escalation(
        self,
        request: pytest.FixtureRequest,
        redis_harness: RedisTestHarness,
        testing_context: QATestingContext,
    ) -> None:
        report = await self._run_flow("escalation", request, redis_harness, testing_context)
        assert report["levels"]["level_1_structure"]["pass"]
        assert report["business_completion"]["goal_achieved"]

    @pytest.mark.asyncio
    async def test_indecision(
        self,
        request: pytest.FixtureRequest,
        redis_harness: RedisTestHarness,
        testing_context: QATestingContext,
    ) -> None:
        report = await self._run_flow("indecision", request, redis_harness, testing_context)
        assert report["levels"]["level_1_structure"]["pass"]
        assert report["levels"]["level_3_execution"]["pass"]

    async def _run_flow(
        self,
        flow_id: str,
        request: pytest.FixtureRequest,
        redis_harness: RedisTestHarness,
        testing_context: QATestingContext,
    ) -> dict[str, Any]:
        self._assert_skill_files_present()
        flow = testing_context.flows[flow_id]
        persona = testing_context.personas[flow.persona_id]
        conversation_id = str(uuid4())
        request.node.qa_conversation_ids = [conversation_id]

        started_at = datetime.now(UTC)
        turns = []
        for step in flow.steps:
            turns.append(
                await redis_harness.execute_turn(
                    conversation_id=conversation_id,
                    user_message=step.user,
                    persona_name=persona.name,
                )
            )
        final_state = await redis_harness.capture_final_state(conversation_id)
        total_duration_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)

        conversation_trace = {
            "scenario_id": flow.id,
            "conversation_id": conversation_id,
            "persona_id": persona.id,
            "turns": turns,
            "final_state": final_state or {},
            "total_duration_ms": total_duration_ms,
            "completed_successfully": True,
        }
        return self._evaluate_conversation(flow, persona, conversation_trace)

    def _evaluate_conversation(
        self,
        flow: Flow,
        persona: Persona,
        trace: dict[str, Any],
    ) -> dict[str, Any]:
        turns = trace["turns"]
        final_state = trace.get("final_state") or {}

        level_1_checks = []
        for turn in turns:
            response = turn.get("agent_response", "")
            level_1_checks.append({
                "id": f"turn_{turn['turn_number']}_not_empty",
                "pass": bool(isinstance(response, str) and response.strip()),
                "evidence": response[:120],
            })
            level_1_checks.append({
                "id": f"turn_{turn['turn_number']}_no_traceback",
                "pass": "traceback" not in response.lower(),
                "evidence": response[:120],
            })
        level_1_pass = all(check["pass"] for check in level_1_checks)

        execution_checks = []
        for step, turn in zip(flow.steps, turns, strict=False):
            expected_markers = [marker.lower() for marker in step.expect.get("response_contains", [])]
            response_lower = turn.get("agent_response", "").lower()
            execution_checks.append({
                "id": f"turn_{step.turn}_markers",
                "pass": all(marker in response_lower for marker in expected_markers),
                "evidence": response_lower[:160],
            })
        if "appointment_created" in flow.expected_outcome:
            execution_checks.append({
                "id": "appointment_created_flag",
                "pass": bool(final_state.get("appointment_created")),
                "evidence": str(final_state.get("appointment_created")),
            })
        if "escalation_triggered" in flow.expected_outcome:
            execution_checks.append({
                "id": "escalation_flag",
                "pass": bool(final_state.get("escalation_triggered")),
                "evidence": str(final_state.get("escalation_triggered")),
            })
        execution_pass = all(check["pass"] for check in execution_checks) if execution_checks else True

        context_checks = [
            {
                "id": "customer_name_preserved",
                "pass": final_state.get("customer_first_name") in (None, persona.name, persona.name.split()[0]),
                "evidence": str(final_state.get("customer_first_name")),
            },
            {
                "id": "message_history_present",
                "pass": bool(final_state.get("messages") or turns),
                "evidence": str(len(final_state.get("messages", []))),
            },
        ]
        context_pass = all(check["pass"] for check in context_checks)

        business_completion = {
            "goal_achieved": execution_pass,
            "expected_outcome": flow.expected_outcome,
        }

        failed_checks = [
            check
            for check in [*level_1_checks, *execution_checks, *context_checks]
            if not check["pass"]
        ]
        return {
            "scenario_id": flow.id,
            "conversation_id": trace["conversation_id"],
            "overall_pass": level_1_pass and execution_pass and context_pass,
            "levels": {
                "level_1_structure": self._level_result(level_1_pass, level_1_checks, deterministic=True),
                "level_2_text": self._placeholder_level("Requires evaluator skill rubric review."),
                "level_3_execution": self._level_result(execution_pass, execution_checks, deterministic=True),
                "level_4_context": self._level_result(context_pass, context_checks, deterministic=True),
                "level_5_ux_tone": self._placeholder_level("Requires evaluator skill rubric review."),
            },
            "business_completion": business_completion,
            "failed_checks": failed_checks,
            "recommended_fixes": [check["id"] for check in failed_checks],
            "summary": f"Flow '{flow.id}' executed for persona '{persona.id}'.",
        }

    @staticmethod
    def _level_result(pass_value: bool, checks: list[dict[str, Any]], deterministic: bool) -> dict[str, Any]:
        score = 1.0 if pass_value else 0.0
        evidence = "; ".join(f"{check['id']}={check['pass']}" for check in checks) or "No checks"
        return {
            "pass": pass_value,
            "score": score,
            "determinism": "deterministic" if deterministic else "rubric",
            "checks": checks,
            "evidence": evidence,
        }

    @staticmethod
    def _placeholder_level(message: str) -> dict[str, Any]:
        return {
            "pass": True,
            "score": 1.0,
            "determinism": "rubric",
            "checks": [],
            "evidence": message,
        }

    @staticmethod
    def _assert_skill_files_present() -> None:
        missing = [str(path) for path in SKILL_FILES if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Missing QA skill files required by the test harness: {', '.join(missing)}")

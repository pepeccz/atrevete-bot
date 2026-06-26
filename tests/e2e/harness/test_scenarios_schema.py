"""
Tests for REQ-H4: scenarios-v2.yaml contains >= 4 reschedule/cancel scenarios.

T17a: Count of entries with tags containing 'reschedule' OR 'cancel' is >= 4.
T17b: All phones in both YAML files start with +34999.
T17c: All phones across both files are unique (no duplicates).
T17d: All expect.outcome values are in the canonical v1+v2 enum.
T17e: New phones for reschedule/cancel scenarios are in range +34999000041..+34999000044.

TDD: T17a and T17e FAIL before T18 because scenarios-v2.yaml currently has 0
reschedule/cancel entries using phones 041..044.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HARNESS_DIR = Path(__file__).parent
SCENARIOS_V1 = HARNESS_DIR / "scenarios.yaml"
SCENARIOS_V2 = HARNESS_DIR / "scenarios-v2.yaml"

# ---------------------------------------------------------------------------
# Canonical outcome enum (v1 + v2)
# ---------------------------------------------------------------------------

CANONICAL_OUTCOMES = {
    # v1 core
    "booked",
    "cancelled",
    "rescheduled",
    "escalated",
    "policy_accepted",
    "rejected",
    "timeout",
    "error",
    "stuck",
    # v2 extension
    "info_provided",
    "multi_completed",
    "partial_completed",
    "out_of_scope_handled",
}


def _load_yaml(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or []


def _has_tag(scenario: dict, tag: str) -> bool:
    tags = scenario.get("tags", []) or []
    return any(tag in str(t).lower() for t in tags)


class TestScenariosSchemaV2:
    """T17: scenarios-v2.yaml structural invariants."""

    def setup_method(self) -> None:
        self.v1_scenarios = _load_yaml(SCENARIOS_V1)
        self.v2_scenarios = _load_yaml(SCENARIOS_V2)
        self.all_scenarios = self.v1_scenarios + self.v2_scenarios

    def test_at_least_4_reschedule_or_cancel_entries(self) -> None:
        """T17a: v2 must have >= 4 scenarios tagged 'reschedule' or 'cancel'."""
        count = sum(
            1 for s in self.v2_scenarios if _has_tag(s, "reschedule") or _has_tag(s, "cancel")
        )
        assert count >= 4, (
            f"Expected >= 4 reschedule/cancel scenarios in scenarios-v2.yaml, found {count}. "
            "Change H requires adding 4 scenarios covering: own-appointment lookup, reschedule, "
            "cancel-single, cancel-and-rebook."
        )

    def test_all_phones_start_with_34999(self) -> None:
        """T17b: Every phone in both scenario files must start with +34999."""
        bad = []
        for s in self.all_scenarios:
            phone = s.get("persona", {}).get("phone", "")
            if phone and not str(phone).startswith("+34999"):
                bad.append((s.get("id"), phone))
        assert not bad, f"Phones not starting with +34999: {bad}"

    def test_all_phones_unique(self) -> None:
        """T17c: No two scenarios share the same phone number."""
        phones = [
            s.get("persona", {}).get("phone", "")
            for s in self.all_scenarios
            if s.get("persona", {}).get("phone")
        ]
        duplicates = [p for p in phones if phones.count(p) > 1]
        assert not duplicates, f"Duplicate phones found: {set(duplicates)}"

    def test_all_outcomes_in_canonical_enum(self) -> None:
        """T17d: All expect.outcome values must be in the canonical enum."""
        bad = []
        for s in self.all_scenarios:
            outcome = (s.get("expect") or {}).get("outcome")
            if outcome and outcome not in CANONICAL_OUTCOMES:
                bad.append((s.get("id"), outcome))
        assert not bad, (
            f"Non-canonical outcomes found: {bad}. " f"Allowed values: {sorted(CANONICAL_OUTCOMES)}"
        )

    def test_new_reschedule_cancel_phones_in_41_to_44_range(self) -> None:
        """T17e: The 4 new reschedule/cancel scenarios use phones +34999000041..044."""
        expected_phones = {
            "+34999000041",
            "+34999000042",
            "+34999000043",
            "+34999000044",
        }
        v2_phones = {
            s.get("persona", {}).get("phone", "")
            for s in self.v2_scenarios
            if _has_tag(s, "reschedule") or _has_tag(s, "cancel")
        }
        missing = expected_phones - v2_phones
        assert not missing, (
            f"Expected phones {missing} to be in reschedule/cancel scenarios. "
            "Change H requires phones +34999000041..+34999000044 for the 4 new scenarios."
        )

    def test_reschedule_scenarios_have_manage_appointments_tool(self) -> None:
        """H4-S2: Reschedule scenarios must require manage_appointments tool."""
        reschedule_scenarios = [s for s in self.v2_scenarios if _has_tag(s, "reschedule")]
        for s in reschedule_scenarios:
            required_tools = (s.get("expect") or {}).get("tool_calls_required", []) or []
            assert "manage_appointments" in required_tools, (
                f"Scenario '{s.get('id')}' tagged 'reschedule' must require manage_appointments tool. "
                f"Got: {required_tools}"
            )

    def test_cancel_scenarios_have_correct_db_status(self) -> None:
        """H4-S3: Cancel scenarios must have db_appointment.status == 'cancelled'."""
        cancel_single_scenarios = [
            s
            for s in self.v2_scenarios
            if _has_tag(s, "cancel") and (s.get("expect") or {}).get("outcome") == "cancelled"
        ]
        for s in cancel_single_scenarios:
            db_appt = (s.get("expect") or {}).get("db_appointment") or {}
            assert db_appt.get("status") == "cancelled", (
                f"Scenario '{s.get('id')}' with outcome=cancelled must have "
                f"db_appointment.status='cancelled'. Got: {db_appt}"
            )

    def test_scenarios_v2_yaml_file_exists(self) -> None:
        """Sanity: scenarios-v2.yaml must exist and have entries."""
        assert SCENARIOS_V2.exists(), f"scenarios-v2.yaml not found at {SCENARIOS_V2}"
        assert len(self.v2_scenarios) > 0, "scenarios-v2.yaml is empty"

    # ------------------------------------------------------------------
    # Change L (L3) — cancel scenario calibration vs the 48h policy
    # ------------------------------------------------------------------

    def _get_scenario(self, scenario_id: str) -> dict:
        match = [s for s in self.v2_scenarios if s.get("id") == scenario_id]
        assert match, f"Scenario '{scenario_id}' not found in scenarios-v2.yaml"
        return match[0]

    def test_cancel_con_razon_seeds_appointment_outside_48h(self) -> None:
        """L3: cancel-con-razon must seed > 48h ahead so cancellation is allowed.

        QA V4 (run 20260609_183226): the seed sat inside the 48h window, the bot
        correctly escalated per policy, and the scenario perma-FAILed against
        expect.outcome=cancelled. The seed must move outside the window.
        """
        scenario = self._get_scenario("cancel-con-razon")
        seed = (scenario.get("seed") or {}).get("appointment") or {}
        days_ahead = seed.get("days_ahead")
        assert days_ahead is not None, (
            "cancel-con-razon must declare seed.appointment.days_ahead so the "
            "runner seeds the appointment deterministically"
        )
        assert (
            days_ahead >= 3
        ), f"cancel-con-razon seed must be > 48h ahead (days_ahead >= 3), got {days_ahead}"
        assert scenario["expect"]["outcome"] == "cancelled"

    def test_cancel_fuera_48h_seeds_appointment_inside_48h(self) -> None:
        """L3: sibling scenario cancel-fuera-48h seeds < 48h and expects escalation."""
        scenario = self._get_scenario("cancel-fuera-48h")
        seed = (scenario.get("seed") or {}).get("appointment") or {}
        days_ahead = seed.get("days_ahead")
        assert days_ahead is not None, "cancel-fuera-48h must declare seed.appointment.days_ahead"
        assert (
            days_ahead <= 1
        ), f"cancel-fuera-48h seed must be < 48h ahead (days_ahead <= 1), got {days_ahead}"
        assert (
            scenario["expect"]["outcome"] == "escalated"
        ), "cancel-fuera-48h must expect escalation (48h policy forbids self-service cancel)"
        db_appt = scenario["expect"].get("db_appointment") or {}
        assert db_appt.get("status") == "confirmed", (
            "cancel-fuera-48h appointment must remain confirmed (NOT cancelled): " f"{db_appt}"
        )

    def test_cancel_fuera_48h_uses_sandbox_phone(self) -> None:
        """L3: the new scenario uses a unique +34999 sandbox phone."""
        scenario = self._get_scenario("cancel-fuera-48h")
        phone = scenario["persona"]["phone"]
        assert phone.startswith("+34999"), f"Sandbox prefix required, got {phone}"
        all_phones = [
            s.get("persona", {}).get("phone", "")
            for s in self.all_scenarios
            if s.get("id") != "cancel-fuera-48h"
        ]
        assert phone not in all_phones, f"Phone {phone} already used by another scenario"

    def test_cancel_fuera_48h_requires_escalate_tool(self) -> None:
        """L3: escalation flow must require manage_appointments AND escalate.

        Mirrors the V4 evidence: manage_appointments found the appointment,
        the 48h policy blocked the cancel, then escalate fired.
        """
        scenario = self._get_scenario("cancel-fuera-48h")
        required = scenario["expect"].get("tool_calls_required") or []
        assert "manage_appointments" in required, f"Got: {required}"
        assert "escalate" in required, f"Got: {required}"

    # ------------------------------------------------------------------
    # Change M — audience-disambiguation guard scenarios
    # ------------------------------------------------------------------

    def test_audience_disambiguation_field_is_valid_when_present(self) -> None:
        """M1: expect.audience_disambiguation must be 'required' | 'not_required' when set."""
        valid_values = {"required", "not_required"}
        bad = []
        for s in self.all_scenarios:
            ad = (s.get("expect") or {}).get("audience_disambiguation")
            if ad is not None and ad not in valid_values:
                bad.append((s.get("id"), ad))
        assert not bad, (
            f"Invalid audience_disambiguation values: {bad}. "
            f"Allowed values: {sorted(valid_values)}"
        )

    def test_audience_disambiguation_scenarios_exist(self) -> None:
        """M2: Both audience-disambiguation guard scenarios must be present."""
        required_ids = {
            "audience-ambiguous-cold-open",
            "multi-service-multi-audience-cold-open",
        }
        found_ids = {s.get("id") for s in self.all_scenarios}
        missing = required_ids - found_ids
        assert not missing, (
            f"Required audience-disambiguation scenarios not found: {missing}. "
            "Change M requires both scenarios to exist in scenarios-v2.yaml."
        )

    def test_audience_disambiguation_scenarios_have_required_field(self) -> None:
        """M3: audience-disambiguation scenarios must declare audience_disambiguation=required."""
        scenario_ids = {
            "audience-ambiguous-cold-open",
            "multi-service-multi-audience-cold-open",
        }
        for s in self.all_scenarios:
            if s.get("id") in scenario_ids:
                ad = (s.get("expect") or {}).get("audience_disambiguation")
                assert ad == "required", (
                    f"Scenario '{s.get('id')}' must have "
                    f"expect.audience_disambiguation='required', got {ad!r}"
                )

    def test_audience_disambiguation_scenarios_use_sandbox_phones(self) -> None:
        """M4: audience-disambiguation scenarios must use phones in +34999000046..047 range."""
        expected_phones = {"+34999000046", "+34999000047"}
        ad_scenarios = [
            s
            for s in self.v2_scenarios
            if (s.get("expect") or {}).get("audience_disambiguation") == "required"
        ]
        found_phones = {s.get("persona", {}).get("phone", "") for s in ad_scenarios}
        missing = expected_phones - found_phones
        assert not missing, (
            f"Expected phones {missing} to be in audience-disambiguation scenarios. "
            "Change M requires phones +34999000046 and +34999000047."
        )

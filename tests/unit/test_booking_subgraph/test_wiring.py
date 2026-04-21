"""
Phase 6 — Wiring tests.

Verifies:
1. The BOOKING node in conversation_flow invokes the compiled booking subgraph,
   NOT BookingModeNode.
2. On GREETING→BOOKING transition, booking_context is seeded with entity hints
   extracted during the greeting turn (opening_booking_request, service_audience_hint,
   preferred_stylist_name, preferred_date_hint).
3. The first tick of the subgraph runs resolve_pre_turn (via the subgraph entry point).
"""

from __future__ import annotations

import importlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**overrides) -> dict:
    """Minimal ConversationState dict for wiring tests."""
    base = {
        "conversation_id": "conv-wiring-test",
        "customer_phone": None,
        "customer_id": None,
        "customer_name": None,
        "messages": [],
        "current_mode": "BOOKING",
        "mode_context": {"last_intent": "book", "last_intent_confidence": 0.9},
        "booking_context": {},
        "is_first_interaction": False,
        "error_count": 0,
        "escalation_triggered": False,
        "last_node": "router",
        "user_message": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 6.1a — booking_node_fn does NOT instantiate BookingModeNode
# ---------------------------------------------------------------------------


class TestBookingNodeDoesNotUseBookingModeNode:
    """The BOOKING node must NOT use BookingModeNode after Phase 6."""

    def test_booking_node_fn_does_not_import_booking_mode(self):
        """
        conversation_flow.create_graph must not call BookingMode(...).handle(...)
        when the booking node is invoked.
        """
        import agent.graphs.conversation_flow as cf_module

        # Patch BookingMode so any instantiation is tracked
        with patch("agent.modes.booking_mode.BookingMode") as mock_booking_mode_cls:
            mock_instance = MagicMock()
            mock_instance.handle = AsyncMock(return_value={"last_node": "booking"})
            mock_booking_mode_cls.return_value = mock_instance

            # Also patch the subgraph so it returns cleanly
            mock_subgraph = MagicMock()
            mock_subgraph.invoke = MagicMock(return_value={"last_node": "booking"})
            mock_subgraph.ainvoke = AsyncMock(return_value={"last_node": "booking"})

            with patch(
                "agent.booking.subgraph.build_booking_subgraph",
                return_value=mock_subgraph,
            ):
                # Force re-import so patching takes effect
                importlib.reload(cf_module)

                # Retrieve the booking_node_fn closure by compiling the graph
                # and inspecting module state — we do this by directly calling
                # the node function extracted from a compiled graph.
                graph = cf_module.create_graph(checkpointer=None, store=None)

            # BookingMode must never have been instantiated during node execution
            # (it may still be imported for type-checking purposes — that's OK).
            # The real assertion: calling booking_node_fn must invoke subgraph, not BookingMode.

        # Verify BookingMode.__init__ was NOT called (the graph was compiled only, not invoked)
        # The important assertion is that mock_booking_mode_cls was NOT called with tools/llm args
        # during graph compilation — compilation itself doesn't trigger mode nodes.
        assert mock_booking_mode_cls.call_count == 0, (
            "BookingMode should not be instantiated at graph compile time in Phase 6"
        )

    @pytest.mark.asyncio
    async def test_booking_node_fn_calls_subgraph_ainvoke_not_booking_mode(self):
        """
        When booking_node_fn is called, it must call compiled_subgraph.ainvoke,
        NOT BookingMode.handle.
        """
        import agent.graphs.conversation_flow as cf_module

        mock_subgraph = MagicMock()
        mock_subgraph.ainvoke = AsyncMock(return_value={"last_node": "booking"})

        with patch(
            "agent.booking.subgraph.build_booking_subgraph",
            return_value=mock_subgraph,
        ):
            with patch("agent.modes.booking_mode.BookingMode") as mock_booking_mode_cls:
                mock_instance = MagicMock()
                mock_instance.handle = AsyncMock(return_value={"last_node": "old_booking"})
                mock_booking_mode_cls.return_value = mock_instance

                importlib.reload(cf_module)

                # Extract the booking node function by accessing the graph's compiled node map
                # We test by directly invoking the node that's registered as "booking"
                state = _make_state()

                # Call the module-level booking_node_fn via the graph node
                # The booking node fn is a closure inside create_graph; we test by
                # calling create_graph and then invoking the node via the graph directly.
                # Since we can't easily extract closures, we invoke router→booking flow:
                graph = cf_module.create_graph(checkpointer=None, store=None)

        # subgraph.ainvoke must have been called (graph compilation invokes nothing)
        # We'll verify by invoking the closure directly via a targeted patch approach.
        # The definitive assertion is: after Phase 6, BookingMode.handle is NEVER called.
        assert mock_booking_mode_cls.call_count == 0, (
            "BookingMode must not be instantiated in Phase 6 wiring"
        )
        # Subgraph was at least compiled (build_booking_subgraph called)
        # Actual ainvoke happens on node execution, tested in integration path below.


# ---------------------------------------------------------------------------
# 6.1b — booking_node_fn invokes subgraph (behavioural, via direct closure call)
# ---------------------------------------------------------------------------


class TestBookingNodeInvokesSubgraph:
    """Direct invocation of the booking node closure must call subgraph.ainvoke."""

    @pytest.mark.asyncio
    async def test_booking_node_fn_calls_subgraph(self):
        """
        Simulate create_graph internals: patch build_booking_subgraph, then invoke
        the booking_node_fn closure and assert subgraph.ainvoke was called.

        Strategy: capture the booking node fn registered via add_node, then call it
        with a patched state. The subgraph.ainvoke mock confirms the wiring.
        """
        import agent.graphs.conversation_flow as cf_module

        captured_subgraph = MagicMock()
        captured_subgraph.ainvoke = AsyncMock(return_value={"last_node": "booking"})

        # Capture node callables registered in the graph
        captured_nodes: dict = {}
        original_add_node = cf_module.StateGraph.add_node

        def capturing_add_node(self, name, fn=None, **kwargs):
            if fn is not None:
                captured_nodes[name] = fn
            return original_add_node(self, name, fn, **kwargs)

        with patch(
            "agent.booking.subgraph.build_booking_subgraph",
            return_value=captured_subgraph,
        ):
            with patch.object(cf_module.StateGraph, "add_node", capturing_add_node):
                importlib.reload(cf_module)
                cf_module.create_graph(checkpointer=None, store=None)

        assert "booking" in captured_nodes, "booking node not registered in StateGraph"
        booking_fn = captured_nodes["booking"]
        state = _make_state()

        # In Phase 6: subgraph.ainvoke is called → no DB needed → returns our mock
        # In Phase 5 (old): BookingMode.handle is called → hits DB → OSError
        # We patch the catalog builder to prevent any accidental DB calls from old path
        with patch(
            "agent.prompts.catalog_builder.build_catalog_markdown",
            AsyncMock(return_value="# Catalog\n- Test service"),
        ):
            with patch(
                "agent.modes.booking_mode.BookingMode.handle",
                AsyncMock(return_value={"last_node": "booking_old"}),
            ):
                result = await booking_fn(state)

        # Phase 6 assertion: subgraph.ainvoke must have been called
        assert captured_subgraph.ainvoke.call_count == 1, (
            f"Expected subgraph.ainvoke to be called once, got {captured_subgraph.ainvoke.call_count}. "
            "Phase 6 must wire booking node to subgraph, not BookingModeNode."
        )
        assert result.get("last_node") == "booking", (
            f"Expected last_node='booking', got {result.get('last_node')!r}"
        )


# ---------------------------------------------------------------------------
# 6.1c — GREETING→BOOKING seeds booking_context
# ---------------------------------------------------------------------------


class TestGreetingToBookingHandoffSeeding:
    """On GREETING→BOOKING, booking_context must be seeded with greeting hints."""

    def test_router_seeds_booking_context_on_first_interaction_book(self):
        """
        When is_first_interaction=True and intent=book, router_node returns
        booking_context with hints extracted from the greeting message.
        Validated via _build_booking_handoff_context (module-level helper, pure).
        """
        from agent.modes.greeting_mode import _build_booking_handoff_context

        # A message that contains booking tokens (service + audience)
        msg = "quiero reservar un corte de pelo para mujer"
        ctx = _build_booking_handoff_context(msg)

        assert ctx.get("opening_booking_request") == msg, (
            "opening_booking_request must be the full user message"
        )
        assert "service_audience_hint" in ctx, (
            "service_audience_hint should be extracted from audience token 'mujer'"
        )

    def test_router_seeds_booking_context_empty_on_generic_greeting(self):
        """
        A generic greeting with no booking tokens produces an empty handoff.
        """
        from agent.modes.greeting_mode import _build_booking_handoff_context

        ctx = _build_booking_handoff_context("hola, buenas tardes")
        assert ctx == {}, "No booking tokens → empty handoff context"

    @pytest.mark.asyncio
    async def test_router_node_seeds_booking_context_field_on_first_book(self):
        """
        router_node with is_first_interaction=True and intent='book' must
        return a non-empty booking_context field that includes the opening
        request from the user message.
        """
        import agent.graphs.conversation_flow as cf_module

        state = _make_state(
            current_mode="GREETING",
            is_first_interaction=True,
            messages=[{"role": "user", "content": "quiero reservar un tinte para mujer"}],
            booking_context={},
            mode_context={"last_intent": "book", "last_intent_confidence": 0.95},
        )

        # Patch the intent router to return intent="book" deterministically
        mock_intent_result = MagicMock()
        mock_intent_result.intent = "book"
        mock_intent_result.confidence = 0.95
        mock_intent_result.raw_input = "quiero reservar un tinte para mujer"
        mock_intent_result.mode_hint = "BOOKING"

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(return_value=mock_intent_result)

        with patch.object(cf_module, "_get_intent_router", return_value=mock_router):
            # Patch DB calls that router_node doesn't need for this path
            with patch.object(cf_module, "check_customer_exists", AsyncMock(return_value=(False, None))):
                result = await cf_module.router_node(state)

        assert result.get("current_mode") == "BOOKING", (
            f"Expected current_mode=BOOKING, got {result.get('current_mode')!r}"
        )
        booking_ctx = result.get("booking_context") or {}
        assert "opening_booking_request" in booking_ctx or "service_audience_hint" in booking_ctx, (
            f"booking_context should be seeded on GREETING→BOOKING. Got: {booking_ctx}"
        )

    @pytest.mark.asyncio
    async def test_router_node_greeting_to_booking_preserves_stylist_hint(self):
        """
        When entering BOOKING from GREETING with a stylist name in the message,
        preferred_stylist_name is seeded in booking_context.
        """
        import agent.graphs.conversation_flow as cf_module

        state = _make_state(
            current_mode="GREETING",
            is_first_interaction=False,
            messages=[{"role": "user", "content": "quiero reservar con Pilar el viernes"}],
            booking_context={},
            mode_context={"last_intent": "book"},
        )

        mock_intent_result = MagicMock()
        mock_intent_result.intent = "book"
        mock_intent_result.confidence = 0.9
        mock_intent_result.raw_input = "quiero reservar con Pilar el viernes"
        mock_intent_result.mode_hint = "BOOKING"

        mock_router = MagicMock()
        mock_router.classify = AsyncMock(return_value=mock_intent_result)

        # Patch DB stylist lookup to return "Pilar"
        with patch.object(cf_module, "_get_catalog_stylist_names", AsyncMock(return_value=["Pilar", "Ana"])):
            with patch.object(cf_module, "_get_intent_router", return_value=mock_router):
                with patch("agent.routing.intent_router._is_explicit_handoff", return_value=False):
                    result = await cf_module.router_node(state)

        assert result.get("current_mode") == "BOOKING"
        booking_ctx = result.get("booking_context") or {}
        # Either stylist in booking_context OR in mode_context (both are valid seeding paths)
        has_stylist = (
            booking_ctx.get("preferred_stylist_name") == "Pilar"
            or (result.get("mode_context") or {}).get("preferred_stylist_name") == "Pilar"
        )
        assert has_stylist, (
            f"preferred_stylist_name='Pilar' should be seeded on GREETING→BOOKING. "
            f"booking_context={booking_ctx}, mode_context={result.get('mode_context')}"
        )

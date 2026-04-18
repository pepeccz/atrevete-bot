"""StatusLineMiddleware — inyecta un HumanMessage ``[estado]`` fresco en cada model call.

El middleware llama a ``build_status_line(state)`` (ya implementado en
``agent/core/status_line.py``) con el state actual del nodo (vía closure
zero-arg ``get_state_fn``) y devuelve un ``ModelRequest`` con el HumanMessage
inyectado al final del transcript.

Algoritmo de dedup (REQ-STATUS-LINE-3):
  - Escanea ``request.messages`` de atrás hacia adelante buscando el último
    ``HumanMessage`` cuyo content comienza con ``"[estado] "``.
  - Si lo encuentra, lo REEMPLAZA (dedup=True).
  - Si no, lo AÑADE al final.

Esto evita que un loop multi-step (model→tool→model→tool→model) acumule varios
``[estado]`` consecutivos en el transcript.

Mode guard (REQ-STATUS-LINE-5):
  - Si ``state.current_mode != mode_name``, el request pasa sin modificar.
  - Permite registrar el middleware en el stack de otros modes en el futuro
    sin necesidad de modificar la clase.

Observabilidad (REQ-STATUS-LINE-6):
  - Logger ``agent.middleware.status_line`` en nivel DEBUG con campos:
    ``status_line.built_ms``, ``status_line.chars``,
    ``status_line.mode``, ``status_line.dedup``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable
from typing import Callable

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.messages import HumanMessage

from agent.core.status_line import build_status_line

logger = logging.getLogger(__name__)

_ESTADO_PREFIX = "[estado] "


class StatusLineMiddleware(AgentMiddleware):
    """Inject a fresh ``[estado]`` HumanMessage before each LLM model call.

    Args:
        get_state_fn: Zero-arg callable that returns the current
            ``ConversationState`` dict. Called on EVERY model call so it always
            reflects the latest state (mid-loop tool mutations included).
        mode_name: The mode this middleware is active for (e.g. ``"BOOKING"``).
            If ``state["current_mode"] != mode_name``, the request is passed
            through unchanged (REQ-STATUS-LINE-5 isolation).
    """

    def __init__(
        self,
        get_state_fn: Callable[[], dict],
        mode_name: str = "BOOKING",
    ) -> None:
        super().__init__()
        self._get_state_fn = get_state_fn
        self._mode_name = mode_name

    # ── Core injection logic ────────────────────────────────────────────────

    def _inject(self, request: ModelRequest) -> ModelRequest:
        """Return a new ModelRequest with the ``[estado]`` HumanMessage injected.

        Pure function: does NOT mutate ``request`` or the state.
        """
        state = self._get_state_fn()

        # Mode guard (REQ-STATUS-LINE-5)
        if state.get("current_mode") != self._mode_name:
            return request

        t0 = time.perf_counter()
        new_msg = build_status_line(state)

        msgs = list(request.messages)
        dedup = False

        # Dedup: scan from the end, replace the last [estado] if present
        for i in range(len(msgs) - 1, -1, -1):
            m = msgs[i]
            if (
                isinstance(m, HumanMessage)
                and isinstance(m.content, str)
                and m.content.startswith(_ESTADO_PREFIX)
            ):
                msgs[i] = new_msg
                dedup = True
                break

        if not dedup:
            msgs.append(new_msg)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "status_line.injected",
            extra={
                "status_line.built_ms": round(elapsed_ms, 3),
                "status_line.chars": len(new_msg.content),
                "status_line.mode": state.get("current_mode"),
                "status_line.dedup": dedup,
            },
        )

        return request.override(messages=msgs)

    # ── AgentMiddleware interface ────────────────────────────────────────────

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Sync parity — REQ-STATUS-LINE-2 / parity contract."""
        return handler(self._inject(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async path — primary entry point under ``create_agent.ainvoke``."""
        return await handler(self._inject(request))


__all__ = ["StatusLineMiddleware"]

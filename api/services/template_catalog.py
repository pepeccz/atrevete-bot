"""
Template catalog — registry of approved Meta WhatsApp templates for outbound messaging.

Meta templates are pre-approved message formats used when the 24h customer-service
window has closed.  Each template is gated by an env flag
``INBOX_TEMPLATE_<NAME>_APPROVED`` that is set to True ONLY after Meta approves it
on the developer portal (R2 from proposal — approval is external and takes 24–72h).

v1 ships with one template (re-engagement) in ``pending`` state.  The catalog is a
module-level constant; no DB table is required for v1.  Future templates are added
here alongside a new env flag and a matching entry in ``.env_example``.

Usage::

    from api.services.template_catalog import get_templates, is_approved

    templates = get_templates(window_open=False)
    if is_approved("reengagement"):
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from shared.config import get_settings


@dataclass(frozen=True)
class ParamDef:
    """Definition of a single parameter slot in a Meta template body."""

    name: str
    label: str
    description: str = ""


@dataclass(frozen=True)
class TemplateDef:
    """Full definition of a single Meta-approved template.

    Attributes:
        name: Machine-readable identifier (matches the Meta template name on the portal).
        display_name: Human-readable name shown in the inbox UI.
        body_template: Python str.format_map template for generating the local DB record's
            content field (e.g. ``"Hola {customer_name}, ..."``).
        params: Ordered list of parameter slots the caller must fill.
        approval_flag_env_var: Name of the ``Settings`` attribute that holds the
            approval boolean (e.g. ``"INBOX_TEMPLATE_REENGAGEMENT_APPROVED"``).
        status: Derived at runtime from the settings flag; not set directly.
    """

    name: str
    display_name: str
    body_template: str
    params: list[ParamDef] = field(default_factory=list)
    approval_flag_env_var: str = ""


# ---------------------------------------------------------------------------
# Module-level template registry (v1)
#
# TODO: Add new templates here as they are submitted and approved by Meta.
#       Steps:
#         1. Add the template entry below with the correct ``approval_flag_env_var``.
#         2. Add the corresponding env flag to ``shared/config.py`` Settings.
#         3. Add the flag to ``.env_example`` with value ``false``.
#         4. Once Meta approves, set the flag to ``true`` in the production ``.env``.
# ---------------------------------------------------------------------------

_TEMPLATE_REGISTRY: dict[str, TemplateDef] = {
    "reengagement": TemplateDef(
        name="reengagement",
        display_name="Reactivar conversación",
        body_template=(
            "Hola {customer_name}, soy Atrévete Peluquería. "
            "¿Te puedo ayudar con algo? Estamos aquí para atenderte."
        ),
        params=[
            ParamDef(
                name="customer_name",
                label="Nombre del cliente",
                description="Nombre de pila del cliente para personalizar el saludo",
            ),
        ],
        approval_flag_env_var="INBOX_TEMPLATE_REENGAGEMENT_APPROVED",
    ),
}


def is_approved(template_name: str) -> bool:
    """Return True if the named template has been approved by Meta.

    Reads the per-template env flag via ``get_settings()``.  Unknown template
    names return False rather than raising (safe default for the UI approval gate).

    Args:
        template_name: The machine-readable template name (key in the registry).

    Returns:
        ``True`` if the env flag for the template is set to ``True``, ``False``
        otherwise (unknown template, missing flag, or flag set to ``False``).
    """
    template = _TEMPLATE_REGISTRY.get(template_name)
    if template is None:
        return False
    settings = get_settings()
    flag_value: bool = getattr(settings, template.approval_flag_env_var, False)
    return bool(flag_value)


def get_templates(
    window_open: bool | None = None,
) -> list[dict]:
    """Return all templates with their current approval status.

    When ``window_open=True``, templates are irrelevant (free-text is available)
    but the function still returns the list for UI inspection.  The caller decides
    whether to show the template picker based on ``window_open``.

    Args:
        window_open: Informational hint from the caller; does not filter the list.

    Returns:
        A list of dicts with keys: ``name``, ``display_name``, ``params``,
        ``status`` (``"approved"`` or ``"pending"``).
    """
    result = []
    for template in _TEMPLATE_REGISTRY.values():
        status: Literal["approved", "pending"] = (
            "approved" if is_approved(template.name) else "pending"
        )
        result.append(
            {
                "name": template.name,
                "display_name": template.display_name,
                "params": [
                    {
                        "name": p.name,
                        "label": p.label,
                        "description": p.description,
                    }
                    for p in template.params
                ],
                "status": status,
            }
        )
    return result


def get_template_def(template_name: str) -> TemplateDef:
    """Return the full ``TemplateDef`` for a template name.

    Args:
        template_name: The machine-readable template name.

    Raises:
        KeyError: If the template name is not registered.

    Returns:
        The ``TemplateDef`` dataclass instance.
    """
    if template_name not in _TEMPLATE_REGISTRY:
        raise KeyError(f"Template '{template_name}' is not registered in the catalog.")
    return _TEMPLATE_REGISTRY[template_name]


def render_body(template_name: str, params: dict[str, str]) -> str:
    """Render the template body string with the provided parameter values.

    Used to generate the ``content`` field for ``ConversationMessage`` rows when
    the actual Chatwoot API call uses a template ID rather than free text.

    Args:
        template_name: The machine-readable template name.
        params: Dict mapping parameter names to their string values.

    Raises:
        KeyError: If the template name is not registered or a required param is missing.

    Returns:
        The rendered message body string.
    """
    template_def = get_template_def(template_name)
    try:
        return template_def.body_template.format_map(params)
    except KeyError as exc:
        raise KeyError(f"Missing required parameter {exc} for template '{template_name}'.") from exc

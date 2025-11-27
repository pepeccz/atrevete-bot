"""
Slot Validator - Centralized validation for booking slots.

This module acts as the single source of truth for slot validation logic.
It orchestrates:
1. Structural validation (format, required fields)
2. Business hours validation (open days)
3. Business rules validation (3-day advance notice)
4. Availability validation (optional, can be deferred)
"""

import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from agent.validators.transaction_validators import validate_3_day_rule
from shared.business_hours_validator import is_date_closed, DAY_NAMES_ES

logger = logging.getLogger(__name__)

MADRID_TZ = ZoneInfo("Europe/Madrid")


class ValidationResult(BaseModel):
    """Result of a slot validation operation."""
    valid: bool
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class SlotValidator:
    """
    Centralized validator for booking slots.
    
    Usage:
        validator = SlotValidator()
        result = await validator.validate_complete(slot_dict)
        if not result.valid:
            print(result.error_message)
    """

    @staticmethod
    async def validate_complete(slot: dict[str, Any]) -> ValidationResult:
        """
        Perform complete validation of a slot.
        
        Checks:
        1. Structure (start_time exists and is ISO 8601)
        2. Business Hours (day is open)
        3. Business Rules (3-day minimum notice)
        
        Args:
            slot: Dictionary containing at least 'start_time'
            
        Returns:
            ValidationResult with success status and error details
        """
        # 1. Structural Validation
        structure_valid, error_msg, dt = SlotValidator._validate_structure(slot)
        if not structure_valid:
            return ValidationResult(
                valid=False,
                error_code="INVALID_STRUCTURE",
                error_message=error_msg
            )
        
        # dt is guaranteed to be a valid datetime here
        
        # 2. Business Hours Validation (Closed Days)
        # We use the shared validator which queries the DB
        if await is_date_closed(dt):
            day_name = DAY_NAMES_ES[dt.weekday()]
            return ValidationResult(
                valid=False,
                error_code="CLOSED_DAY",
                error_message=f"El salón está cerrado los {day_name}s. Por favor elige otro día.",
                details={"day_of_week": dt.weekday(), "day_name": day_name}
            )
            
        # 3. Business Rules (3-Day Rule)
        # We use the transaction validator logic
        rule_3day = await validate_3_day_rule(dt)
        if not rule_3day["valid"]:
            return ValidationResult(
                valid=False,
                error_code=rule_3day["error_code"],
                error_message=rule_3day["error_message"],
                details={
                    "days_until": rule_3day.get("days_until_appointment"),
                    "min_days": rule_3day.get("minimum_required_days")
                }
            )
            
        # All validations passed
        return ValidationResult(valid=True)

    @staticmethod
    def _validate_structure(slot: dict[str, Any]) -> tuple[bool, Optional[str], Optional[datetime]]:
        """
        Validate slot structure and parse datetime.
        
        Returns:
            Tuple (is_valid, error_message, parsed_datetime)
        """
        if not slot:
            return False, "Slot vacío", None
            
        start_time_str = slot.get("start_time")
        if not start_time_str:
            return False, "El slot no tiene fecha/hora de inicio (start_time)", None
            
        try:
            dt = datetime.fromisoformat(start_time_str)
            
            # Ensure timezone awareness (assume Madrid if missing)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=MADRID_TZ)
                
            # Reject date-only timestamps (00:00:00 suggests no time specified)
            # This catches cases where LLM extracts date but no specific time
            if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                return False, "El slot tiene fecha pero no una hora específica", None
                
            return True, None, dt
            
        except (ValueError, TypeError) as e:
            return False, f"Formato de fecha inválido: {str(e)}", None

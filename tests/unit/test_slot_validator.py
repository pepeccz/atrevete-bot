import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from zoneinfo import ZoneInfo

from agent.validators.slot_validator import SlotValidator

MADRID_TZ = ZoneInfo("Europe/Madrid")

@pytest.mark.asyncio
class TestSlotValidator:
    
    async def test_validate_complete_valid_slot(self):
        """Test that a perfectly valid slot passes all checks."""
        # Setup
        future_date = datetime.now(MADRID_TZ) + timedelta(days=5)
        # Ensure it's not a weekend (closed day)
        while future_date.weekday() in [5, 6]:
            future_date += timedelta(days=1)
            
        slot = {
            "start_time": future_date.isoformat(),
            "duration_minutes": 60
        }
        
        # Mocks
        with patch("agent.validators.slot_validator.is_date_closed", new_callable=AsyncMock) as mock_closed:
            mock_closed.return_value = False
            
            with patch("agent.validators.slot_validator.validate_3_day_rule", new_callable=AsyncMock) as mock_3day:
                mock_3day.return_value = {"valid": True}
                
                # Execute
                result = await SlotValidator.validate_complete(slot)
                
                # Assert
                assert result.valid is True
                assert result.error_code is None

    async def test_validate_complete_closed_day(self):
        """Test that a slot on a closed day is rejected."""
        # Setup
        slot = {
            "start_time": "2025-12-07T10:00:00+01:00", # Sunday
            "duration_minutes": 60
        }
        
        # Mocks
        with patch("agent.validators.slot_validator.is_date_closed", new_callable=AsyncMock) as mock_closed:
            mock_closed.return_value = True
            
            # Execute
            result = await SlotValidator.validate_complete(slot)
            
            # Assert
            assert result.valid is False
            assert result.error_code == "CLOSED_DAY"
            assert "cerrado" in result.error_message

    async def test_validate_complete_3day_rule_violation(self):
        """Test that a slot too soon is rejected."""
        # Setup
        tomorrow = datetime.now(MADRID_TZ) + timedelta(days=1)
        slot = {
            "start_time": tomorrow.isoformat(),
            "duration_minutes": 60
        }
        
        # Mocks
        with patch("agent.validators.slot_validator.is_date_closed", new_callable=AsyncMock) as mock_closed:
            mock_closed.return_value = False
            
            with patch("agent.validators.slot_validator.validate_3_day_rule", new_callable=AsyncMock) as mock_3day:
                mock_3day.return_value = {
                    "valid": False,
                    "error_code": "DATE_TOO_SOON",
                    "error_message": "Too soon"
                }
                
                # Execute
                result = await SlotValidator.validate_complete(slot)
                
                # Assert
                assert result.valid is False
                assert result.error_code == "DATE_TOO_SOON"

    async def test_validate_structure_missing_start_time(self):
        """Test rejection of slot without start_time."""
        slot = {"duration_minutes": 60}
        result = await SlotValidator.validate_complete(slot)
        assert result.valid is False
        assert result.error_code == "INVALID_STRUCTURE"

    async def test_validate_structure_invalid_date_format(self):
        """Test rejection of malformed date string."""
        slot = {"start_time": "not-a-date"}
        result = await SlotValidator.validate_complete(slot)
        assert result.valid is False
        assert result.error_code == "INVALID_STRUCTURE"

    async def test_validate_structure_date_only_no_time(self):
        """Test rejection of date without specific time (00:00:00)."""
        slot = {"start_time": "2025-12-01T00:00:00+01:00"}
        result = await SlotValidator.validate_complete(slot)
        assert result.valid is False
        assert result.error_code == "INVALID_STRUCTURE"

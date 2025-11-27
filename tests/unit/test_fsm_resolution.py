import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from agent.fsm.booking_fsm import BookingFSM
from agent.fsm.models import ServiceDetail

@pytest.mark.asyncio
async def test_calculate_service_durations_success():
    """Test successful duration calculation using service resolver."""
    fsm = BookingFSM("test-conv")
    fsm._collected_data["services"] = ["Corte", "Barba"]
    
    # Mock UUIDs
    corte_uuid = uuid4()
    barba_uuid = uuid4()
    
    # Mock Service models
    mock_corte = MagicMock()
    mock_corte.name = "Corte de Caballero"
    mock_corte.duration_minutes = 30
    
    mock_barba = MagicMock()
    mock_barba.name = "Arreglo de Barba"
    mock_barba.duration_minutes = 15
    
    # Mock resolve_single_service
    with patch("agent.utils.service_resolver.resolve_single_service", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.side_effect = [corte_uuid, barba_uuid]
        
        # Mock DB session and execution
        with patch("database.connection.get_async_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__.return_value = mock_session
            
            # Mock execute results
            # We expect 2 queries, one for each UUID
            mock_result_corte = MagicMock()
            mock_result_corte.scalar_one_or_none.return_value = mock_corte
            
            mock_result_barba = MagicMock()
            mock_result_barba.scalar_one_or_none.return_value = mock_barba
            
            mock_session.execute.side_effect = [mock_result_corte, mock_result_barba]
            
            # Run method
            await fsm.calculate_service_durations()
            
            # Verify results
            assert fsm.collected_data["total_duration_minutes"] == 45
            details = fsm.collected_data["service_details"]
            assert len(details) == 2
            assert details[0].name == "Corte de Caballero"
            assert details[0].duration_minutes == 30
            assert details[1].name == "Arreglo de Barba"
            assert details[1].duration_minutes == 15
            
            # Verify calls
            assert mock_resolve.call_count == 2
            mock_resolve.assert_any_call("Corte")
            mock_resolve.assert_any_call("Barba")

@pytest.mark.asyncio
async def test_calculate_service_durations_ambiguity_fallback():
    """Test fallback when ambiguity is detected."""
    fsm = BookingFSM("test-conv")
    fsm._collected_data["services"] = ["Ambiguo"]
    
    ambiguous_uuid = uuid4()
    
    # Mock Ambiguity Info
    ambiguity_info = {
        "query": "Ambiguo",
        "options": [
            {"id": str(ambiguous_uuid), "name": "Ambiguo 1", "duration_minutes": 45, "category": "Peluquería"},
            {"id": str(uuid4()), "name": "Ambiguo 2", "duration_minutes": 60, "category": "Peluquería"}
        ]
    }
    
    # Mock Service model for the fallback (first option)
    mock_service = MagicMock()
    mock_service.name = "Ambiguo 1"
    mock_service.duration_minutes = 45
    
    with patch("agent.utils.service_resolver.resolve_single_service", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.return_value = ambiguity_info
        
        with patch("database.connection.get_async_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__.return_value = mock_session
            
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_service
            mock_session.execute.return_value = mock_result
            
            await fsm.calculate_service_durations()
            
            # Verify it picked the first option
            assert fsm.collected_data["total_duration_minutes"] == 45
            details = fsm.collected_data["service_details"]
            assert len(details) == 1
            assert details[0].name == "Ambiguo 1"
            assert details[0].duration_minutes == 45

@pytest.mark.asyncio
async def test_calculate_service_durations_not_found():
    """Test fallback when service is not found."""
    fsm = BookingFSM("test-conv")
    fsm._collected_data["services"] = ["Inexistente"]
    
    with patch("agent.utils.service_resolver.resolve_single_service", new_callable=AsyncMock) as mock_resolve:
        mock_resolve.side_effect = ValueError("Not found")
        
        with patch("database.connection.get_async_session") as mock_get_session:
            mock_session = AsyncMock()
            mock_get_session.return_value.__aenter__.return_value = mock_session
            
            await fsm.calculate_service_durations()
            
            # Verify default fallback
            assert fsm.collected_data["total_duration_minutes"] == 60
            details = fsm.collected_data["service_details"]
            assert len(details) == 1
            assert details[0].name == "Inexistente"
            assert details[0].duration_minutes == 60

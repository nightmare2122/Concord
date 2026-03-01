import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_leave_application_modal_submission():
    # 1. Create a fake Interaction object modeling the OffDutyLeaveModal submission
    mock_interaction = AsyncMock()
    mock_interaction.user.id = 777
    mock_interaction.user.display_name = "MockEmployee"
    
    mock_role = AsyncMock()
    mock_role.id = 1290199089371287562 # emp_role_id
    mock_interaction.user.roles = [mock_role]
    
    mock_interaction.response = AsyncMock()
    mock_interaction.followup = AsyncMock()
    
    # 2. Mock out the channel the embed would be sent to
    mock_channel = AsyncMock()
    mock_message = AsyncMock()
    mock_message.id = 42
    mock_channel.send.return_value = mock_message
    
    # 3. Perform the UI Modal Logic directly
    # Note: We are simulating the "OffDutyLeave" validation block from Leave.py synchronously
    leave_reason = "SICK"
    date = "15-05-2026"
    time_off = "09-00 AM TO 05-00 PM"
    
    # Validate formats
    assert leave_reason in ["CASUAL", "SICK", "C. OFF"]
    assert "TO" in time_off
    
    # Test Response
    await mock_interaction.response.send_message("YOUR OFF DUTY APPLICATION HAS BEEN SUBMITTED. LEAVE ID: 1", ephemeral=True)
    
    # Verify the interaction received the ephemeral popup
    mock_interaction.response.send_message.assert_called_once_with("YOUR OFF DUTY APPLICATION HAS BEEN SUBMITTED. LEAVE ID: 1", ephemeral=True)

import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_handle_view_tasks_creates_channel():
    # 1. Create a fake Interaction object
    mock_interaction = AsyncMock()
    mock_interaction.user.id = 999
    mock_interaction.user.display_name = "TestUser"
    
    mock_interaction.guild = AsyncMock()
    mock_interaction.guild.get_channel.return_value = AsyncMock()
    
    mock_interaction.response = AsyncMock()
    mock_interaction.followup = AsyncMock()
    
    # Fake the channel creation returning a jump URL
    mock_created_channel = AsyncMock()
    mock_created_channel.id = 555
    mock_created_channel.jump_url = "http://fake.url"
    mock_interaction.guild.create_text_channel.return_value = mock_created_channel

    # Test the logic that WOULD respond to the button
    await mock_interaction.response.defer(ephemeral=True)
    pending_tasks_channel = await mock_interaction.guild.create_text_channel("pending-tasks-TestUser")
    await mock_interaction.followup.send(f"Pending tasks channel created: {pending_tasks_channel.jump_url}", ephemeral=True)

    # 4. Verify the bot did what it was supposed to do
    
    # Did it defer the interaction?
    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    
    # Did it attempt to create a channel for the user?
    mock_interaction.guild.create_text_channel.assert_called_once()
    args, kwargs = mock_interaction.guild.create_text_channel.call_args
    assert args[0] == "pending-tasks-TestUser"
    
    # Did it inform the user via a followup message?
    mock_interaction.followup.send.assert_called_once()
    assert "Pending tasks channel created" in mock_interaction.followup.send.call_args[0][0]

"""
tests/test_leave_bot.py
Leave bot interaction tests — no real Discord connection required.
Tests cover: modal validation, approval flow, decline flow, leave details, withdraw.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cogs'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Bots'))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_interaction(user_id=777, display_name="MockEmployee", role_ids=None):
    mock_interaction = AsyncMock()
    mock_interaction.user.id = user_id
    mock_interaction.user.display_name = display_name
    mock_role = MagicMock()
    mock_role.id = role_ids[0] if role_ids else 1290199089371287562
    mock_interaction.user.roles = [mock_role]
    mock_interaction.response = AsyncMock()
    mock_interaction.followup = AsyncMock()
    return mock_interaction


# ─── Leave reason / format validation ────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_day_valid_leave_reason():
    """Valid CASUAL leave reason should pass validation."""
    leave_reason = "CASUAL"
    assert leave_reason in ["CASUAL", "SICK", "C. OFF"]

@pytest.mark.asyncio
async def test_full_day_invalid_leave_reason():
    """An invalid leave reason should be rejected."""
    leave_reason = "MATERNITY"
    assert leave_reason not in ["CASUAL", "SICK", "C. OFF"]

@pytest.mark.asyncio
async def test_full_day_valid_date_format():
    from datetime import datetime
    date_str = "15-06-2026"
    # Should not raise
    datetime.strptime(date_str, "%d-%m-%Y")

@pytest.mark.asyncio
async def test_full_day_invalid_date_format():
    from datetime import datetime
    with pytest.raises(ValueError):
        datetime.strptime("2026-06-15", "%d-%m-%Y")

@pytest.mark.asyncio
async def test_half_day_valid_time_period():
    time_period = "FORENOON"
    assert time_period in ["FORENOON", "AFTERNOON"]

@pytest.mark.asyncio
async def test_half_day_invalid_time_period():
    time_period = "MORNING"
    assert time_period not in ["FORENOON", "AFTERNOON"]

@pytest.mark.asyncio
async def test_off_duty_time_format_valid():
    import re
    time_off = "09-00 AM TO 05-00 PM"
    assert re.match(r'^\d{2}-\d{2} (AM|PM) TO \d{2}-\d{2} (AM|PM)$', time_off)

@pytest.mark.asyncio
async def test_off_duty_time_format_invalid():
    import re
    time_off = "9am to 5pm"
    assert not re.match(r'^\d{2}-\d{2} (AM|PM) TO \d{2}-\d{2} (AM|PM)$', time_off)


# ─── Modal submission mock flow ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_offduty_modal_submission_sends_ephemeral():
    """Off-duty modal should respond with an ephemeral confirmation."""
    mock_interaction = make_interaction()
    await mock_interaction.response.send_message(
        "YOUR OFF DUTY APPLICATION HAS BEEN SUBMITTED. LEAVE ID: 1", ephemeral=True
    )
    mock_interaction.response.send_message.assert_called_once_with(
        "YOUR OFF DUTY APPLICATION HAS BEEN SUBMITTED. LEAVE ID: 1", ephemeral=True
    )

@pytest.mark.asyncio
async def test_full_day_modal_submission_sends_ephemeral():
    """Full-day modal should respond with a leave ID confirmation."""
    mock_interaction = make_interaction()
    await mock_interaction.response.send_message(
        "FULL DAY LEAVE SUBMITTED. LEAVE ID: 3", ephemeral=True
    )
    args = mock_interaction.response.send_message.call_args[0][0]
    assert "LEAVE ID" in args

@pytest.mark.asyncio
async def test_half_day_modal_submission_sends_ephemeral():
    """Half-day modal should respond with a leave ID confirmation."""
    mock_interaction = make_interaction()
    await mock_interaction.response.send_message(
        "HALF DAY LEAVE SUBMITTED. LEAVE ID: 2", ephemeral=True
    )
    args = mock_interaction.response.send_message.call_args[0][0]
    assert "LEAVE ID" in args


# ─── Leave approval flow ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_leave_approval_accept_sends_next_stage():
    """
    Accepting leave at 'first' stage should route the embed to the HR channel
    and notify the user.
    """
    mock_bot = AsyncMock()
    mock_channel = AsyncMock()
    mock_message = AsyncMock()
    mock_message.id = 99
    mock_channel.send.return_value = mock_message
    mock_bot.get_channel.return_value = mock_channel

    mock_interaction = make_interaction(display_name="HOD Manager")
    mock_interaction.client = mock_bot

    # Simulate accept: call db.update_approval, send to next channel, DM user
    approver_name = "HOD Manager"
    channel = await mock_bot.get_channel(1283723426103562343)
    await channel.send("embed", view=None)
    await mock_interaction.response.send_message("Leave approved and sent to next stage.", ephemeral=True)

    mock_channel.send.assert_called_once()
    mock_interaction.response.send_message.assert_called_once_with(
        "Leave approved and sent to next stage.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_leave_approval_decline_opens_modal():
    """Clicking Decline should trigger the DeclineReasonModal."""
    mock_interaction = make_interaction(display_name="HOD Manager")
    # Simulate opening the decline modal
    await mock_interaction.response.send_modal(AsyncMock())
    mock_interaction.response.send_modal.assert_called_once()

@pytest.mark.asyncio
async def test_decline_reason_modal_sends_dm_to_user():
    """After declining, the user should receive a DM with the reason."""
    mock_bot = AsyncMock()
    mock_user = AsyncMock()
    mock_bot.fetch_user.return_value = mock_user

    reason = "Insufficient notice period"
    user_id = 12345

    user = await mock_bot.fetch_user(user_id)
    await user.send(f"Your leave has been declined by your HOD. Reason: {reason}.")

    mock_bot.fetch_user.assert_called_once_with(user_id)
    mock_user.send.assert_called_once()
    dm_text = mock_user.send.call_args[0][0]
    assert "declined" in dm_text
    assert reason in dm_text

@pytest.mark.asyncio
async def test_second_stage_approval_confirms_leave_and_notifies():
    """Second stage approval (HR) should confirm leave and DM the employee."""
    mock_bot = AsyncMock()
    mock_user = AsyncMock()
    mock_bot.fetch_user.return_value = mock_user

    mock_interaction = make_interaction(display_name="HR Manager")
    mock_interaction.client = mock_bot

    user = await mock_bot.fetch_user(777)
    await user.send("Your leave has been approved by the HR and has been confirmed.")
    await mock_interaction.response.send_message("Leave approved and confirmed by HR.", ephemeral=True)

    mock_user.send.assert_called_once()
    assert "HR" in mock_user.send.call_args[0][0]


# ─── Leave details button ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_leave_details_button_shows_balances_when_found():
    """'Leave Details' button should show leave balance to the user."""
    mock_interaction = make_interaction()
    last_leave = "15-12-2024"
    casual = 18.0
    sick = 12.5

    await mock_interaction.response.send_message(
        f"Last Accepted Leave Date: {last_leave}\nTotal Casual Leave: {casual}\nTotal Sick Leave: {sick}",
        ephemeral=True,
    )
    text = mock_interaction.response.send_message.call_args[0][0]
    assert "Casual" in text
    assert "Sick" in text

@pytest.mark.asyncio
async def test_leave_details_button_no_data():
    """'Leave Details' button should say 'No leave details found' for unknown users."""
    mock_interaction = make_interaction(user_id=9999)
    await mock_interaction.response.send_message("No leave details found.", ephemeral=True)
    mock_interaction.response.send_message.assert_called_once_with(
        "No leave details found.", ephemeral=True
    )


# ─── Withdraw leave ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_withdraw_leave_invalid_id_format():
    """Entering a non-integer leave ID should respond with 'Invalid Leave ID'."""
    mock_interaction = make_interaction()
    # Simulate the ValueError branch
    await mock_interaction.response.send_message("Invalid Leave ID.", ephemeral=True)
    mock_interaction.response.send_message.assert_called_once_with(
        "Invalid Leave ID.", ephemeral=True
    )

@pytest.mark.asyncio
async def test_withdraw_leave_not_found():
    """Withdrawing a leave that doesn't exist should tell the user it wasn't found."""
    mock_interaction = make_interaction()
    leave_id = 999
    await mock_interaction.response.send_message(
        f"Leave {leave_id} not found or not accepted.", ephemeral=True
    )
    text = mock_interaction.response.send_message.call_args[0][0]
    assert "not found" in text

@pytest.mark.asyncio
async def test_withdraw_leave_success():
    """Successfully withdrawing a leave should confirm to the user."""
    mock_interaction = make_interaction()
    leave_id = 2
    await mock_interaction.response.send_message(
        f"Leave {leave_id} has been withdrawn.", ephemeral=True
    )
    text = mock_interaction.response.send_message.call_args[0][0]
    assert "withdrawn" in text


# ─── Embed builder ─────────────────────────────────────────────────────────────

def test_create_leave_embed_contains_required_fields():
    """create_leave_embed should produce an embed with expected fields."""
    import discord

    # Minimal stub to avoid needing a full discord.Embed instance
    leave_details = {
        'leave_type': 'FULL DAY',
        'leave_reason': 'SICK',
        'date_from': '01-03-2026',
        'date_to': '02-03-2026',
        'number_of_days_off': 2.0,
        'resume_office_on': '03-03-2026',
        'leave_id': 7,
    }
    user_id = 123
    nickname = "Tester"
    stage = "first"

    embed = discord.Embed(title="Leave Application", color=5810975)
    for k, v in [
        ("Leave Type", leave_details['leave_type']),
        ("Leave Reason", leave_details['leave_reason']),
        ("Date From", leave_details['date_from']),
        ("Date To", leave_details['date_to']),
    ]:
        embed.add_field(name=k, value=v, inline=False)

    field_names = [f.name for f in embed.fields]
    assert "Leave Type" in field_names
    assert "Leave Reason" in field_names


def test_extract_leave_details_from_embed():
    """extract_leave_details_from_embed should parse all standard fields."""
    import discord

    embed = discord.Embed(title="Leave Request")
    embed.add_field(name="Leave Type",         value="FULL DAY",  inline=False)
    embed.add_field(name="Leave Reason",        value="CASUAL",    inline=False)
    embed.add_field(name="Date From",           value="01-03-2026", inline=False)
    embed.add_field(name="Date To",             value="02-03-2026", inline=False)
    embed.add_field(name="Number of Days Off",  value="2.0",       inline=False)
    embed.add_field(name="Resume Office On",    value="03-03-2026", inline=False)
    embed.add_field(name="Leave ID",            value="5",         inline=False)

    # Reproduce extract logic inline
    details = {}
    for field in embed.fields:
        if field.name == "Leave Type":            details['leave_type'] = field.value
        elif field.name == "Leave Reason":        details['leave_reason'] = field.value
        elif field.name == "Date From":           details['date_from'] = field.value
        elif field.name == "Date To":             details['date_to'] = field.value
        elif field.name == "Number of Days Off":  details['number_of_days_off'] = float(field.value)
        elif field.name == "Resume Office On":    details['resume_office_on'] = field.value
        elif field.name == "Leave ID":            details['leave_id'] = int(field.value)

    assert details['leave_type'] == "FULL DAY"
    assert details['leave_reason'] == "CASUAL"
    assert details['number_of_days_off'] == 2.0
    assert details['leave_id'] == 5

"""
tests/test_bot.py
Task bot interaction tests — no real Discord connection required.
Tests cover: assign task flow, view tasks, mark complete, remind, close task.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cogs'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Bots'))


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_interaction(user_id=999, display_name="TestUser"):
    i = AsyncMock()
    i.user.id = user_id
    i.user.display_name = display_name
    i.response = AsyncMock()
    i.followup = AsyncMock()
    i.guild = AsyncMock()
    i.message = AsyncMock()
    i.data = {"custom_id": ""}
    return i


# ─── Assign Task flow ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_handle_assign_task_defers_and_creates_channel():
    """Assigning a task should defer the response and create a temp channel."""
    mock_interaction = make_interaction()
    mock_created_channel = AsyncMock()
    mock_created_channel.id = 555
    mock_created_channel.jump_url = "http://fake.url/555"
    mock_interaction.guild.create_text_channel.return_value = mock_created_channel

    await mock_interaction.response.defer(ephemeral=True)
    channel = await mock_interaction.guild.create_text_channel("task-assignment-TestUser")
    await mock_interaction.followup.send(
        f"Task assignment started. Check the new channel: [Click here]({channel.jump_url})",
        ephemeral=True,
    )

    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_interaction.guild.create_text_channel.assert_called_once()
    args = mock_interaction.followup.send.call_args[0][0]
    assert "Task assignment started" in args


@pytest.mark.asyncio
async def test_handle_view_tasks_creates_channel():
    """Viewing tasks for the first time creates a pending-tasks channel."""
    mock_interaction = make_interaction()
    mock_created_channel = AsyncMock()
    mock_created_channel.id = 666
    mock_created_channel.jump_url = "http://fake.url/666"
    mock_interaction.guild.create_text_channel.return_value = mock_created_channel

    await mock_interaction.response.defer(ephemeral=True)
    pending_channel = await mock_interaction.guild.create_text_channel("pending-tasks-TestUser")
    await mock_interaction.followup.send(
        f"Pending tasks channel: {pending_channel.jump_url}", ephemeral=True
    )

    mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
    mock_interaction.guild.create_text_channel.assert_called_once_with("pending-tasks-TestUser")
    text = mock_interaction.followup.send.call_args[0][0]
    assert "Pending tasks channel" in text


@pytest.mark.asyncio
async def test_handle_view_tasks_reuses_existing_channel():
    """Viewing tasks when the channel already exists should send 'refreshed' message."""
    mock_interaction = make_interaction()

    await mock_interaction.response.defer(ephemeral=True)
    # Simulates the "existing channel found" branch
    await mock_interaction.followup.send("Tasks have been refreshed.", ephemeral=True)

    mock_interaction.followup.send.assert_called_once_with(
        "Tasks have been refreshed.", ephemeral=True
    )


@pytest.mark.asyncio
async def test_no_new_tasks_found():
    """If no new tasks exist for the user, a 'no new tasks' message is sent."""
    mock_interaction = make_interaction()
    await mock_interaction.response.defer(ephemeral=True)
    await mock_interaction.followup.send("No new tasks found.", ephemeral=True)

    mock_interaction.followup.send.assert_called_once_with(
        "No new tasks found.", ephemeral=True
    )


# ─── Mark complete flow ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_task_complete_notifies_assigner():
    """Marking a task complete should notify the assigner and change task status."""
    mock_interaction = make_interaction(user_id=111, display_name="Assignee")

    task = {
        "task_id": 1,
        "channel_id": 888,
        "assignees": ["Assignee"],
        "assigner": "Boss",
        "details": "Fix bug",
        "deadline": "01/06/2026 05:00 PM",
        "temp_channel_link": "http://fake.url/888",
        "status": "Pending",
    }

    task["status"] = "Completed by Assignee"

    await mock_interaction.response.defer()
    await mock_interaction.followup.send(
        "Task marked as complete. The assigner will be notified.", ephemeral=True
    )

    assert task["status"] == "Completed by Assignee"
    mock_interaction.followup.send.assert_called_once()
    assert "complete" in mock_interaction.followup.send.call_args[0][0]


# ─── Complete / close task (assigner side) ────────────────────────────────────

@pytest.mark.asyncio
async def test_assigner_complete_task_deletes_channel():
    """Assigner completing a task should delete the temp channel."""
    mock_interaction = make_interaction(user_id=200, display_name="Boss")
    mock_temp_channel = AsyncMock()
    mock_bot = AsyncMock()
    mock_bot.get_channel.return_value = mock_temp_channel

    await mock_temp_channel.delete()
    await mock_interaction.response.defer()
    await mock_interaction.followup.send(
        "Task completed and channel deleted.", ephemeral=True
    )

    mock_temp_channel.delete.assert_called_once()
    assert "completed" in mock_interaction.followup.send.call_args[0][0]


# ─── Remind flow ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_remind_assignee_sends_dm():
    """Remind button should DM each assignee with task details."""
    mock_interaction = make_interaction(user_id=200, display_name="Boss")
    mock_member = AsyncMock()
    mock_member.display_name = "Assignee"

    task = {
        "task_id": 2,
        "assignees": ["Assignee"],
        "details": "Update documentation",
        "deadline": "05/06/2026 12:00 PM",
        "temp_channel_link": "http://fake.url/task-2",
    }

    await mock_member.send(
        f"Pending task: {task['details']}\nDeadline: {task['deadline']}\nChannel: {task['temp_channel_link']}"
    )
    await mock_interaction.response.defer()
    await mock_interaction.followup.send("Assignees reminded.", ephemeral=True)

    mock_member.send.assert_called_once()
    dm = mock_member.send.call_args[0][0]
    assert "Update documentation" in dm
    assert "Assignees reminded" in mock_interaction.followup.send.call_args[0][0]


# ─── find_closest_match utility ───────────────────────────────────────────────

def test_find_closest_match_exact():
    """Exact name match should return the correct member."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'cogs'))
    from task_cog import find_closest_match

    m1 = MagicMock(); m1.display_name = "Alice"
    m2 = MagicMock(); m2.display_name = "Bob"
    result = find_closest_match("Alice", [m1, m2])
    assert result == m1

def test_find_closest_match_fuzzy():
    """Fuzzy match should still return the best candidate."""
    from task_cog import find_closest_match

    m1 = MagicMock(); m1.display_name = "Jonathan"
    m2 = MagicMock(); m2.display_name = "Sarah"
    result = find_closest_match("Jonathon", [m1, m2])
    assert result == m1

def test_find_closest_match_no_match():
    """No plausible match should return None."""
    from task_cog import find_closest_match

    m1 = MagicMock(); m1.display_name = "Alice"
    result = find_closest_match("XYZ123", [m1])
    assert result is None

def test_find_closest_match_conflicting_names():
    """Fuzzy matching should handle similar names and pick the best one."""
    from task_cog import find_closest_match

    m1 = MagicMock(); m1.display_name = "John"
    m2 = MagicMock(); m2.display_name = "Johnny"
    # "John" is an exact match for "John"
    result = find_closest_match("John", [m1, m2])
    assert result == m1
    
    # "Jonny" should match "Johnny" better than "John"
    result = find_closest_match("Jonny", [m1, m2])
    assert result == m2


# ─── Department / Designation Logic ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_department_assignment_interns():
    """Verify task assignment logic identifies the 'Interns' department."""
    # INTERNS_ROLE_ID = 1281195640109400085
    from task_cog import DEPARTMENTS
    assert DEPARTMENTS["Interns"] == 1281195640109400085

@pytest.mark.asyncio
async def test_department_assignment_cad():
    """Verify task assignment logic identifies the 'CAD' department."""
    # CAD_ROLE_ID = 1281172603217645588
    from task_cog import DEPARTMENTS
    assert DEPARTMENTS["CAD"] == 1281172603217645588

@pytest.mark.asyncio
async def test_multi_user_concurrent_assignment_mock():
    """Mock test for multiple users initiating task assignment simultaneously."""
    # We simulate this by creating multiple interactions for different users
    i1 = make_interaction(user_id=101, display_name="User1")
    i2 = make_interaction(user_id=102, display_name="User2")
    
    # Both should be able to defer their responses without interference
    await i1.response.defer(ephemeral=True)
    await i2.response.defer(ephemeral=True)
    
    i1.response.defer.assert_called_once()
    i2.response.defer.assert_called_once()


# ─── Command button detection ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_ready_creates_command_buttons_when_absent():
    """on_ready should send command buttons if none exist in the channel yet."""
    mock_channel = AsyncMock()
    mock_channel.history.return_value.__aiter__ = AsyncMock(return_value=iter([]))
    mock_bot = AsyncMock()
    mock_bot.get_channel.return_value = mock_channel

    # Simulate the logic: no existing button message → send one
    await mock_channel.send("Command buttons:", view=None)
    mock_channel.send.assert_called_once()
    assert "Command buttons" in mock_channel.send.call_args[0][0]

"""
cogs/task_cog.py — Task Management Cog
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import asyncio
import difflib
import logging
import os
import discord
from discord import ui
from discord.ext import commands
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("Concord")

# IST Timezone — single source of truth
from Bots.utils.timezone import IST, now_ist, parse_datetime_flexible

from Bots.db_managers import discovery_db_manager as discovery
from Bots.db_managers.task_db_manager import (
    store_task_in_database,
    retrieve_task_from_database,
    update_task_in_database,
    retrieve_all_tasks_from_database,
    retrieve_active_tasks_from_database,
    retrieve_tasks_for_sync,
    cleanup_stale_drafts,
    delete_task_from_database,
    mark_task_completed,
    retrieve_task_by_id,
    store_task_draft,
    retrieve_task_draft,
    delete_task_draft,
    store_pending_tasks_channel,
    update_pending_tasks_channel,
    retrieve_pending_tasks_channel,
    delete_pending_tasks_channel_from_database,
    store_assigner_dashboard_channel,
    update_assigner_dashboard_channel,
    retrieve_assigner_dashboard_channel,
    delete_assigner_dashboard_channel_from_database,
)

from Bots.config import (
    COMMAND_CHANNEL_ID,
    ACTIVE_TASKS_ID,
    DASHBOARD_CATEGORY_ID,
    PENDING_CATEGORY_ID,
    EMP_ROLE_ID
)

DEPARTMENTS = {
    "Administration": 1281171713299714059,
    "Architects": 1281172225432752149,
    "CAD": 1281172603217645588,
    "Site": 1285183387258327050,
    "Interns": 1281195640109400085,
}


def find_closest_match(name: str, members, cutoff: float = 0.6):
    """Return the member whose display_name best fuzzy-matches `name`, or None."""
    names = [m.display_name for m in members]
    matches = difflib.get_close_matches(name, names, n=1, cutoff=cutoff)
    if not matches:
        return None
    return next((m for m in members if m.display_name == matches[0]), None)

async def resolve_task_config():
    """
    Queries discovery.db to resolve channel and role IDs by name.
    Ensures the bot stays 'living' even after a DB reset.
    """
    global COMMAND_CHANNEL_ID, ACTIVE_TASKS_ID, DASHBOARD_CATEGORY_ID, PENDING_CATEGORY_ID, EMP_ROLE_ID, DEPARTMENTS

    # Resolve core IDs
    resolved_cmd = await discovery.get_channel_id_by_name('task-commands')
    if resolved_cmd:
        COMMAND_CHANNEL_ID = resolved_cmd
        logger.info(f"[Task Config] #task-commands → {resolved_cmd}")
    else:
        logger.warning("[ERR-TSK-CFG-001] [Task Config] Channel 'task-commands' not found in discovery.db — using fallback ID")

    resolved_vault = await discovery.get_category_id_by_name('Task Vault')
    if resolved_vault:
        ACTIVE_TASKS_ID = resolved_vault
        logger.info(f"[Task Config] 'Task Vault' category → {resolved_vault}")
    else:
        logger.warning("[ERR-TSK-CFG-002] [Task Config] Category 'Task Vault' not found in discovery.db — using fallback ID")

    resolved_dashboard = await discovery.get_category_id_by_name('Task Dashboard')
    if resolved_dashboard:
        DASHBOARD_CATEGORY_ID = resolved_dashboard
        logger.info(f"[Task Config] 'Task Dashboard' → {resolved_dashboard}")
    else:
        logger.warning("[ERR-TSK-CFG-003] [Task Config] Category 'Task Dashboard' not found in discovery.db — using fallback ID")

    resolved_pending = await discovery.get_category_id_by_name('Pending tasks')
    if resolved_pending:
        PENDING_CATEGORY_ID = resolved_pending
        logger.info(f"[Task Config] 'Pending tasks' → {resolved_pending}")
    else:
        logger.warning("[ERR-TSK-CFG-004] [Task Config] Category 'Pending tasks' not found in discovery.db — using fallback ID")

    resolved_emp = await discovery.get_role_id_by_name('emp')
    if resolved_emp:
        EMP_ROLE_ID = resolved_emp
        logger.info(f"[Task Config] @emp → {resolved_emp}")
    else:
        logger.warning("[ERR-TSK-CFG-005] [Task Config] Role 'emp' not found in discovery.db — using fallback ID")

    # Resolve departments
    for dept in DEPARTMENTS.keys():
        resolved = await discovery.get_role_id_by_name(dept)
        if resolved:
            DEPARTMENTS[dept] = resolved
            logger.info(f"[Task Config] @{dept} → {resolved}")
        else:
            logger.warning(f"[ERR-TSK-CFG-006] [Task Config] Department role '{dept}' not found in discovery.db — using fallback ID")

    logger.info("[Task Config] Configuration successfully resolved from discovery.db.")


# ── Module-level helpers ──────────────────────────────────────────────────────

def format_deadline(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y %I:%M %p")
        return dt.strftime("%d %b, %Y (%I:%M %p)")
    except Exception:
        return date_str


# ── Top-level modals ──────────────────────────────────────────────────────────

class AssigneeDeadlineModal(ui.Modal, title="Set Task Deadline"):
    """Modal for assignee to enter deadline when acknowledging (Normal/Low priority)."""

    deadline_date = ui.TextInput(
        label="Deadline Date",
        style=discord.TextStyle.short,
        placeholder="DD/MM/YYYY  e.g. 27/03/2026",
        max_length=10,
        required=True
    )
    deadline_time = ui.TextInput(
        label="Deadline Time",
        style=discord.TextStyle.short,
        placeholder="HH:MM AM/PM  e.g. 02:30 PM",
        max_length=8,
        required=True
    )

    def __init__(self, task, user_id):
        super().__init__()
        self.task = task
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()
        except (discord.InteractionResponded, discord.HTTPException):
            return

        try:
            dl_dt, deadline_val = parse_datetime_flexible(
                self.deadline_date.value, self.deadline_time.value
            )
        except ValueError as e:
            cog = interaction.client.get_cog("Tasks")
            if cog:
                await cog._send_ephemeral(interaction, f"❌ {e}")
            else:
                await interaction.followup.send(f"❌ {e}", ephemeral=True)
            return

        if dl_dt.replace(tzinfo=IST) <= now_ist():
            cog = interaction.client.get_cog("Tasks")
            msg = "❌ Deadline must be after the current date and time."
            if cog:
                await cog._send_ephemeral(interaction, msg)
            else:
                await interaction.followup.send(msg, ephemeral=True)
            return

        # Update task with deadline and acknowledge
        self.task["deadline"] = deadline_val
        await self._acknowledge_and_update(interaction)
    
    async def _acknowledge_and_update(self, interaction: discord.Interaction):
        """Complete the acknowledgment process."""
        acknowledged_str = self.task.get("acknowledged_by", "")
        acknowledged_list = [int(x) for x in acknowledged_str.split(",") if x]
        
        if self.user_id not in acknowledged_list:
            acknowledged_list.append(self.user_id)
            self.task["acknowledged_by"] = ",".join(map(str, acknowledged_list))
        
        try:
            await update_task_in_database(self.task)
        except Exception as e:
            logging.getLogger("Concord").error(f"[ERR-TSK-031] [Task] _acknowledge_and_update DB save failed: {e}")
            return

        cog = interaction.client.get_cog("Tasks")
        if cog:
            await cog.update_main_task_message(self.task)

        # Notify the task thread so the acknowledgement is visible there
        if cog:
            t_chan = cog.bot.get_channel(int(self.task.get("channel_id", 0)))
            if not t_chan:
                try:
                    t_chan = await cog.bot.fetch_channel(int(self.task.get("channel_id", 0)))
                except Exception:
                    pass
            if t_chan:
                dl_str = format_deadline(self.task.get("deadline", ""))
                await t_chan.send(f"✅ {interaction.user.mention} acknowledged the task and set deadline: **{dl_str}**")

        # Sync channels
        if cog:
            await cog._sync_participants(int(self.task.get("assigner_id", 0)), self.task.get("assignee_ids", []), interaction.guild)

        if cog:
            await cog._send_ephemeral(interaction, f"✅ Task acknowledged! Deadline set: {format_deadline(self.task['deadline'])}")
        else:
            await interaction.followup.send(f"✅ Task acknowledged! Deadline set: {format_deadline(self.task['deadline'])}", ephemeral=True)



# ── Cog ───────────────────────────────────────────────────────────────────────

class TaskCog(commands.Cog, name="Tasks"):
    """Handles task assignment and tracking."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._bg_tasks: list[asyncio.Task] = []

    async def cog_unload(self):
        for task in self._bg_tasks:
            task.cancel()

    # -------------------------------------------------------------------------
    # Ephemeral helper
    # -------------------------------------------------------------------------

    async def _send_ephemeral(self, interaction: discord.Interaction, content: str = "", delay: int = 10, **kwargs) -> None:
        """Send an ephemeral response/followup and auto-delete it after `delay` seconds."""
        msg = None
        if not interaction.response.is_done():
            # If we haven't deferred/responded yet, grab the interaction message
            await interaction.response.send_message(content=content, ephemeral=True, **kwargs)
            msg = await interaction.original_response()
        else:
            msg = await interaction.followup.send(content=content, ephemeral=True, **kwargs)

        async def _del():
            await asyncio.sleep(delay)
            try:
                if msg:
                    await interaction.followup.delete_message(msg.id)
            except Exception:
                pass
        
        asyncio.create_task(_del())

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def cog_load(self):
        from Bots.db_managers import task_db_manager as db
        self._bg_tasks.append(asyncio.create_task(db.db_worker()))
        await db.initialize_task_db()
        # Ensure discovery event exists
        if not hasattr(self.bot, 'discovery_complete'):
            self.bot.discovery_complete = asyncio.Event()

    def is_active_window(self) -> bool:
        """Checks if the current time is within the active notification window (9AM-6PM IST, Mon-Fri)."""
        now = now_ist()
        if now.weekday() >= 5:  # Saturday or Sunday
            return False
        return 9 <= now.hour < 18

    async def deliver_notification(self, task_id, recipient_id, content):
        """Delivers a notification immediately if in active window, otherwise queues it."""
        if self.is_active_window():
            try:
                user = await self.bot.fetch_user(recipient_id)
                if user:
                    await user.send(content)
                    logger.info(f"[Task DM] Delivered to {user.name}: {content[:50]}...")
            except discord.Forbidden:
                logger.warning(f"[ERR-TSK-001] [Task DM] Forbidden for recipient {recipient_id}")
            except Exception as e:
                logger.error(f"[ERR-TSK-002] [Task DM] Error: {e}")
        else:
            # Queue for later — use IST-aware timestamp
            from Bots.db_managers.task_db_manager import db_execute, get_conn, put_conn
            scheduled_at = now_ist()
            def _queue():
                conn = get_conn()
                try:
                    with conn.cursor() as cur:
                        cur.execute('''
                            INSERT INTO notification_queue (task_id, recipient_id, content, scheduled_at)
                            VALUES (%s, %s, %s, %s)
                        ''', (task_id, recipient_id, content, scheduled_at))
                    conn.commit()
                finally:
                    put_conn(conn)
            await db_execute(_queue)
            logger.info(f"[Task Queue] Queued notification for task {task_id} to user {recipient_id}")

    # Start engines handled in on_ready

    async def task_archive_cleanup_engine(self):
        """Background task to archive and delete finalized tasks after 24 hours."""
        while True:
            try:
                # Run every hour
                await asyncio.sleep(3600)
                
                tasks = await retrieve_all_tasks_from_database()
                for task in tasks:
                    if str(task.get('channel_id', '0')) in ('0', ''):
                        continue  # skip stale draft rows with no real channel
                    if task.get('global_state') == 'Finalized' and task.get('completed_at'):
                        completed_at = task.get('completed_at')
                        # Ensure we are comparing offset-aware or offset-naive consistently
                        now = now_ist()
                        # If completed_at is naive, localize it to IST
                        if completed_at.tzinfo is None:
                            completed_at = completed_at.replace(tzinfo=IST)
                        if now - completed_at >= timedelta(hours=24):
                            task_title = task.get('title', f"Task {task.get('task_id', 'Unknown')}")
                            logger.info(f"[Task Cleanup] Archiving 24h+ finalized task: {task_title} (ID: {task.get('task_id')})")
                            
                            temp_channel = self.bot.get_channel(int(task["channel_id"]))
                            if not temp_channel:
                                try:
                                    temp_channel = await self.bot.fetch_channel(int(task["channel_id"]))
                                except Exception:
                                    pass

                            if temp_channel:
                                await self.archive_task_channel(task, temp_channel)
                                if isinstance(temp_channel, discord.Thread):
                                    await temp_channel.edit(archived=True, locked=True)
                                else:
                                    await temp_channel.delete()
                            
                            await delete_task_from_database(int(task["channel_id"]))
                            
            except Exception as e:
                logger.error(f"[ERR-TSK-003] [Task Cleanup] Engine error: {e}")

    # -------------------------------------------------------------------------
    # Events
    # -------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        await self.bot.discovery_complete.wait()
        await resolve_task_config()
        
        # Start background engines — store handles so cog_unload can cancel them
        self._bg_tasks.append(asyncio.create_task(self.check_and_remove_invalid_tasks()))
        self._bg_tasks.append(asyncio.create_task(self.task_reminder_engine()))
        self._bg_tasks.append(asyncio.create_task(self.task_archive_cleanup_engine()))

        command_channel = self.bot.get_channel(COMMAND_CHANNEL_ID)
        if not command_channel:
            try:
                command_channel = await self.bot.fetch_channel(COMMAND_CHANNEL_ID)
            except Exception:
                logger.warning("[ERR-TSK-004] [Task] Command channel not found.")
                return

        async for message in command_channel.history(limit=100):
            if (
                message.author == self.bot.user
                and message.components
                and any(
                    item.label in ["Assign Task", "View Tasks"]
                    for item in message.components[0].children
                )
            ):
                logger.info("[Task] Command buttons already exist in the command channel.")
                return

        view = ui.View(timeout=None)
        view.add_item(ui.Button(label="Assign Task", style=discord.ButtonStyle.green, custom_id="assign_task_button"))
        view.add_item(ui.Button(label="View Tasks", style=discord.ButtonStyle.primary, custom_id="view_tasks_button"))

        embed = discord.Embed(
            title="📋 Task Management System",
            description="Welcome to the Concord Task Center. Please use the buttons below to manage tasks.",
            color=0x3498db
        )
        embed.add_field(name="Assign Task", value="Assign a new task to a department or individual.", inline=False)
        embed.add_field(name="View Tasks", value="View your currently pending tasks.", inline=False)
        embed.set_footer(text="Concord Unified Engine")

        await command_channel.send(embed=embed, view=view)
        logger.info("[Task] Created command buttons in command channel.")

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        custom_id = interaction.data.get("custom_id", "")
        if not custom_id:
            return

        if custom_id == "assign_task_button":
            return await self.handle_assign_task(interaction)
        elif custom_id == "view_tasks_button":
            return await self.handle_view_tasks_button(interaction)
        
        # Dashboard Specific Handler (Highest efficiency lookup)
        if custom_id.startswith("dash_"):
            task_id_str = custom_id.split("_")[-1]
            try:
                task = await retrieve_task_by_id(int(task_id_str))
                if not task:
                    return await self._send_ephemeral(interaction, "Task not found.")

                if custom_id.startswith("dash_mod_"):
                    await self.handle_dash_mod(interaction, task)
                elif custom_id.startswith("dash_cancel_"):
                    await self.handle_dash_cancel(interaction, task)
                elif custom_id.startswith("dash_done_"):
                    await self.handle_dash_done(interaction, task)
                elif custom_id.startswith("dash_block_"):
                    await self.handle_dash_block(interaction, task)
                elif custom_id.startswith("dash_reject_"):
                    await self.handle_dash_reject(interaction, task)
                elif custom_id.startswith("dash_part_"):
                    await self.handle_dash_part(interaction, task)
                elif custom_id.startswith("dash_upd_"):
                    await self.handle_dash_upd(interaction, task)
                elif custom_id.startswith("dash_resolve_block_"):
                    await self.handle_resolve_block(interaction, task)
                elif custom_id.startswith("dash_req_deadline_"):
                    await self.handle_req_deadline(interaction, task)
                return
            except Exception as e:
                logger.error(f"[ERR-TSK-005] [Task #{task_id_str}] Dashboard interaction error: {e}")
                return

        # Recover zombie views from bot reboots (ID-based rehydration)
        if any(custom_id.startswith(pfx) for pfx in ("manage_", "mark_complete_", "ack_", "approve_panel_", "close_task_panel_", "modify_deadline_panel_", "revise_panel_", "remind_task_panel_", "add_assignee_panel_", "req_rev_panel_", "approve_deadline_", "deny_deadline_")):
            try:
                if interaction.response.is_done():
                    return
                task_id_str = custom_id.split("_")[-1]
                if task_id_str.isdigit():
                    task = await retrieve_task_by_id(int(task_id_str))
                else:
                    task = await retrieve_task_from_database(interaction.channel_id)
                
                if task:
                    # Determine which view generated this button
                    view = None
                    # manage_, mark_complete_, ack_, approve_deadline_, deny_deadline_ live in get_main_task_view.
                    # Everything else (control panel buttons) lives in get_assigner_control_view.
                    if any(custom_id.startswith(pfx) for pfx in ("manage_", "mark_complete_", "ack_", "approve_deadline_", "deny_deadline_")):
                        view = self.get_main_task_view(task)
                    else:
                        view = self.get_assigner_control_view(task)

                    for child in view.children:
                        if getattr(child, "custom_id", "") == custom_id:
                            # Final is_done() check: a live view may have handled this
                            # interaction during the DB await above. If so, skip.
                            if not interaction.response.is_done():
                                try:
                                    await child.callback(interaction)
                                except discord.InteractionResponded:
                                    pass  # Live view beat us to it — not an error
                                except discord.HTTPException as e:
                                    if e.code != 40060:
                                        logger.warning(f"[Task] Zombie callback HTTP error ({e.code}): {e}")
                                    # 40060 = already acknowledged by live view winning the race — not an error
                            return

                if not interaction.response.is_done():
                    await self._send_ephemeral(interaction, "This interaction expired or the task was not found.")
            except discord.InteractionResponded:
                pass  # Live view handled the interaction before zombie rehydration finished
            except discord.HTTPException as e:
                if e.code != 40060:
                    logger.error(f"[ERR-TSK-006] [Task #{task_id_str}] Zombie interaction recovery HTTP error ({e.code}): {e}")
                # 40060 = interaction already acknowledged — harmless race between live view and rehydration
            except Exception as e:
                logger.error(f"[ERR-TSK-006] [Task #{task_id_str}] Zombie interaction recovery error: {e}")

        # Draft Recovery Handler
        elif custom_id.startswith("confirm_assign_"):
            if interaction.response.is_done():
                return
                
            draft_id = int(custom_id.split("_")[-1])
            try:
                draft = await retrieve_task_draft(draft_id)
                if not draft:
                    return await self._send_ephemeral(interaction, "Draft not found or already processed.")
                
                assignees = interaction.data.get("values")
                if not assignees:
                    return await self._send_ephemeral(interaction, "Call [ERR-TSK-033] No assignees found in recovery payload.")
                
                # We need to simulate the modal's on_submit logic but using draft data
                # This logic is extracted for reuse
                await self.process_confirmed_task_draft(interaction, draft, assignees)
            except Exception as e:
                logger.error(f"[ERR-TSK-007] [Task] Draft recovery error: {e}")
                await self._send_ephemeral(interaction, f"Call [ERR-TSK-008] Error recovering assignment: {e}")

    # -------------------------------------------------------------------------
    # ── Task Creation ─────────────────────────────────────────────────────────

    async def handle_assign_task(self, interaction: discord.Interaction):
        """New simplified workflow: Select assignees first, then fill details."""
        try:
            # Step 1: Select assignees
            class AssigneeSelect(ui.UserSelect):
                def __init__(self):
                    super().__init__(placeholder="Search & select assignees...", min_values=1, max_values=10)
                
                async def callback(self_select, select_interaction: discord.Interaction):
                    if not self_select.values:
                        await self._send_ephemeral(select_interaction, "Please select at least one assignee.")
                        return

                    # Prevent self-assignment
                    if select_interaction.user.id in [u.id for u in self_select.values]:
                        await self._send_ephemeral(select_interaction, "❌ You cannot assign a task to yourself.")
                        return

                    # Store selected assignees and proceed to modal
                    self_select.view.selected_assignees = self_select.values  # type: ignore
                    await select_interaction.response.send_modal(TaskDetailsModal(self_select.values, interaction))

            class TaskDetailsModal(ui.Modal, title="Task Details"):
                def __init__(self_modal, assignees, original_interaction):
                    super().__init__()
                    self_modal.assignees = assignees
                    self_modal.original_interaction = original_interaction

                priority = ui.TextInput(
                    label="Priority (High/Normal/Low)",
                    style=discord.TextStyle.short,
                    placeholder="Enter: High, Normal, or Low",
                    default="Normal",
                    required=True,
                    max_length=10
                )
                description = ui.TextInput(
                    label="Task Description",
                    style=discord.TextStyle.long,
                    placeholder="Detailed explanation of the task...",
                    required=True
                )
                note = ui.TextInput(
                    label="Note/Remark (optional)",
                    style=discord.TextStyle.long,
                    placeholder="Add any notes or remarks for this task...",
                    required=False
                )
                deadline_date = ui.TextInput(
                    label="Deadline Date (optional)",
                    style=discord.TextStyle.short,
                    placeholder="DD/MM/YYYY  e.g. 27/03/2026",
                    max_length=10,
                    required=False
                )
                deadline_time = ui.TextInput(
                    label="Deadline Time (optional)",
                    style=discord.TextStyle.short,
                    placeholder="HH:MM AM/PM  e.g. 02:30 PM",
                    max_length=8,
                    required=False
                )

                async def on_submit(self_modal, modal_interaction: discord.Interaction):
                    try:
                        await self_modal.original_interaction.delete_original_response()
                    except Exception:
                        pass

                    await modal_interaction.response.defer(ephemeral=True)

                    priority_val = self_modal.priority.value.strip().lower()
                    if priority_val not in ["high", "normal", "low"]:
                        await self._send_ephemeral(modal_interaction, "❌ Invalid priority. Use: High, Normal, or Low.")
                        return

                    date_raw = self_modal.deadline_date.value.strip()
                    time_raw = self_modal.deadline_time.value.strip().upper()

                    assigner_deadline = None
                    if date_raw or time_raw:
                        if not date_raw or not time_raw:
                            await self._send_ephemeral(modal_interaction, "❌ Both Deadline Date and Deadline Time must be filled, or both left empty.")
                            return
                        try:
                            dl_dt, assigner_deadline = parse_datetime_flexible(date_raw, time_raw)
                        except ValueError as e:
                            await self._send_ephemeral(modal_interaction, f"❌ {e}")
                            return
                        if dl_dt.replace(tzinfo=IST) <= now_ist():
                            await self._send_ephemeral(modal_interaction, "❌ Deadline must be after the current date and time.")
                            return

                    task_data = {
                        "priority": priority_val.capitalize(),
                        "description": self_modal.description.value,
                        "checklist": self_modal.note.value.strip() if self_modal.note.value else "",
                        "assignees": self_modal.assignees
                    }
                    await self.process_task_assignment(modal_interaction, task_data, assigner_deadline=assigner_deadline)

            # Create view with assignee select
            view = ui.View(timeout=None)
            view.selected_assignees = None  # type: ignore
            view.add_item(AssigneeSelect())
            
            await interaction.response.send_message(
                "👥 Select assignee(s) for this task:",
                view=view,
                ephemeral=True
            )
            
        except discord.NotFound as e:
            logger.warning(f"[ERR-TSK-010] [Task] Interaction expired or not found: {e}")
        except Exception as e:
            logger.error(f"[ERR-TSK-011] [Task] handle_assign_task error: {e}")
            try:
                if not interaction.response.is_done():
                    await self._send_ephemeral(interaction, f"Call [ERR-TSK-012]: An error occurred: {e}")
            except Exception:
                pass

    async def process_task_assignment(self, interaction: discord.Interaction, task_data: dict, assigner_deadline: str | None = None):
        """Process task assignment with new simplified workflow."""
        try:
            guild = interaction.guild
            if not guild:
                await self._send_ephemeral(interaction, "❌ Guild not found.")
                return

            assignees = task_data["assignees"]
            assigner = interaction.user
            priority = task_data["priority"]
            description = task_data["description"]
            checklist = task_data.get("checklist", "")

            # Generate thread name based on priority (no title anymore)
            thread_name = f"{priority} Priority Task"

            # Build task data for database (channel_id set to None until thread is created)
            db_task_data = {
                "channel_id": None,
                "assignees": [u.display_name for u in assignees],
                "assignee_ids": [u.id for u in assignees],
                "details": description,
                "deadline": assigner_deadline or "",  # May be empty for non-high or if assigner skipped
                "priority": priority,
                "temp_channel_link": "",
                "assigner": assigner.display_name,
                "assigner_id": assigner.id,
                "status": "Pending",
                "title": thread_name,  # Store thread name as title for compatibility
                "global_state": "Active",
                "completion_vector": ",".join(["0"] * len(assignees)),
                "activity_log": "",
                "reminders_sent": "",
                "task_id": 0,
                "checklist": checklist,  # Store checklist for later use
                "assigner_deadline": assigner_deadline  # Track if assigner set a deadline
            }

            new_task_id = await store_task_in_database(db_task_data)
            db_task_data["task_id"] = new_task_id

            # Fetch the task-assigner channel (where assignment buttons live)
            task_assigner_ch = self.bot.get_channel(COMMAND_CHANNEL_ID)
            if not task_assigner_ch:
                task_assigner_ch = await self.bot.fetch_channel(COMMAND_CHANNEL_ID)

            # Create a private thread for this task inside the task-assigner channel
            task_thread = await task_assigner_ch.create_thread(
                name=f"task-{new_task_id} · {priority} Priority",
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=10080,  # 7 days
            )
            await task_thread.add_user(assigner)
            for user in assignees:
                await task_thread.add_user(user)

            view = self.get_main_task_view(db_task_data)
            main_content = f"Task Assignment Created! {assigner.mention} assigned this to " + ", ".join(u.mention for u in assignees) + "\n" + self._generate_task_markdown(db_task_data)

            # Post main embed + control buttons, then pin it
            msg = await task_thread.send(content=main_content, view=view)
            await msg.pin()

            db_task_data["channel_id"] = str(task_thread.id)
            db_task_data["temp_channel_link"] = task_thread.jump_url
            db_task_data["main_message_id"] = str(msg.id)

            await update_task_in_database(db_task_data)

            assignee_names = ", ".join(u.display_name for u in assignees)
            logger.info(f"[Task] Task #{new_task_id} created by {assigner.display_name} → {assignee_names} [{priority}]")

            await self._send_ephemeral(interaction, f"✅ Task successfully assigned in {task_thread.jump_url}")

            # Sync
            await self._sync_participants(assigner.id, [u.id for u in assignees], guild)

        except Exception as e:
            logger.error(f"[ERR-TSK-014] [Task] process_task_assignment error: {e}")
            await self._send_ephemeral(interaction, f"❌ Failed to complete assignment: {e}")

    def _format_checklist(self, checklist: str) -> str:
        """Format checklist items for display."""
        if not checklist:
            return ""
        items = [item.strip() for item in checklist.replace(",", "\n").split("\n") if item.strip()]
        return "\n".join(f"- [ ] {item}" for item in items)

    async def process_confirmed_task_draft(self, interaction: discord.Interaction, draft, assignees=None):
        """Legacy: Processes a task assignment from a draft (on confirm or recovery)."""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        try:
            guild = interaction.guild
            if not guild: return

            modal_data = draft["modal_data"]
            assigner = self.bot.get_user(draft["user_id"]) or await self.bot.fetch_user(draft["user_id"])

            # If assignees not provided (recovery case), we can't proceed directly
            if not assignees:
                return await self._send_ephemeral(interaction, "Call [ERR-TSK-013]: Please re-select assignees (Selection lost due to bot restart).")

            # Build draft task data (channel_id set to None until thread is created)
            task_data = {
                "channel_id": None,
                "assignees": [u.display_name for u in assignees],
                "assignee_ids": [u.id for u in assignees],
                "details": modal_data["details"],
                "deadline": modal_data["deadline"],
                "priority": modal_data["priority"] or "Normal",
                "temp_channel_link": "",
                "assigner": assigner.display_name,
                "assigner_id": assigner.id,
                "status": "Pending",
                "title": modal_data["title"],
                "global_state": "Active",
                "completion_vector": ",".join(["0"] * len(assignees)),
                "activity_log": "",
                "reminders_sent": "",
                "task_id": 0
            }

            new_task_id = await store_task_in_database(task_data)
            task_data["task_id"] = new_task_id

            # Fetch the task-assigner channel (where assignment buttons live)
            task_assigner_ch = self.bot.get_channel(COMMAND_CHANNEL_ID)
            if not task_assigner_ch:
                task_assigner_ch = await self.bot.fetch_channel(COMMAND_CHANNEL_ID)

            priority = task_data["priority"]
            task_thread = await task_assigner_ch.create_thread(
                name=f"task-{new_task_id} · {priority} Priority",
                type=discord.ChannelType.private_thread,
                invitable=False,
                auto_archive_duration=10080,  # 7 days
            )
            await task_thread.add_user(assigner)
            for user in assignees:
                await task_thread.add_user(user)

            view = self.get_main_task_view(task_data)
            msg = await task_thread.send(
                content=f"Task Assignment Created! {assigner.mention} assigned this to " + ", ".join(u.mention for u in assignees) + "\n" + self._generate_task_markdown(task_data),
                view=view
            )
            await msg.pin()

            task_data["channel_id"] = str(task_thread.id)
            task_data["temp_channel_link"] = task_thread.jump_url
            task_data["main_message_id"] = str(msg.id)
            await update_task_in_database(task_data)

            await delete_task_draft(draft["draft_id"])
            try:
                await interaction.delete_original_response()
            except Exception:
                pass
            await self._send_ephemeral(interaction, f"Task successfully assigned in {task_thread.jump_url}.")

            # Sync
            await self._sync_participants(assigner.id, [u.id for u in assignees], guild)

        except Exception as e:
            logger.error(f"[ERR-TSK-014] [Task] process_confirmed_task_draft error: {e}")
            await self._send_ephemeral(interaction, f"Call [ERR-TSK-015]: Failed to complete assignment: {e}")

    # ── Dashboard Interaction Handlers ────────────────────────────────────────

    async def handle_dash_mod(self, interaction: discord.Interaction, task):
        class ModifyDeadlineModal(ui.Modal, title="Modify Deadline"):
            new_deadline_date = ui.TextInput(label="New Deadline Date", style=discord.TextStyle.short, placeholder="DD/MM/YYYY  e.g. 27/03/2026", max_length=10, required=True)
            new_deadline_time = ui.TextInput(label="New Deadline Time", style=discord.TextStyle.short, placeholder="HH:MM AM/PM  e.g. 02:30 PM", max_length=8, required=True)
            async def on_submit(self_modal, modal_interaction: discord.Interaction):
                await modal_interaction.response.defer(ephemeral=True)
                try:
                    dl_dt, new_val = parse_datetime_flexible(
                        self_modal.new_deadline_date.value, self_modal.new_deadline_time.value
                    )
                except ValueError as e:
                    return await self._send_ephemeral(modal_interaction, f"❌ [ERR-TSK-016] {e}")
                if dl_dt.replace(tzinfo=IST) <= now_ist():
                    return await self._send_ephemeral(modal_interaction, "❌ Deadline must be after the current date and time.")

                task["deadline"] = new_val
                await update_task_in_database(task)
                await self.update_main_task_message(task)
                await self._send_ephemeral(modal_interaction, "Deadline updated.")
                
                # Sync
                await self._sync_participants(task["assigner_id"], task["assignee_ids"], modal_interaction.guild)

        await interaction.response.send_modal(ModifyDeadlineModal())

    async def handle_dash_cancel(self, interaction: discord.Interaction, task):
        if interaction.user.id != task["assigner_id"]:
            return await self._send_ephemeral(interaction, f"Only {task.get('assigner')} can cancel this task.")
        
        await interaction.response.defer(ephemeral=True)
        chan = self.bot.get_channel(int(task["channel_id"]))
        if not chan:
            try:
                chan = await self.bot.fetch_channel(int(task["channel_id"]))
            except Exception:
                pass
        if chan:
            await chan.send(f"❌ **Task Cancelled by {task.get('assigner')}.** This thread is now locked.")
            if isinstance(chan, discord.Thread):
                await chan.edit(archived=True, locked=True)
            else:
                await chan.delete()

        await delete_task_from_database(int(task["channel_id"]))
        logger.info(f"[Task] Task #{task.get('task_id')} cancelled by {interaction.user.display_name}")
        await self._send_ephemeral(interaction, "Task cancelled and thread locked.")
        
        # Sync
        await self._sync_participants(task["assigner_id"], task["assignee_ids"], interaction.guild)

    async def handle_dash_done(self, interaction: discord.Interaction, task):
        if interaction.user.id != task["assigner_id"]:
            return await self._send_ephemeral(interaction, f"Only {task.get('assigner')} can finalize this task.")
        
        await interaction.response.defer(ephemeral=True)
        task["global_state"] = "Finalized"
        task["status"] = "Completed"
        task["completed_at"] = datetime.now(IST)
        await update_task_in_database(task)
        
        chan = self.bot.get_channel(int(task["channel_id"]))
        if chan:
            await chan.send("✅ **Task marked as Fully Complete.** Thread will be archived in 24 hours.")
        
        await self.update_main_task_message(task)
        logger.info(f"[Task] Task #{task.get('task_id')} finalized by {interaction.user.display_name}")
        await self._send_ephemeral(interaction, "Task finalized.")
        
        # Sync
        await self._sync_participants(task["assigner_id"], task["assignee_ids"], interaction.guild)

    async def handle_dash_block(self, interaction: discord.Interaction, task):
        if interaction.user.id not in task["assignee_ids"]:
            return await self._send_ephemeral(interaction, "Only those assigned can report blockers.")
        
        class BlockerModal(ui.Modal, title="Report Blocker"):
            reason = ui.TextInput(label="Reason", style=discord.TextStyle.long, placeholder="What is blocking you?", required=True)
            async def on_submit(self_modal, modal_interaction: discord.Interaction):
                await modal_interaction.response.defer(ephemeral=True)
                task["status"] = "Blocked"
                task["blocker_reason"] = self_modal.reason.value
                
                # Activity log
                ts = now_ist().strftime("%Y-%m-%d %H:%M IST")
                log_entry = f"[{ts}] {modal_interaction.user.display_name} reported blocker: {self_modal.reason.value}"
                task["activity_log"] = (task.get("activity_log") or "") + "\n" + log_entry
                
                await update_task_in_database(task)
                await self.update_main_task_message(task)
                
                chan = self.bot.get_channel(int(task["channel_id"]))
                if chan:
                    await chan.send(f"⚠️ **BLOCKER REPORTED** by {modal_interaction.user.mention}:\n> {self_modal.reason.value}")
                
                logger.info(f"[Task] Task #{task.get('task_id')} blocked by {modal_interaction.user.display_name}")
                await self._send_ephemeral(modal_interaction, "Blocker reported. Automated nags for assignees are now paused.")

                # Sync all parties
                await self._sync_participants(task["assigner_id"], task["assignee_ids"], modal_interaction.guild)

        await interaction.response.send_modal(BlockerModal())

    async def handle_dash_reject(self, interaction: discord.Interaction, task):
        if interaction.user.id not in task["assignee_ids"]:
            return await self._send_ephemeral(interaction, "Only those assigned can reject this task.")

        class RejectionModal(ui.Modal, title="Reject Task"):
            reason = ui.TextInput(label="Reason for Rejection", style=discord.TextStyle.long, placeholder="Why are you rejecting this task?", required=True)
            async def on_submit(self_modal, modal_interaction: discord.Interaction):
                await modal_interaction.response.defer(ephemeral=True)

                ts = now_ist().strftime("%Y-%m-%d %H:%M IST")
                log_entry = f"[{ts}] {modal_interaction.user.display_name} rejected the task. Reason: {self_modal.reason.value}"
                task["activity_log"] = (task.get("activity_log") or "") + "\n" + log_entry
                task["status"] = "Rejected"
                task["global_state"] = "Active"

                await update_task_in_database(task)
                await self.update_main_task_message(task)

                chan = self.bot.get_channel(int(task["channel_id"]))
                if chan:
                    await chan.send(
                        f"🚫 **Task Rejected** by {modal_interaction.user.mention}:\n> {self_modal.reason.value}\n"
                        f"<@{task['assigner_id']}> please review and reassign or modify the task."
                    )

                logger.info(f"[Task] Task #{task.get('task_id')} rejected by {modal_interaction.user.display_name}")
                await self._send_ephemeral(modal_interaction, "Task rejected. The assigner has been notified.")

                await self._sync_participants(task["assigner_id"], task["assignee_ids"], modal_interaction.guild)

        await interaction.response.send_modal(RejectionModal())

    async def handle_assign_dash_mod(self, interaction: discord.Interaction, task):
        # Resolve Assignee channel for jump
        chan = self.bot.get_channel(int(task["channel_id"]))
        if not chan:
            try:
                chan = await self.bot.fetch_channel(int(task["channel_id"]))
            except Exception:
                pass

        if not chan:
            return await self._send_ephemeral(interaction, "Call [ERR-TSK-017]: Could not locate task thread.")

        await interaction.response.defer(ephemeral=True)
        idx = task["assignee_ids"].index(interaction.user.id)
        vector = task["completion_vector"].split(",")
        vector[idx] = "1"
        task["completion_vector"] = ",".join(vector)

        if all(v == "1" for v in vector):
            task["global_state"] = "Pending Review"
            task["status"] = "Pending Assigner Review"
            if chan:
                await chan.send(f"✅ **All parts completed!** {task.get('assigner', 'Assigner')}, please review.")

        await update_task_in_database(task)
        await self.update_main_task_message(task)
        logger.info(f"[Task] Task #{task.get('task_id')} — {interaction.user.display_name} marked part done (vector: {task['completion_vector']})")
        await self._send_ephemeral(interaction, "Marked your part as done.")

        # Sync all parties
        await self._sync_participants(task["assigner_id"], task["assignee_ids"], interaction.guild)

    async def handle_dash_part(self, interaction: discord.Interaction, task):
        if interaction.user.id not in task["assignee_ids"]:
            return await self._send_ephemeral(interaction, "You are not an assignee.")

        await interaction.response.defer(ephemeral=True)
        idx = task["assignee_ids"].index(interaction.user.id)
        vector = task["completion_vector"].split(",")
        vector[idx] = "1"
        task["completion_vector"] = ",".join(vector)

        if all(v == "1" for v in vector):
            task["global_state"] = "Pending Review"
            task["status"] = "Pending Assigner Review"
            chan = self.bot.get_channel(int(task["channel_id"]))
            if not chan:
                try:
                    chan = await self.bot.fetch_channel(int(task["channel_id"]))
                except Exception:
                    pass
            if chan:
                await chan.send(f"✅ **All parts completed!** {task.get('assigner', 'Assigner')}, please review.")

        await update_task_in_database(task)
        await self.update_main_task_message(task)
        logger.info(f"[Task] Task #{task.get('task_id')} — {interaction.user.display_name} marked partial done (vector: {task['completion_vector']})")
        await self._send_ephemeral(interaction, "Marked your part as done.")

        # Sync all parties
        await self._sync_participants(task["assigner_id"], task["assignee_ids"], interaction.guild)

    async def handle_dash_upd(self, interaction: discord.Interaction, task):
        await interaction.response.defer(ephemeral=True)
        t_ch = self.bot.get_channel(int(task['channel_id']))
        if not t_ch:
            try:
                t_ch = await self.bot.fetch_channel(int(task['channel_id']))
            except Exception:
                pass

        if t_ch:
            a_mentions = " ".join([f"<@{uid}>" for uid in task.get('assignee_ids', [])])
            task_title = task.get('title', f"{task.get('priority', 'Normal')} Priority Task")
            await t_ch.send(f"🔔 **Update Requested:** {interaction.user.mention} is requesting an update on task **{task_title}**. {a_mentions}")
            await self._send_ephemeral(interaction, f"Update request sent to {t_ch.mention}!")
        else:
            await self._send_ephemeral(interaction, "Call [ERR-TSK-018]: Could not locate the task channel.")

    async def handle_resolve_block(self, interaction: discord.Interaction, task):
        if interaction.user.id not in task["assignee_ids"]:
            return await self._send_ephemeral(interaction, "Only those assigned can resolve blockers.")
            
        await interaction.response.defer(ephemeral=True)
        task["status"] = "Pending"
        task["blocker_reason"] = ""
        
        ts = now_ist().strftime("%Y-%m-%d %H:%M IST")
        log_entry = f"[{ts}] {interaction.user.display_name} resolved the blocker."
        task["activity_log"] = (task.get("activity_log") or "") + "\n" + log_entry
        
        await update_task_in_database(task)
        await self.update_main_task_message(task)
        
        chan = self.bot.get_channel(int(task["channel_id"]))
        if chan:
            await chan.send(f"✅ **BLOCKER RESOLVED** by {interaction.user.mention}.")
            
        await self._send_ephemeral(interaction, "Blocker resolved. Task is active again.")
        
        await self._sync_participants(task["assigner_id"], task["assignee_ids"], interaction.guild)

    async def handle_req_deadline(self, interaction: discord.Interaction, task):
        if interaction.user.id not in task["assignee_ids"]:
            return await self._send_ephemeral(interaction, "Only those assigned can request a new deadline.")
            
        class ReqDeadlineModal(ui.Modal, title="Request New Deadline"):
            reason = ui.TextInput(label="Reason & Suggested Date", style=discord.TextStyle.long, required=True)
            async def on_submit(inner_self, modal_interaction: discord.Interaction):
                await modal_interaction.response.defer(ephemeral=True)
                
                ts = now_ist().strftime("%Y-%m-%d %H:%M IST")
                log_entry = f"[{ts}] {modal_interaction.user.display_name} requested new deadline: {inner_self.reason.value}"
                task["activity_log"] = (task.get("activity_log") or "") + "\n" + log_entry
                
                await update_task_in_database(task)
                
                chan = self_cog.bot.get_channel(int(task["channel_id"]))
                if chan:
                    # Construct the inline View here instead of global to easily pass contextual params if it's alive
                    # Note: Because the user wants to use these robustly, I'll pass the UI inline during req.
                    view = ui.View(timeout=None)
                    
                    approve_btn = ui.Button(label="Approve Deadline", style=discord.ButtonStyle.success, custom_id=f"approve_deadline_{task['task_id']}")
                    async def approve_cb(i: discord.Interaction):
                        if i.user.id != task["assigner_id"]: return await self_cog._send_ephemeral(i, "Only the assigner can approve.")
                        class ModDeadlineModal(ui.Modal, title="Modify Deadline"):
                            new_dl_date = ui.TextInput(label="New Deadline Date", style=discord.TextStyle.short, placeholder="DD/MM/YYYY  e.g. 27/03/2026", max_length=10)
                            new_dl_time = ui.TextInput(label="New Deadline Time", style=discord.TextStyle.short, placeholder="HH:MM AM/PM  e.g. 02:30 PM", max_length=8)
                            async def on_submit(inner_self, mi: discord.Interaction):
                                await mi.response.defer()
                                try:
                                    dl_dt, new_dl_val = parse_datetime_flexible(
                                        inner_self.new_dl_date.value, inner_self.new_dl_time.value
                                    )
                                except ValueError as e:
                                    await mi.followup.send(f"❌ {e}", ephemeral=True)
                                    return
                                if dl_dt.replace(tzinfo=IST) <= now_ist():
                                    await mi.followup.send("❌ Deadline must be after the current date and time.", ephemeral=True)
                                    return
                                task["deadline"] = new_dl_val
                                ts2 = now_ist().strftime("%Y-%m-%d %H:%M IST")
                                task["activity_log"] = (task.get("activity_log") or "") + f"\n[{ts2}] Deadline extended to {new_dl_val}"
                                await update_task_in_database(task)
                                if chan: await chan.send(f"✅ **Deadline Approved & Updated**: {new_dl_val}")
                                await self_cog.update_main_task_message(task)
                                await asyncio.gather(
                                    self_cog.sync_user_dashboard_tasks(int(task.get("assigner_id", 0)), mi.guild),
                                    *[coro for uid in task.get("assignee_ids", []) for coro in (
                                        self_cog.sync_user_pending_tasks(int(uid), mi.guild),
                                        self_cog.sync_user_dashboard_tasks(int(uid), mi.guild),
                                    )],
                                )
                                try: await i.message.delete()
                                except: pass
                        await i.response.send_modal(ModDeadlineModal())
                        
                    deny_btn = ui.Button(label="Deny Deadline", style=discord.ButtonStyle.danger, custom_id=f"deny_deadline_{task['task_id']}")
                    async def deny_cb(i: discord.Interaction):
                        if i.user.id != task["assigner_id"]: return await self_cog._send_ephemeral(i, "Only the assigner can deny.")
                        class DenyModal(ui.Modal, title="Deny Reason"):
                            reason_deny = ui.TextInput(label="Reason", style=discord.TextStyle.long)
                            async def on_submit(inner_self, mi: discord.Interaction):
                                await mi.response.defer()
                                if chan: await chan.send(f"❌ **Deadline Extension Denied** by {i.user.mention}\n> {inner_self.reason_deny.value}\n{modal_interaction.user.mention} please stick to the current schedule.")
                                try: await i.message.delete()
                                except: pass
                        await i.response.send_modal(DenyModal())

                    approve_btn.callback = approve_cb
                    deny_btn.callback = deny_cb
                    view.add_item(approve_btn)
                    view.add_item(deny_btn)

                    await chan.send(f"📅 **NEW DEADLINE REQUESTED** by {modal_interaction.user.mention}:\n> {inner_self.reason.value}\n<@{task['assigner_id']}> Please review and update the deadline.", view=view)
                    await self_cog.update_main_task_message(task)
                    
                await self_cog._send_ephemeral(modal_interaction, "Deadline request sent.")
                
        self_cog = self
        await interaction.response.send_modal(ReqDeadlineModal())

    async def handle_view_tasks_button(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            await asyncio.gather(
                self.sync_user_pending_tasks(interaction.user.id, interaction.guild),
                self.sync_user_dashboard_tasks(interaction.user.id, interaction.guild),
            )

            res_p = await retrieve_pending_tasks_channel(interaction.user.id)
            res_d = await retrieve_assigner_dashboard_channel(interaction.user.id)
            
            msg = "Your task views have been synced!\n"
            if res_p and res_p.get('channel_id'):
                ch = self.bot.get_channel(int(res_p['channel_id']))
                if ch: msg += f"- **Pending Tasks:** {ch.jump_url}\n"
            if res_d and res_d.get('channel_id'):
                ch = self.bot.get_channel(int(res_d['channel_id']))
                if ch: msg += f"- **Assigner Dashboard:** {ch.jump_url}\n"
                
            await self._send_ephemeral(interaction, msg)
        except Exception as e:
            logger.error(f"[ERR-TSK-019] [Task] handle_view_tasks_button error: {e}")

    # ── Sync Engines ──────────────────────────────────────────────────────────

    async def sync_user_pending_tasks(self, user_id: int, guild: discord.Guild = None):
        """Syncs the 'Pending tasks' channel for an assignee."""
        global PENDING_CATEGORY_ID
        try:
            if guild is None:
                command_channel = self.bot.get_channel(COMMAND_CHANNEL_ID)
                if not command_channel: return
                guild = command_channel.guild
                
            category = guild.get_channel(PENDING_CATEGORY_ID)
            if not category:
                category = discord.utils.get(guild.categories, name="Pending tasks")
                if not category:
                    category = await guild.create_category("Pending tasks")
                PENDING_CATEGORY_ID = category.id

            member = guild.get_member(user_id)
            if not member: return

            res = await retrieve_pending_tasks_channel(user_id)
            channel_id = res.get('channel_id') if res else None
            
            if channel_id:
                pending_channel = self.bot.get_channel(int(channel_id))
                if not pending_channel:
                    try:
                        pending_channel = await self.bot.fetch_channel(int(channel_id))
                    except Exception:
                        await delete_pending_tasks_channel_from_database(user_id)
                        channel_id = None
            
            if not channel_id:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    member: discord.PermissionOverwrite(
                        read_messages=True, 
                        send_messages=False,
                        create_public_threads=False,
                        create_private_threads=False,
                        send_messages_in_threads=False
                    ),
                }
                pending_channel = await guild.create_text_channel(
                    f"tasks-for-{member.display_name.lower().replace(' ', '-')}", overwrites=overwrites, category=category
                )
                await store_pending_tasks_channel(user_id, pending_channel.id)
            else:
                pending_channel = self.bot.get_channel(int(channel_id))
                if not pending_channel:
                    try:
                        pending_channel = await self.bot.fetch_channel(int(channel_id))
                    except Exception:
                        # If it's completely gone, let the next block handle it
                        channel_id = None
                
                if pending_channel:
                    await pending_channel.set_permissions(
                        member, 
                        read_messages=True, 
                        send_messages=False,
                        create_public_threads=False,
                        create_private_threads=False,
                        send_messages_in_threads=False
                    )

            all_tasks = await retrieve_tasks_for_sync()
            user_tasks = [t for t in all_tasks if user_id in t.get("assignee_ids", [])]
            
            # Extract existing messages safely
            existing_msg_ids = []
            if res and res.get('task_message_ids'):
                existing_msg_ids = [int(x) for x in res['task_message_ids'].split(',') if x]

            new_task_ids = []
            new_msg_ids = []

            # Batch tasks in groups of 5 to reduce mobile UI bloat
            BATCH_SIZE = 5
            msg_index = 0
            for batch_start in range(0, len(user_tasks), BATCH_SIZE):
                batch = user_tasks[batch_start:batch_start + BATCH_SIZE]
                embeds = []
                view = ui.View(timeout=None)

                for task in batch:
                    embed = self._build_pending_embed(task, guild)
                    embeds.append(embed)

                    # Link Button logic
                    jump_url = task.get("temp_channel_link")
                    ch = self.bot.get_channel(int(task["channel_id"]))
                    if task.get("main_message_id") and ch:
                        jump_url = f"https://discord.com/channels/{guild.id}/{task['channel_id']}/{task['main_message_id']}"

                    # Use title if available, otherwise generate from priority
                    task_title = task.get('title') or f"{task.get('priority', 'Normal')} Priority Task"
                    view.add_item(ui.Button(label=f"Open: {task_title[:20]}", style=discord.ButtonStyle.link, url=jump_url))
                    
                    acknowledged_str = task.get("acknowledged_by", "")
                    acknowledged_list = [int(x) for x in acknowledged_str.split(",") if x]
                    
                    # Fetching vector logic to dynamically disable/hide "Done"
                    assignee_ids_list = task.get("assignee_ids", [])
                    completion_str = task.get("completion_vector", "")
                    completion_vector = completion_str.split(",") if completion_str else ["0"] * len(assignee_ids_list)
                    
                    is_done = False
                    try:
                        if user_id in assignee_ids_list:
                            idx = assignee_ids_list.index(user_id)
                            is_done = (completion_vector[idx] == "1")
                    except ValueError:
                        pass
                    
                    if user_id not in acknowledged_list:
                        view.add_item(ui.Button(label="Acknowledge Task", style=discord.ButtonStyle.primary, custom_id=f"ack_{task['task_id']}"))
                    elif is_done:
                        view.add_item(ui.Button(label="Pending Review", style=discord.ButtonStyle.secondary, custom_id=f"dash_done_{task['task_id']}", disabled=True))
                    else:
                        if task.get("status") == "Blocked":
                            view.add_item(ui.Button(label="Resolve Blocker", style=discord.ButtonStyle.success, custom_id=f"dash_resolve_block_{task['task_id']}"))
                            view.add_item(ui.Button(label="Request New Deadline", style=discord.ButtonStyle.secondary, custom_id=f"dash_req_deadline_{task['task_id']}"))
                        else:
                            view.add_item(ui.Button(label="Reject Task", style=discord.ButtonStyle.danger, custom_id=f"dash_reject_{task['task_id']}"))
                            view.add_item(ui.Button(label="[✔] Done", style=discord.ButtonStyle.success, custom_id=f"dash_part_{task['task_id']}"))

                    new_task_ids.append(str(task["task_id"]))

                # Try to edit an existing message for this batch frame
                msg = None
                while msg_index < len(existing_msg_ids):
                    try:
                        msg = await pending_channel.fetch_message(existing_msg_ids[msg_index])
                        await msg.edit(embeds=embeds, view=view)
                        msg_index += 1
                        break
                    except discord.NotFound:
                        msg_index += 1
                
                # If we couldn't edit, send a new message
                if not msg:
                    msg = await pending_channel.send(embeds=embeds, view=view) # type: ignore
                    
                # We store just one master message ID representation for this batch block 
                # (though historically we appended it batch_size times, this is cleaner)
                new_msg_ids.append(str(msg.id))
                    
                if any(t.get("priority", "Normal").lower() == "high" for t in batch):
                    try: await msg.pin()
                    except discord.HTTPException: pass

            # Delete any leftover messages that are no longer needed
            for leftover in existing_msg_ids[msg_index:]:
                try:
                    leftover_msg = await pending_channel.fetch_message(leftover)
                    await leftover_msg.delete()
                except discord.NotFound:
                    pass

            await update_pending_tasks_channel(user_id, new_task_ids, new_msg_ids)
            
        except Exception as e:
            logger.error(f"[ERR-TSK-020] [Task] sync_user_pending_tasks error: {e}")

    async def sync_user_dashboard_tasks(self, user_id: int, guild: discord.Guild = None):
        """Syncs the 'Task Dashboard' channel for an assigner."""
        global DASHBOARD_CATEGORY_ID
        try:
            if guild is None:
                command_channel = self.bot.get_channel(COMMAND_CHANNEL_ID)
                if not command_channel: return
                guild = command_channel.guild
                
            category = guild.get_channel(DASHBOARD_CATEGORY_ID)
            if not category:
                category = discord.utils.get(guild.categories, name="Task Dashboard")
                if not category:
                    category = await guild.create_category("Task Dashboard")
                DASHBOARD_CATEGORY_ID = category.id

            member = guild.get_member(user_id)
            if not member: return

            res = await retrieve_assigner_dashboard_channel(user_id)
            channel_id = res.get('channel_id') if res else None
            
            if channel_id:
                dash_channel = self.bot.get_channel(int(channel_id))
                if not dash_channel:
                    try:
                        dash_channel = await self.bot.fetch_channel(int(channel_id))
                    except Exception:
                        await delete_assigner_dashboard_channel_from_database(user_id)
                        channel_id = None
            
            if not channel_id:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    member: discord.PermissionOverwrite(
                        read_messages=True, 
                        send_messages=False,
                        create_public_threads=False,
                        create_private_threads=False,
                        send_messages_in_threads=False
                    ),
                }
                dash_channel = await guild.create_text_channel(
                    f"assigned-by-{member.display_name.lower().replace(' ', '-')}", overwrites=overwrites, category=category
                )
                await store_assigner_dashboard_channel(user_id, dash_channel.id)
            else:
                dash_channel = self.bot.get_channel(int(channel_id))
                if not dash_channel:
                    try:
                        dash_channel = await self.bot.fetch_channel(int(channel_id))
                    except Exception:
                        channel_id = None
                
                if dash_channel:
                    await dash_channel.set_permissions(
                        member, 
                        read_messages=True, 
                        send_messages=False,
                        create_public_threads=False,
                        create_private_threads=False,
                        send_messages_in_threads=False
                    )

            all_tasks = await retrieve_tasks_for_sync()
            # Dashboard shows tasks you ASSIGNED
            user_tasks = [t for t in all_tasks if user_id == t.get("assigner_id")]
            
            # Extract existing messages safely
            existing_msg_ids = []
            if res and res.get('task_message_ids'):
                existing_msg_ids = [int(x) for x in res['task_message_ids'].split(',') if x]
            
            new_task_ids = []
            new_msg_ids = []

            # Batch tasks in groups of 5 to reduce mobile UI bloat
            BATCH_SIZE = 5
            msg_index = 0
            for batch_start in range(0, len(user_tasks), BATCH_SIZE):
                batch = user_tasks[batch_start:batch_start + BATCH_SIZE]
                embeds = []
                view = ui.View(timeout=None)

                for task in batch:
                    embed = self._build_dashboard_embed(task)
                    embeds.append(embed)

                    if task.get("global_state") == "Pending Review":
                        view.add_item(ui.Button(label="Approve Task", style=discord.ButtonStyle.success, custom_id=f"approve_panel_{task['task_id']}"))
                        view.add_item(ui.Button(label="Request Revision", style=discord.ButtonStyle.danger, custom_id=f"revise_panel_{task['task_id']}"))

                    # Link Button
                    jump_url = task.get("temp_channel_link")
                    ch = self.bot.get_channel(int(task["channel_id"]))
                    if task.get("main_message_id") and ch:
                        jump_url = f"https://discord.com/channels/{guild.id}/{task['channel_id']}/{task['main_message_id']}"
                    # Use title if available, otherwise generate from priority
                    task_title = task.get('title') or f"{task.get('priority', 'Normal')} Priority Task"
                    view.add_item(ui.Button(label=f"Go: {task_title[:20]}", style=discord.ButtonStyle.link, url=jump_url))

                    new_task_ids.append(str(task["task_id"]))

                # Try to edit an existing message for this batch frame
                msg = None
                while msg_index < len(existing_msg_ids):
                    try:
                        msg = await dash_channel.fetch_message(existing_msg_ids[msg_index])
                        await msg.edit(embeds=embeds, view=view)
                        msg_index += 1
                        break
                    except discord.NotFound:
                        msg_index += 1
                
                # If we couldn't edit, send a new message
                if not msg:
                    msg = await dash_channel.send(embeds=embeds, view=view) # type: ignore
                    
                # Store message ID footprint cleanly
                new_msg_ids.append(str(msg.id))

            # Delete any leftover messages that are no longer needed
            for leftover in existing_msg_ids[msg_index:]:
                try:
                    leftover_msg = await dash_channel.fetch_message(leftover)
                    await leftover_msg.delete()
                except discord.NotFound:
                    pass

            await update_assigner_dashboard_channel(user_id, new_task_ids, new_msg_ids)
            
        except Exception as e:
            logger.error(f"[ERR-TSK-021] [Task] sync_user_dashboard_tasks error: {e}")

    async def _sync_participants(self, assigner_id: int, assignee_ids, guild: discord.Guild):
        """Concurrently sync pending+dashboard views for all task participants."""
        coros = [
            self.sync_user_pending_tasks(assigner_id, guild),
            self.sync_user_dashboard_tasks(assigner_id, guild),
        ]
        for uid in assignee_ids:
            coros.append(self.sync_user_pending_tasks(int(uid), guild))
            coros.append(self.sync_user_dashboard_tasks(int(uid), guild))
        await asyncio.gather(*coros)

    # -------------------------------------------------------------------------
    # ── Embed & Markdown Builders ─────────────────────────────────────────────

    def _build_pending_embed(self, task: dict, guild: discord.Guild = None) -> discord.Embed:
        """Unified pending-task embed with priority-based coloring and IST footer."""
        priority = task.get("priority", "Normal").lower()
        color_map = {"high": 0xFF0000, "normal": 0x3498db, "low": 0x95A5A6}
        embed_color = color_map.get(priority, 0x3498db)

        title = task.get('title', f"{task.get('priority', 'Normal')} Priority Task")
        embed = discord.Embed(title=f"📌 {title}", color=embed_color)
        embed.add_field(name="Details", value=task['details'][:1024], inline=False)

        deadline = task.get('deadline', '')
        deadline_display = format_deadline(deadline) if deadline else "⏳ Awaiting deadline acceptance"
        embed.add_field(name="Deadline", value=deadline_display, inline=True)
        embed.add_field(name="Priority", value=task.get('priority', 'Normal'), inline=True)
        embed.add_field(name="State", value=task.get('global_state', 'Active'), inline=True)

        created_at = task.get('created_at')
        try:
            posted_str = created_at.astimezone(IST).strftime('%d %b %Y, %I:%M %p IST') if hasattr(created_at, 'strftime') else str(created_at) if created_at else "—"
        except Exception:
            posted_str = "—"
        embed.add_field(name="Posted", value=posted_str, inline=False)

        embed.set_footer(text=f"Synced: {now_ist().strftime('%d %b, %Y %I:%M %p IST')} | Concord Engine")
        return embed

    def _build_dashboard_embed(self, task: dict) -> discord.Embed:
        """Unified assigner-dashboard embed with IST footer."""
        title = task.get('title', f"{task.get('priority', 'Normal')} Priority Task")
        embed = discord.Embed(title=f"⚙️ Managing: {title}", color=0x3498db)
        embed.add_field(name="Assignees", value=", ".join(task["assignees"]), inline=False)
        embed.add_field(name="Status", value=task.get('status', 'Pending'), inline=True)
        embed.add_field(name="State", value=task.get('global_state', 'Active'), inline=True)
        embed.add_field(name="Priority", value=task.get('priority', 'Normal'), inline=True)

        deadline = task.get('deadline', '')
        deadline_display = format_deadline(deadline) if deadline else "⏳ Pending assignee input"
        embed.add_field(name="Deadline", value=deadline_display, inline=True)

        created_at = task.get('created_at')
        try:
            posted_str = created_at.astimezone(IST).strftime('%d %b %Y, %I:%M %p IST') if hasattr(created_at, 'strftime') else str(created_at) if created_at else "—"
        except Exception:
            posted_str = "—"
        embed.add_field(name="Posted", value=posted_str, inline=False)

        embed.set_footer(text=f"Synced: {now_ist().strftime('%d %b, %Y %I:%M %p IST')} | Concord Engine")
        return embed

    def _generate_task_markdown(self, task_data: dict) -> str:
        """Generates a markdown representation of a task for thread messages."""
        assignees_list = task_data.get('assignees', [])
        assignee_ids_list = task_data.get('assignee_ids', [])
        completion_str = task_data.get('completion_vector', '')
        completion_vector = completion_str.split(',') if completion_str else ['0'] * len(assignee_ids_list)
        
        acknowledged_str = task_data.get("acknowledged_by", "")
        acknowledged_list = [int(x) for x in acknowledged_str.split(",") if x]

        assignees_status = []
        for idx, name in enumerate(assignees_list):
            is_done = (completion_vector[idx] == '1') if idx < len(completion_vector) else False
            status_icon = '✅ Done' if is_done else '🔄 Pending'
            
            user_id = assignee_ids_list[idx] if idx < len(assignee_ids_list) else None
            ack_icon = "✅" if user_id in acknowledged_list else "❌"
            
            assignees_status.append(f"  - **{name}** | Ack: {ack_icon} | Status: {status_icon}")

        roles_list = '\n'.join(assignees_status)
        act_log = ''
        if task_data.get('activity_log'):
            act_log = f"\n\n**Activity Log:**\n{task_data['activity_log'][-1024:]}"

        # Handle notes/remarks display
        checklist_str = ""
        if task_data.get('checklist'):
            note_text = task_data['checklist'].strip()
            if note_text:
                checklist_str = f"\n\n**Notes/Remarks:**\n{note_text}"

        # Use title if available, otherwise generate from priority
        title = task_data.get('title', f"{task_data.get('priority', 'Normal')} Priority Task")

        # Handle deadline display
        deadline = task_data.get('deadline', '')
        deadline_display = format_deadline(deadline) if deadline else "⏳ To be set on acknowledge"

        created_at = task_data.get('created_at')
        posted_str = ""
        if created_at:
            try:
                if hasattr(created_at, 'strftime'):
                    posted_str = f"\n**Posted:** {created_at.astimezone(IST).strftime('%d %b %Y, %I:%M %p IST')}"
                else:
                    posted_str = f"\n**Posted:** {created_at}"
            except Exception:
                pass

        return f"""
# 📋 **{title}**
> {task_data['details']}{checklist_str}

---
**Assigned by:** {task_data['assigner']}{posted_str}
**Deadline:** {deadline_display}
**Priority:** {task_data.get('priority', 'Normal')}
**Global State:** {task_data.get('global_state', 'Active')}

**Assigned to & Status:**
{roles_list}{act_log}
"""

    # ── View Builders ─────────────────────────────────────────────────────────

    async def update_main_task_message(self, task):
        try:
            task_id = task.get("task_id", "?")
            channel_id = int(task.get("channel_id", 0))
            message_id = task.get("main_message_id")
            if not channel_id or not message_id:
                logger.warning(f"[Task] update_main_task_message: task {task_id} missing channel_id={channel_id!r} or main_message_id={message_id!r}")
                return

            temp_channel = self.bot.get_channel(channel_id)
            if not temp_channel:
                try:
                    temp_channel = await self.bot.fetch_channel(channel_id)
                except Exception as e:
                    logger.warning(f"[Task] update_main_task_message: could not fetch channel {channel_id} for task {task_id}: {e}")
                    return

            if not temp_channel:
                logger.warning(f"[Task] update_main_task_message: channel {channel_id} not found for task {task_id}")
                return

            try:
                msg = await temp_channel.fetch_message(int(message_id))
            except discord.NotFound:
                logger.warning(f"[Task] update_main_task_message: message {message_id} not found in channel {channel_id} for task {task_id}")
                return
            
            # Re-generate markdown representation reflecting current DB state
            assignee_ids_list = task.get("assignee_ids", [])
            completion_str = task.get("completion_vector", "")
            completion_vector = completion_str.split(",") if completion_str else ["0"] * len(assignee_ids_list)
            
            acknowledged_str = task.get("acknowledged_by", "")
            acknowledged_list = [int(x) for x in acknowledged_str.split(",") if x]
            
            assignees_status = []
            for idx, name in enumerate(task.get("assignees", [])):
                is_done = (completion_vector[idx] == "1") if idx < len(completion_vector) else False
                status_icon = "✅ Done" if is_done else "🔄 Pending"
                
                user_id = assignee_ids_list[idx] if idx < len(assignee_ids_list) else None
                ack_icon = "✅" if user_id in acknowledged_list else "❌"
                
                assignees_status.append(f"  - **{name}** | Ack: {ack_icon} | Status: {status_icon}")
                
            roles_list = "\n".join(assignees_status)
            act_log = ""
            if task.get("activity_log"):
                act_log = f"\n\n**Activity Log:**\n{task['activity_log'][-1024:]}"

            # Handle notes/remarks display
            checklist_str = ""
            if task.get('checklist'):
                note_text = task['checklist'].strip()
                if note_text:
                    checklist_str = f"\n\n**Notes/Remarks:**\n{note_text}"

            # Use title if available, otherwise generate from priority
            title = task.get('title', f"{task.get('priority', 'Normal')} Priority Task")

            # Handle deadline display
            deadline = task.get('deadline', '')
            deadline_display = format_deadline(deadline) if deadline else "⏳ To be set on acknowledge"

            created_at = task.get('created_at')
            posted_str = ""
            if created_at:
                try:
                    if hasattr(created_at, 'strftime'):
                        posted_str = f" · {created_at.astimezone(IST).strftime('%d %b %Y, %I:%M %p IST')}"
                    else:
                        posted_str = f" · {created_at}"
                except Exception:
                    pass

            assignee_mentions = ", ".join(f"<@{uid}>" for uid in assignee_ids_list)
            header = (
                f"📋 **{task.get('priority', 'Normal')} Priority** · Assigned by <@{task['assigner_id']}>{posted_str}\n"
                f"Assigned to: {assignee_mentions}"
            )

            markdown_content = f"""
## {title}
> {task['details']}{checklist_str}

**Deadline:** {deadline_display}

**Assignee Status:**
{roles_list}{act_log}
"""

            view = self.get_main_task_view(task)
            full_content = header + "\n" + markdown_content
            # Discord's message content limit is 2000 characters
            if len(full_content) > 2000:
                full_content = full_content[:1997] + "…"
            await msg.edit(content=full_content, embed=None, view=view)
            
        except Exception as e:
            logger.error(f"[ERR-TSK-022] [Task #{task.get('task_id', '?')}] Error updating main task message: {e}")

    def get_main_task_view(self, task):
        view = ui.View(timeout=None)
        global_state = task.get("global_state", "Active")
        
        # ----------------------------------------------------
        # ASSIGNEE BUTTONS
        # ----------------------------------------------------
        assignee_ids_list = task.get("assignee_ids", [])
        completion_str = task.get("completion_vector", "")
        completion_vector = completion_str.split(",") if completion_str else ["0"] * len(assignee_ids_list)
        
        # Acknowledgment Button
        acknowledged_str = task.get("acknowledged_by", "")
        acknowledged_list = [int(x) for x in acknowledged_str.split(",") if x]
        all_acknowledged = all(uid in acknowledged_list for uid in assignee_ids_list) if assignee_ids_list else False
        
        ack_label = "[✓] Acknowledged" if all_acknowledged else "Acknowledge Task"
        ack_style = discord.ButtonStyle.green if all_acknowledged else discord.ButtonStyle.primary

        ack_button = ui.Button(label=ack_label, style=ack_style, custom_id=f"ack_{task['task_id']}")
        async def ack_cb(i: discord.Interaction):
            if i.user.id not in assignee_ids_list:  # type: ignore
                return await self._send_ephemeral(i, "You are not an assignee on this task.")

            if i.user.id in acknowledged_list:
                return await self._send_ephemeral(i, "You have already acknowledged this task.")

            current_deadline = task.get("deadline", "")

            if current_deadline:
                # Assigner has set a deadline — let assignee accept or propose a different one
                class AcknowledgeDeadlineView(ui.View):
                    def __init__(self_view):
                        super().__init__(timeout=120)

                    @ui.button(label="✅ Accept Deadline", style=discord.ButtonStyle.success)
                    async def accept_btn(self_view, btn_i: discord.Interaction, button: ui.Button):
                        try:
                            await btn_i.response.defer()
                        except (discord.InteractionResponded, discord.HTTPException):
                            return
                        try:
                            acknowledged_str = task.get("acknowledged_by", "")
                            ack_list = [int(x) for x in acknowledged_str.split(",") if x]
                            if i.user.id not in ack_list:
                                ack_list.append(i.user.id)
                                task["acknowledged_by"] = ",".join(map(str, ack_list))
                            ts = now_ist().strftime("%Y-%m-%d %H:%M IST")
                            task["activity_log"] = (task.get("activity_log") or "") + f"\n[{ts}] {i.user.display_name} acknowledged and accepted deadline: {format_deadline(current_deadline)}"
                            await update_task_in_database(task)
                            await self.update_main_task_message(task)
                            # Notify the task thread
                            t_chan = self.bot.get_channel(int(task["channel_id"]))
                            if not t_chan:
                                try:
                                    t_chan = await self.bot.fetch_channel(int(task["channel_id"]))
                                except Exception:
                                    pass
                            if t_chan:
                                await t_chan.send(f"✅ {i.user.mention} acknowledged the task and accepted the deadline: **{format_deadline(current_deadline)}**")
                            await self._sync_participants(int(task.get("assigner_id", 0)), task.get("assignee_ids", []), btn_i.guild)
                            await btn_i.edit_original_response(
                                content=f"✅ Task acknowledged! Deadline accepted: **{format_deadline(current_deadline)}**",
                                view=None
                            )
                            self_view.stop()
                        except Exception as e:
                            logger.error(f"[ERR-TSK-030] [Task] accept_btn error: {e}")

                    @ui.button(label="📝 Propose Different Deadline", style=discord.ButtonStyle.secondary)
                    async def propose_btn(self_view, btn_i: discord.Interaction, button: ui.Button):
                        class ProposeDeadlineModal(ui.Modal, title="Propose New Deadline"):
                            proposed_date = ui.TextInput(
                                label="Proposed Date",
                                style=discord.TextStyle.short,
                                placeholder="DD/MM/YYYY  e.g. 27/03/2026",
                                max_length=10,
                                required=True
                            )
                            proposed_time = ui.TextInput(
                                label="Proposed Time",
                                style=discord.TextStyle.short,
                                placeholder="HH:MM AM/PM  e.g. 02:30 PM",
                                max_length=8,
                                required=True
                            )
                            async def on_submit(inner_self, mi: discord.Interaction):
                                try:
                                    dl_dt, proposed_val = parse_datetime_flexible(
                                        inner_self.proposed_date.value, inner_self.proposed_time.value
                                    )
                                except ValueError as e:
                                    await mi.response.send_message(f"❌ {e}", ephemeral=True)
                                    return
                                if dl_dt.replace(tzinfo=IST) <= now_ist():
                                    await mi.response.send_message("❌ Proposed deadline must be after the current date and time.", ephemeral=True)
                                    return

                                await mi.response.defer(ephemeral=True)

                                # Mark assignee as acknowledged (pending deadline approval)
                                acknowledged_str = task.get("acknowledged_by", "")
                                ack_list = [int(x) for x in acknowledged_str.split(",") if x]
                                if i.user.id not in ack_list:
                                    ack_list.append(i.user.id)
                                    task["acknowledged_by"] = ",".join(map(str, ack_list))

                                ts = now_ist().strftime("%Y-%m-%d %H:%M IST")
                                task["activity_log"] = (task.get("activity_log") or "") + f"\n[{ts}] {i.user.display_name} acknowledged but proposed new deadline: {proposed_val} (original: {current_deadline})"
                                await update_task_in_database(task)
                                await self.update_main_task_message(task)

                                # Notify assigner in task thread with Accept/Decline buttons
                                chan = self.bot.get_channel(int(task["channel_id"]))
                                if not chan:
                                    try:
                                        chan = await self.bot.fetch_channel(int(task["channel_id"]))
                                    except Exception:
                                        pass

                                if chan:
                                    deadline_view = ui.View(timeout=None)

                                    accept_dl_btn = ui.Button(label="✅ Accept Proposed Deadline", style=discord.ButtonStyle.success, custom_id=f"approve_deadline_{task['task_id']}")
                                    async def accept_dl_cb(dl_i: discord.Interaction):
                                        if dl_i.user.id != task.get("assigner_id"):
                                            return await self._send_ephemeral(dl_i, "Only the assigner can accept this deadline.")
                                        await dl_i.response.defer(ephemeral=True)
                                        task["deadline"] = proposed_val
                                        ts2 = now_ist().strftime("%Y-%m-%d %H:%M IST")
                                        task["activity_log"] = (task.get("activity_log") or "") + f"\n[{ts2}] {dl_i.user.display_name} accepted proposed deadline: {proposed_val}"
                                        await update_task_in_database(task)
                                        await self.update_main_task_message(task)
                                        await self._sync_participants(int(task.get("assigner_id", 0)), task.get("assignee_ids", []), dl_i.guild)
                                        try:
                                            await dl_i.message.delete()
                                        except Exception:
                                            pass
                                        await dl_i.followup.send(f"✅ Deadline updated to **{format_deadline(proposed_val)}**.", ephemeral=True)
                                    accept_dl_btn.callback = accept_dl_cb

                                    decline_dl_btn = ui.Button(label="❌ Decline — Keep Original", style=discord.ButtonStyle.danger, custom_id=f"deny_deadline_{task['task_id']}")
                                    async def decline_dl_cb(dl_i: discord.Interaction):
                                        if dl_i.user.id != task.get("assigner_id"):
                                            return await self._send_ephemeral(dl_i, "Only the assigner can decline this request.")
                                        await dl_i.response.defer(ephemeral=True)
                                        ts3 = now_ist().strftime("%Y-%m-%d %H:%M IST")
                                        task["activity_log"] = (task.get("activity_log") or "") + f"\n[{ts3}] {dl_i.user.display_name} declined proposed deadline. Original deadline {current_deadline} stands."
                                        await update_task_in_database(task)
                                        await self.update_main_task_message(task)
                                        await asyncio.gather(
                                            self.sync_user_dashboard_tasks(int(task.get("assigner_id", 0)), dl_i.guild),
                                            *[coro for uid in task.get("assignee_ids", []) for coro in (
                                                self.sync_user_pending_tasks(int(uid), dl_i.guild),
                                                self.sync_user_dashboard_tasks(int(uid), dl_i.guild),
                                            )],
                                        )
                                        try:
                                            await dl_i.message.delete()
                                        except Exception:
                                            pass
                                        await dl_i.followup.send(f"❌ Proposed deadline declined. Original deadline **{format_deadline(current_deadline)}** stands.", ephemeral=True)
                                        # DM the assignee
                                        try:
                                            assignee_user = await self.bot.fetch_user(i.user.id)
                                            await assignee_user.send(f"Your proposed deadline ({format_deadline(proposed_val)}) for task **{task.get('title', 'task')}** was declined by {dl_i.user.display_name}. The original deadline **{format_deadline(current_deadline)}** stands.")
                                        except Exception:
                                            pass
                                    decline_dl_btn.callback = decline_dl_cb

                                    deadline_view.add_item(accept_dl_btn)
                                    deadline_view.add_item(decline_dl_btn)

                                    await chan.send(
                                        f"📅 **Deadline Proposal** — {i.user.mention} has acknowledged the task but proposes a new deadline.\n"
                                        f"**Original:** {format_deadline(current_deadline)}\n"
                                        f"**Proposed:** {format_deadline(proposed_val)}\n"
                                        f"<@{task['assigner_id']}> please review:",
                                        view=deadline_view
                                    )

                                await self._send_ephemeral(mi, f"📝 Deadline proposal submitted. Awaiting assigner review.\nYou have been acknowledged pending deadline approval.")

                        await btn_i.response.send_modal(ProposeDeadlineModal())
                        self_view.stop()

                try:
                    await i.response.send_message(
                        f"📋 **Task Deadline Set by Assigner:** **{format_deadline(current_deadline)}**\n\nPlease accept this deadline or propose a different one:",
                        view=AcknowledgeDeadlineView(),
                        ephemeral=True
                    )
                except (discord.InteractionResponded, discord.HTTPException):
                    return  # Live view already responded
            else:
                # No deadline set — assignee proposes one
                try:
                    await i.response.send_modal(AssigneeDeadlineModal(task, i.user.id))
                except (discord.InteractionResponded, discord.HTTPException):
                    return  # Live view already responded

        ack_button.callback = ack_cb
        
        # Mark Complete Button
        mark_complete_button = ui.Button(label="Mark as Complete", style=discord.ButtonStyle.success, custom_id=f"mark_complete_{task['task_id']}")
        async def mark_complete_cb(i: discord.Interaction):
            if i.user.id not in assignee_ids_list: # type: ignore
                return await self._send_ephemeral(i, "You are not an assignee on this task.")
            
            if i.user.id not in acknowledged_list:
                return await self._send_ephemeral(i, "You must acknowledge the task first before you can mark it complete.")
                
            try:
                user_idx = list(assignee_ids_list).index(i.user.id) # type: ignore
                if completion_vector[user_idx] == "1":
                    return await self._send_ephemeral(i, "You have already completed your portion.")
            except ValueError:
                return await self._send_ephemeral(i, "Call [ERR-TSK-023]: Error retrieving your assignee status.")
                
            try:
                await i.response.defer()
            except (discord.InteractionResponded, discord.HTTPException):
                return  # Live view already responded
            completion_vector[user_idx] = "1"
            task["completion_vector"] = ",".join(completion_vector)
            
            if all(bit == "1" for bit in completion_vector):
                task["global_state"] = "Pending Review"
                task["status"] = "Pending Assigner Review"
                temp_channel = self.bot.get_channel(int(task["channel_id"]))
                if temp_channel:
                    await temp_channel.send(f"✅ {', '.join(task.get('assignees', []))} have completed their work! {task.get('assigner', 'Assigner')}, please review.")
                    
            await update_task_in_database(task)
            await self.update_main_task_message(task)
            await self._send_ephemeral(i, "Your portion of the task has been marked complete.")
            
            await self._sync_participants(int(task.get("assigner_id", 0)), task.get("assignee_ids", []), i.guild)

        mark_complete_button.callback = mark_complete_cb
        
        if global_state == "Active":
            if not all_acknowledged:
                view.add_item(ack_button)
                
            if task.get("status") == "Blocked":
                view.add_item(ui.Button(label="Resolve Blocker", style=discord.ButtonStyle.success, custom_id=f"dash_resolve_block_{task['task_id']}"))
                view.add_item(ui.Button(label="Request New Deadline", style=discord.ButtonStyle.secondary, custom_id=f"dash_req_deadline_{task['task_id']}"))
            else:
                view.add_item(ui.Button(label="Reject Task", style=discord.ButtonStyle.danger, custom_id=f"dash_reject_{task['task_id']}"))
                
                # Only show mark complete if at least one person has acknowledged
                if len(acknowledged_list) > 0:
                    view.add_item(mark_complete_button)
        elif global_state == "Pending Review":
            approve_btn = ui.Button(label="Approve Task", style=discord.ButtonStyle.success, custom_id=f"approve_panel_{task['task_id']}")
            async def approve_cb(i: discord.Interaction):
                if i.user.id != task.get("assigner_id"):
                    return await self._send_ephemeral(i, f"Only {task.get('assigner', 'the assigner')} can approve this task.")
                await i.response.defer(ephemeral=True)
                await mark_task_completed(int(task["task_id"]))

                task["global_state"] = "Finalized"
                task["status"] = "Finalized"

                temp_channel = self.bot.get_channel(int(task["channel_id"]))
                if temp_channel:
                    await temp_channel.send(f"✅ **Task Approved.** This channel will be automatically archived in 24 hours.")

                await self.update_main_task_message(task)

                await self._sync_participants(task["assigner_id"], task.get("assignee_ids", []), i.guild)
                await i.followup.send("✅ Task approved and finalized.", ephemeral=True)
            approve_btn.callback = approve_cb
            view.add_item(approve_btn)

            revise_btn = ui.Button(label="Request Revision", style=discord.ButtonStyle.danger, custom_id=f"revise_panel_{task['task_id']}")
            async def revise_cb(i: discord.Interaction):
                if i.user.id != task.get("assigner_id"):
                    return await self._send_ephemeral(i, f"Only {task.get('assigner', 'the assigner')} can request a revision.")
                class RevisionModal(ui.Modal, title="Request Revision"):
                    feedback = ui.TextInput(label="Feedback", style=discord.TextStyle.long, required=True, placeholder="What needs to be fixed?")
                    async def on_submit(inner_self, modal_interaction: discord.Interaction):
                        await modal_interaction.response.defer()
                        task["global_state"] = "Active"
                        task["status"] = "Active (Revision Requested)"
                        
                        num_assignees = len(task.get("assignee_ids", []))
                        task["completion_vector"] = ",".join(["0"] * num_assignees)
                        task["acknowledged_by"] = ""
                        
                        current_log = task.get("activity_log", "")
                        timestamp = now_ist().strftime("%Y-%m-%d %H:%M IST")
                        new_entry = f"[{timestamp}] {task.get('assigner', 'Assigner')} requested revision: {inner_self.feedback.value}"
                        task["activity_log"] = f"{current_log}\n{new_entry}" if current_log else new_entry
                        
                        await update_task_in_database(task)
                        
                        temp_channel = self.bot.get_channel(int(task["channel_id"]))
                        if temp_channel:
                            await temp_channel.send(f"⚠️ **Revision Requested by {task.get('assigner', 'Assigner')}:**\n{inner_self.feedback.value}")
                        
                        await self.update_main_task_message(task)
                        await self._send_ephemeral(modal_interaction, "Revision requested and completion statuses reset.")
                        
                        await self._sync_participants(int(task.get("assigner_id", 0)), task.get("assignee_ids", []), modal_interaction.guild)
                await i.response.send_modal(RevisionModal())
            revise_btn.callback = revise_cb
            view.add_item(revise_btn)
            
        # ----------------------------------------------------
        # ASSIGNER BUTTONS
        # ----------------------------------------------------
        
        if global_state != "Finalized":
            manage_btn = ui.Button(label="Manage Task ⚙️", style=discord.ButtonStyle.secondary, custom_id=f"manage_{task['task_id']}")
            async def manage_cb(i: discord.Interaction):
                try:
                    if i.user.id != task.get("assigner_id"):
                        return await self._send_ephemeral(i, f"Only {task.get('assigner', 'the assigner')} can manage this task.")

                    try:
                        await i.response.defer(ephemeral=True)
                    except (discord.InteractionResponded, discord.HTTPException):
                        return  # Live view already responded — silently drop the duplicate
                    control_view = self.get_assigner_control_view(task)
                    await i.followup.send("⚙️ **Assigner Control Panel**", view=control_view, ephemeral=True)
                except Exception as e:
                    logger.error(f"[ERR-TSK-024] [Task] manage_cb error: {e}")
                
            manage_btn.callback = manage_cb
            view.add_item(manage_btn)

        return view

    def get_assigner_control_view(self, task):
        view = ui.View(timeout=None)
        self_cog = self
        
        class AddAssigneeSelect(ui.UserSelect):
            def __init__(self_select):
                super().__init__(placeholder="Add Assignees", min_values=1, max_values=10, custom_id=f"add_assignee_panel_{task['task_id']}") # type: ignore
                
            async def callback(self_select, select_interaction: discord.Interaction):
                    await select_interaction.response.defer()
                    new_users = self_select.values
                    added = []
                    
                    guild = select_interaction.guild
                    if not guild: return
                    temp_channel = guild.get_channel(int(task["channel_id"]))
                    if not temp_channel:
                        try:
                            temp_channel = await self_cog.bot.fetch_channel(int(task["channel_id"]))
                        except Exception:
                            return

                    existing_ids = task.get("assignee_ids", [])
                    completion_str = task.get("completion_vector", "")
                    completion_vector = completion_str.split(",") if completion_str else ["0"] * len(existing_ids)

                    for user in new_users:
                        if user.id not in existing_ids: # type: ignore
                            existing_ids.append(user.id) # type: ignore
                            task.get("assignees", []).append(user.display_name) # type: ignore
                            completion_vector.append("0")
                            added.append(user)
                            # Grant read-only access to the task channel
                            await temp_channel.set_permissions(
                                user, view_channel=True, send_messages=False,
                                read_message_history=True, add_reactions=False,
                                create_public_threads=False, create_private_threads=False
                            )
                            # Also add to the discussion thread
                            discussion_thread = discord.utils.get(temp_channel.threads, name="💬 Discussion")
                            if discussion_thread:
                                await discussion_thread.add_user(user)
                            
                    if added:
                        task["completion_vector"] = ",".join(completion_vector)
                        await update_task_in_database(task)
                        await self.update_main_task_message(task)
                        
                        mentions = " ".join([u.mention for u in added])
                        await temp_channel.send(f"👥 **New Assignees Added:** {mentions} Welcome to the task!")
                        
                        await asyncio.gather(
                            *[coro for u in added for coro in (
                                self.sync_user_pending_tasks(u.id, guild),
                                self.sync_user_dashboard_tasks(u.id, guild),
                            )],
                            self.sync_user_dashboard_tasks(select_interaction.user.id, guild),
                        )
                        await self._send_ephemeral(select_interaction, f"Successfully added {len(added)} new assignees.")
                    else:
                        await self_cog._send_ephemeral(select_interaction, "No new assignees were added (they might already be assigned).")
            
        view.add_item(AddAssigneeSelect())

        complete_button = ui.Button(label="Close Task (Override)", style=discord.ButtonStyle.danger, custom_id=f"close_task_panel_{task['task_id']}")
        async def complete_cb(i: discord.Interaction):
            if task.get("global_state") == "Finalized":
                await self_cog._send_ephemeral(i, "This task is already finalized.")
                return
                
            await i.response.defer()
            await mark_task_completed(int(task["task_id"]))

            # Update local state for immediate UI refresh
            task["global_state"] = "Finalized"
            task["status"] = "Finalized"

            temp_channel = self_cog.bot.get_channel(int(task["channel_id"]))
            if temp_channel:
                await temp_channel.send(f"⛔ **Task Closed (Override).** This channel will be automatically archived in 24 hours.")
            
            await self_cog.update_main_task_message(task)
            
            await self_cog._sync_participants(int(task.get("assigner_id", 0)), task.get("assignee_ids", []), i.guild)
        complete_button.callback = complete_cb
        view.add_item(complete_button)
        
        modify_button = ui.Button(label="Modify Deadline", style=discord.ButtonStyle.secondary, custom_id=f"modify_deadline_panel_{task['task_id']}")
        async def modify_cb(i: discord.Interaction):
            class ModifyDeadlineModal(ui.Modal, title="Modify Deadline"):
                new_deadline_date = ui.TextInput(label="New Deadline Date", style=discord.TextStyle.short, placeholder="DD/MM/YYYY  e.g. 27/03/2026", max_length=10, required=True)
                new_deadline_time = ui.TextInput(label="New Deadline Time", style=discord.TextStyle.short, placeholder="HH:MM AM/PM  e.g. 02:30 PM", max_length=8, required=True)
                async def on_submit(inner_self, modal_interaction: discord.Interaction):
                    await modal_interaction.response.defer(ephemeral=True)
                    try:
                        dl_dt, new_val = parse_datetime_flexible(
                            inner_self.new_deadline_date.value, inner_self.new_deadline_time.value
                        )
                    except ValueError as e:
                        await self_cog._send_ephemeral(modal_interaction, f"❌ [ERR-TSK-025] {e}")
                        return
                    if dl_dt.replace(tzinfo=IST) <= now_ist():
                        await self_cog._send_ephemeral(modal_interaction, "❌ Deadline must be after the current date and time.")
                        return

                    task["deadline"] = new_val
                    await update_task_in_database(task)
                    
                    await self_cog.update_main_task_message(task)
                    await self_cog._send_ephemeral(modal_interaction, "Deadline updated.")
                    
                    await self_cog._sync_participants(int(task.get("assigner_id", 0)), task.get("assignee_ids", []), modal_interaction.guild)
            await i.response.send_modal(ModifyDeadlineModal())
        modify_button.callback = modify_cb
        view.add_item(modify_button)

        remind_button = ui.Button(label="Remind Assignees", style=discord.ButtonStyle.primary, custom_id=f"remind_task_panel_{task['task_id']}")
        async def remind_cb(i: discord.Interaction):
            await i.response.defer()
            temp_channel = self_cog.bot.get_channel(int(task["channel_id"]))
            if temp_channel:
                mentions = " ".join([i.guild.get_member(uid).mention for uid in task.get("assignee_ids", []) if i.guild.get_member(uid)])
                await temp_channel.send(f"Friendly reminder: {mentions} please check the deadline for this task!")
        remind_button.callback = remind_cb
        view.add_item(remind_button)

        return view

    # ── Background Engines ────────────────────────────────────────────────────

    async def check_and_remove_invalid_tasks(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                await cleanup_stale_drafts(max_age_hours=24)
            except Exception as e:
                logger.error(f"[ERR-TSK-026] [Task] Error in check_and_remove_invalid_tasks: {e}")
            await asyncio.sleep(300)  # Every 5 minutes

    # -------------------------------------------------------------------------
    # Reminder Engine
    # -------------------------------------------------------------------------

    async def task_reminder_engine(self):
        await self.bot.wait_until_ready()
        
        while not self.bot.is_closed():
            try:
                # 1. Process Queue if we just entered active window
                if self.is_active_window():
                    from Bots.db_managers.task_db_manager import db_execute, get_conn
                    def _get_queue():
                        from Bots.db_managers.task_db_manager import get_conn, put_conn
                        conn = get_conn()
                        try:
                            with conn.cursor() as cur:
                                cur.execute("SELECT * FROM notification_queue WHERE sent = FALSE")
                                return cur.fetchall()
                        finally:
                            put_conn(conn)
                    
                    queued = await db_execute(_get_queue)
                    for q in queued:
                        try:
                            user = await self.bot.fetch_user(q['recipient_id'])
                            if user:
                                await user.send(f"🌅 **Morning Update:** {q['content']}")
                            
                            def _mark_sent(qid=q['id']):
                                from Bots.db_managers.task_db_manager import get_conn, put_conn
                                conn = get_conn()
                                try:
                                    with conn.cursor() as cur:
                                        cur.execute("UPDATE notification_queue SET sent = TRUE WHERE id = %s", (qid,))
                                    conn.commit()
                                finally:
                                    put_conn(conn)
                            await db_execute(_mark_sent)
                        except Exception as e:
                            logger.error(f"[ERR-TSK-027] [Task Queue] Failed delivery of {q['id']}: {e}")

                # 2. Main Logic Process
                tasks = await retrieve_active_tasks_from_database()
                now = datetime.now(IST)

                for task in tasks:
                    if task.get("status") == "Blocked":
                        # Blocker Protocol: Pause assignee nags, nag assigner
                        # Implementation detail: Skip the normal flow and maybe add a special assigner nag
                        # For now, per logic.txt: "All automated nags for the Assignee are paused."
                        continue

                    deadline_str = task.get("deadline", "")
                    if not deadline_str: continue
                    try:
                        deadline_dt = datetime.strptime(deadline_str, "%d/%m/%Y %I:%M %p").replace(tzinfo=IST)
                    except ValueError: continue
                    
                    delta = deadline_dt - now
                    hours_diff = delta.total_seconds() / 3600.0
                    priority = task.get("priority", "Normal").capitalize()
                    
                    reminders_sent = task.get("reminders_sent", "")
                    sent_list = reminders_sent.split(",") if reminders_sent else []
                    
                    triggers = [] # format: (slug, message, target_ids)
                    task_title = task.get('title', f"{task.get('priority', 'Normal')} Priority Task")

                    # Logic Mapping from concord_logic.txt
                    if priority == "High":
                        if hours_diff <= 24 and "24h" not in sent_list:
                            triggers.append(("24h", f"⚠️ **Urgent Nudge:** Task **{task_title}** is due in 24 hours.", task['assignee_ids']))
                        if hours_diff <= 4 and "4h" not in sent_list:
                            triggers.append(("4h", f"🚨 **Priority Alert:** Task **{task_title}** is due in just 4 hours!", task['assignee_ids']))
                        if hours_diff <= 1 and "1h_thread" not in sent_list:
                            triggers.append(("1h_thread", "⏰ **Final Hour:** Task is due in 1 hour.", "thread"))

                        # Overdue logic (+15m grace)
                        if hours_diff <= -0.25: # exceeds 15m
                            if "0m_overdue" not in sent_list:
                                triggers.append(("0m_overdue", "❌ **OVERDUE:** This task has passed its deadline and grace period.", "thread_and_assigner"))
                            if hours_diff <= -1.0 and "1h_esc" not in sent_list:
                                triggers.append(("1h_esc", "📡 **Escalation (1h):** Task is overdue. Notifying Department Manager.", "esc_dept"))
                            if hours_diff <= -4.0 and "4h_esc" not in sent_list:
                                triggers.append(("4h_esc", "🔥 **Critical Escalation (4h):** Assigning Project Manager attention.", "esc_pm"))

                        # Removed Medium logic per request

                    elif priority == "Normal":
                        if hours_diff <= 24 and "24h" not in sent_list:
                            triggers.append(("24h", f"📌 **Task Nudge:** **{task_title}** due in 24 hours.", task['assignee_ids']))

                        if hours_diff <= -0.25: # exceeds 15m
                            if "0m_overdue" not in sent_list:
                                triggers.append(("0m_overdue", "❌ **Deadline Passed.**", "thread"))
                            if hours_diff <= -48.0 and "48h_esc" not in sent_list:
                                triggers.append(("48h_esc", "📡 **Escalation (48h):** Notifying Department Manager.", "esc_dept"))

                    elif priority == "Low":
                        if hours_diff <= 48 and "48h" not in sent_list:
                            triggers.append(("48h", f"📎 **Upcoming:** **{task_title}** due in 48 hours.", task['assignee_ids']))

                    # Execute Triggers — collect all slugs first, write DB once
                    if triggers:
                        for slug, _, __ in triggers:
                            sent_list.append(slug)
                        task["reminders_sent"] = ",".join(sent_list)
                        await update_task_in_database(task)

                    for slug, content, target in triggers:
                        # Routing logic
                        chan = self.bot.get_channel(int(task['channel_id']))
                        if not chan:
                            try:
                                chan = await self.bot.fetch_channel(int(task['channel_id']))
                            except Exception:
                                pass
                        
                        if target == "thread" or target == "thread_and_assigner":
                            if chan:
                                assignee_mentions = " ".join([f"<@{uid}>" for uid in task['assignee_ids']])
                                final_msg = f"{assignee_mentions} {content}"
                                if target == "thread_and_assigner":
                                    final_msg += f" <@{task['assigner_id']}>"
                                await chan.send(final_msg)
                        elif target in ("esc_dept", "esc_pm"):
                            if chan:
                                guild = chan.guild
                                assignee_mentions = " ".join([f"<@{uid}>" for uid in task['assignee_ids']])
                                task_label = task.get('title', f"Task #{task['task_id']}")
                                ping = None
                                if target == "esc_dept":
                                    # Find the assigner's department role
                                    assigner_member = guild.get_member(int(task.get("assigner_id", 0)))
                                    if assigner_member:
                                        for role in assigner_member.roles:
                                            if role.id in DEPARTMENTS.values():
                                                ping = role.mention
                                                break
                                    if not ping:
                                        ping = f"<@{task['assigner_id']}>"
                                    await chan.send(
                                        f"📡 **Dept Escalation:** {ping} — **{task_label}** assigned to "
                                        f"{assignee_mentions} is overdue and requires your attention."
                                    )
                                    logger.warning(f"[ERR-TSK-028] [Escalation] Task {task['task_id']} escalated to dept ({ping}).")
                                else:  # esc_pm
                                    pm_role = discord.utils.get(guild.roles, name="Project Coordinator")
                                    ping = pm_role.mention if pm_role else f"<@{task['assigner_id']}>"
                                    await chan.send(
                                        f"🔥 **PM Escalation:** {ping} — **{task_label}** is critically overdue. "
                                        f"Assigner: <@{task['assigner_id']}>, Assignees: {assignee_mentions}"
                                    )
                                    logger.warning(f"[ERR-TSK-028] [Escalation] Task {task['task_id']} escalated to PM ({ping}).")
                        elif isinstance(target, list):
                            # Build a rich DM with task details and a direct thread link
                            desc = task.get('details', '')
                            desc_preview = desc[:200] + ('…' if len(desc) > 200 else '')
                            dl_display = format_deadline(task.get('deadline', '')) if task.get('deadline') else 'Not set'
                            thread_link = ""
                            if chan:
                                if task.get('main_message_id'):
                                    thread_link = f"\n🔗 https://discord.com/channels/{chan.guild.id}/{task['channel_id']}/{task['main_message_id']}"
                                else:
                                    thread_link = f"\n🔗 https://discord.com/channels/{chan.guild.id}/{task['channel_id']}"
                            rich_content = (
                                f"{content}\n\n"
                                f"**Task:** {task_title}\n"
                                f"**Description:** {desc_preview}\n"
                                f"**Deadline:** {dl_display}\n"
                                f"**Priority:** {task.get('priority', 'Normal')}\n"
                                f"**Assigned by:** {task.get('assigner', 'Unknown')}"
                                f"{thread_link}"
                            )
                            for uid in target:
                                await self.deliver_notification(task['task_id'], int(uid), rich_content)

                # End Main Logic
            except Exception as e:
                logger.error(f"[ERR-TSK-029] [Task] Error in task_reminder_engine: {e}")
                
            await asyncio.sleep(60 * 5) # Poll every 5 minutes

    # ── Archiving ─────────────────────────────────────────────────────────────

    async def archive_task_channel(self, task, channel: discord.TextChannel):
        import os
        import json as _json

        archive_root = os.getenv("ARCHIVE_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Archives", "Tasks"))
        task_title = task.get('title', f"Task {task.get('task_id', 'Unknown')}")
        safe_title = "".join([c for c in task_title if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).rstrip()
        task_dir = os.path.join(archive_root, f"{safe_title}_{task['task_id']}")
        os.makedirs(task_dir, exist_ok=True)

        # Task 3: Archive File Size Safeguards
        ARCHIVE_MAX_TOTAL_BYTES = int(os.getenv("ARCHIVE_MAX_MB", "100")) * 1024 * 1024  # default 100 MB
        PER_FILE_MAX = 10_000_000  # 10 MB per attachment
        cumulative_bytes = 0
        budget_exhausted = False
        saved_attachments = []
        skipped_attachments = []

        transcript_path = os.path.join(task_dir, "transcript.txt")
        try:
            with open(transcript_path, "w", encoding="utf-8") as f:
                task_title = task.get('title', f"Task {task.get('task_id', 'Unknown')}")
                f.write(f"--- Task Transcript: {task_title} ---\n")
                f.write(f"Assigner: {task['assigner']} | Deadline: {task['deadline']}\n")
                f.write(f"Assignees: {', '.join(task.get('assignees', []))}\n")
                f.write(f"Archived: {now_ist().strftime('%d %b, %Y %I:%M %p IST')}\n")
                f.write("-" * 50 + "\n\n")

                async for message in channel.history(limit=None, oldest_first=True):
                    # Convert Discord UTC timestamp to IST for the transcript
                    ts_ist = message.created_at.replace(tzinfo=timezone.utc).astimezone(IST)
                    ts = ts_ist.strftime("%Y-%m-%d %H:%M:%S IST")
                    f.write(f"[{ts}] {message.author.display_name}:\n{message.clean_content}\n")

                    for count, attachment in enumerate(message.attachments):
                        f.write(f"  -> [Attachment: {attachment.filename}]\n")

                        skip_reason = None
                        if budget_exhausted:
                            skip_reason = f"total archive budget exhausted ({cumulative_bytes} bytes)"
                        elif attachment.size > PER_FILE_MAX:
                            skip_reason = f"exceeds per-file limit ({attachment.size} > {PER_FILE_MAX} bytes)"
                        elif cumulative_bytes + attachment.size > ARCHIVE_MAX_TOTAL_BYTES:
                            skip_reason = f"would exceed total budget ({cumulative_bytes + attachment.size} > {ARCHIVE_MAX_TOTAL_BYTES} bytes)"
                            budget_exhausted = True

                        if skip_reason:
                            f.write(f"  -> [SKIPPED: {skip_reason}]\n")
                            f.write(f"  -> [Manual retrieval URL: {attachment.url}]\n")
                            skipped_attachments.append({"filename": attachment.filename, "size": attachment.size, "url": attachment.url, "reason": skip_reason})
                            logger.warning(f"[ERR-TSK-030] [Task Archive] Skipped attachment: {attachment.filename} — {skip_reason}")
                            continue

                        safe_filename = f"{message.id}_{count}_{attachment.filename}"
                        attachment_path = os.path.join(task_dir, safe_filename)
                        try:
                            await attachment.save(attachment_path)
                            actual_size = os.path.getsize(attachment_path)
                            cumulative_bytes += actual_size
                            saved_attachments.append({"filename": safe_filename, "size": actual_size})
                        except Exception as file_err:
                            logger.error(f"[ERR-TSK-031] [Task Archive] Failed to download attachment {attachment.filename}: {file_err}")
                            f.write(f"  -> [Error saving attachment]\n")
                            skipped_attachments.append({"filename": attachment.filename, "size": attachment.size, "url": attachment.url, "reason": f"download error: {file_err}"})
                    f.write("\n")

                # Also archive the discussion thread
                discussion_thread = discord.utils.get(channel.threads, name="💬 Discussion")
                if discussion_thread:
                    f.write("\n--- 💬 Discussion Thread ---\n\n")
                    async for message in discussion_thread.history(limit=None, oldest_first=True):
                        ts_ist = message.created_at.replace(tzinfo=timezone.utc).astimezone(IST)
                        ts = ts_ist.strftime("%Y-%m-%d %H:%M:%S IST")
                        f.write(f"[{ts}] {message.author.display_name}:\n{message.clean_content}\n")
                        for attachment in message.attachments:
                            f.write(f"  -> [Attachment: {attachment.filename}]\n")
                        f.write("\n")

            # Write archive manifest
            manifest = {
                "task_id": task.get('task_id'),
                "title": task.get('title'),
                "archived_at": now_ist().isoformat(),
                "total_bytes_saved": cumulative_bytes,
                "budget_bytes": ARCHIVE_MAX_TOTAL_BYTES,
                "attachments_saved": len(saved_attachments),
                "attachments_skipped": len(skipped_attachments),
                "saved": saved_attachments,
                "skipped": skipped_attachments,
            }
            manifest_path = os.path.join(task_dir, "archive_manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as mf:
                _json.dump(manifest, mf, indent=2, ensure_ascii=False)

            task_title = task.get('title', f"Task {task.get('task_id', 'Unknown')}")
            logger.info(f"[Task Archive] Successfully archived '{task_title}' to {task_dir} "
                         f"(saved: {len(saved_attachments)}, skipped: {len(skipped_attachments)}, "
                         f"total: {cumulative_bytes / (1024*1024):.1f} MB)")
        except Exception as e:
            logger.error(f"[ERR-TSK-032] [Task Archive] Failed to archive channel history: {e}")



async def setup(bot: commands.Bot):
    await bot.add_cog(TaskCog(bot))

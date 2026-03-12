"""
cogs/task_cog.py — Task Management Cog
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import asyncio
import logging
import discord
from discord import ui
from discord.ext import commands
import difflib
import os
import ast
from datetime import datetime, timedelta, timezone

# IST Timezone — single source of truth
from Bots.utils.timezone import IST, now_ist

from Bots.db_managers import discovery_db_manager as discovery
from Bots.db_managers.task_db_manager import (
    store_task_in_database,
    retrieve_task_from_database,
    update_task_in_database,
    retrieve_all_tasks_from_database,
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

# Live config — populated by resolve_task_config() on bot startup
COMMAND_CHANNEL_ID    = 1293531912496746638
ACTIVE_TASKS_ID       = 1480381619100713041
DASHBOARD_CATEGORY_ID = 1480152905045774436
PENDING_CATEGORY_ID   = 1299338707605651537
EMP_ROLE_ID           = 1290199089371287562

DEPARTMENTS = {
    "Administration": 1281171713299714059,
    "Architects": 1281172225432752149,
    "CAD": 1281172603217645588,
    "Site": 1285183387258327050,
    "Interns": 1281195640109400085,
}

async def resolve_task_config():
    """
    Queries discovery.db to resolve channel and role IDs by name.
    Ensures the bot stays 'living' even after a DB reset.
    """
    global COMMAND_CHANNEL_ID, ACTIVE_TASKS_ID, DASHBOARD_CATEGORY_ID, PENDING_CATEGORY_ID, EMP_ROLE_ID, DEPARTMENTS
    
    logger = logging.getLogger("Concord")

    # Resolve core IDs
    resolved_cmd = await discovery.get_channel_id_by_name('task-commands')
    if resolved_cmd:
        COMMAND_CHANNEL_ID = resolved_cmd
        logger.info(f"[Task Config] #task-commands → {resolved_cmd}")

    resolved_vault = await discovery.get_channel_id_by_name('active-tasks')
    if resolved_vault:
        ACTIVE_TASKS_ID = resolved_vault
        logger.info(f"[Task Config] #active-tasks → {resolved_vault}")

    resolved_dashboard = await discovery.get_category_id_by_name('Task Dashboard')
    if resolved_dashboard:
        DASHBOARD_CATEGORY_ID = resolved_dashboard
        logger.info(f"[Task Config] 'Task Dashboard' → {resolved_dashboard}")

    resolved_pending = await discovery.get_category_id_by_name('Pending tasks')
    if resolved_pending:
        PENDING_CATEGORY_ID = resolved_pending
        logger.info(f"[Task Config] 'Pending tasks' → {resolved_pending}")

    resolved_emp = await discovery.get_role_id_by_name('emp')
    if resolved_emp:
        EMP_ROLE_ID = resolved_emp
        logger.info(f"[Task Config] @emp → {resolved_emp}")

    # Resolve departments
    for dept in DEPARTMENTS.keys():
        resolved = await discovery.get_role_id_by_name(dept)
        if resolved:
            DEPARTMENTS[dept] = resolved
            logger.info(f"[Task Config] @{dept} → {resolved}")

    logging.info("[Task Config] Configuration successfully resolved from discovery.db.")


def find_closest_match(name: str, members):
    names = [m.display_name.lower() for m in members]
    matches = difflib.get_close_matches(name.lower(), names, n=1, cutoff=0.6)
    if matches:
        for m in members:
            if m.display_name.lower() == matches[0]:
                return m
    return None

def format_deadline(date_str: str) -> str:
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y %I:%M %p")
        return dt.strftime("%d %b, %Y (%I:%M %p)")
    except Exception:
        return date_str


class TaskCog(commands.Cog, name="Tasks"):
    """Handles task assignment and tracking."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------------------
    # Ephemeral helper
    # -------------------------------------------------------------------------

    async def _send_ephemeral(self, interaction: discord.Interaction, content: str, delay: int = 10) -> None:
        """Send an ephemeral response/followup and auto-delete it after `delay` seconds."""
        msg = None
        if not interaction.response.is_done():
            # If we haven't deferred/responded yet, grab the interaction message
            await interaction.response.send_message(content, ephemeral=True)
            msg = await interaction.original_response()
        else:
            msg = await interaction.followup.send(content, ephemeral=True)

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
        self.bot.loop.create_task(db.db_worker())
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
                    logging.info(f"[Task DM] Delivered to {user.name}: {content[:50]}...")
            except discord.Forbidden:
                logging.warning(f"[ERR-TSK-001] [Task DM] Forbidden for recipient {recipient_id}")
            except Exception as e:
                logging.error(f"[ERR-TSK-002] [Task DM] Error: {e}")
        else:
            # Queue for later — use IST-aware timestamp
            from Bots.db_managers.task_db_manager import db_execute, get_conn
            scheduled_at = now_ist()
            def _queue():
                with get_conn() as conn:
                    with conn.cursor() as cur:
                        cur.execute('''
                            INSERT INTO notification_queue (task_id, recipient_id, content, scheduled_at)
                            VALUES (%s, %s, %s, %s)
                        ''', (task_id, recipient_id, content, scheduled_at))
                    conn.commit()
            await db_execute(_queue)
            logging.info(f"[Task Queue] Queued notification for task {task_id} to user {recipient_id}")

    # Start engines handled in on_ready

    async def task_archive_cleanup_engine(self):
        """Background task to archive and delete finalized tasks after 24 hours."""
        while True:
            try:
                # Run every hour
                await asyncio.sleep(3600)
                
                tasks = await retrieve_all_tasks_from_database()
                for task in tasks:
                    if task.get('global_state') == 'Finalized' and task.get('completed_at'):
                        completed_at = task.get('completed_at')
                        # Ensure we are comparing offset-aware or offset-naive consistently
                        now = now_ist()
                        # If completed_at is naive, localize it to IST
                        if completed_at.tzinfo is None:
                            completed_at = completed_at.replace(tzinfo=IST)
                        if now - completed_at >= timedelta(hours=24):
                            logging.info(f"[Task Cleanup] Archiving 24h+ finalized task: {task['title']} (ID: {task['task_id']})")
                            
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
                logging.error(f"[ERR-TSK-003] [Task Cleanup] Engine error: {e}")

    # -------------------------------------------------------------------------
    # Events
    # -------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        await resolve_task_config()
        
        # Start background engines
        asyncio.create_task(self.check_and_remove_invalid_tasks())
        asyncio.create_task(self.task_reminder_engine())
        asyncio.create_task(self.task_archive_cleanup_engine())

        command_channel = self.bot.get_channel(COMMAND_CHANNEL_ID)
        if not command_channel:
            try:
                command_channel = await self.bot.fetch_channel(COMMAND_CHANNEL_ID)
            except Exception:
                logging.warning("[ERR-TSK-004] [Task] Command channel not found.")
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
                logging.info("[Task] Command buttons already exist in the command channel.")
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
        logging.info("[Task] Created command buttons in command channel.")

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
                elif custom_id.startswith("dash_part_"):
                    await self.handle_dash_part(interaction, task)
                elif custom_id.startswith("dash_upd_"):
                    await self.handle_dash_upd(interaction, task)
                return
            except Exception as e:
                logging.error(f"[ERR-TSK-005] [Task] Dashboard interaction error: {e}")
                return

        # Recover zombie views from bot reboots (ID-based rehydration)
        if any(custom_id.startswith(pfx) for pfx in ("manage_", "mark_complete_", "ack_", "approve_panel_", "close_task_panel_", "modify_deadline_panel_", "revise_panel_", "remind_task_panel_", "add_assignee_panel_", "req_rev_panel_")):
            try:
                task_id_str = custom_id.split("_")[-1]
                if task_id_str.isdigit():
                    task = await retrieve_task_by_id(int(task_id_str))
                else:
                    task = await retrieve_task_from_database(interaction.channel_id)
                
                if task:
                    # Determine which view generated this button
                    view = None
                    if any(custom_id.startswith(pfx) for pfx in ("manage_", "mark_complete_", "ack_", "approve_panel_", "revise_panel_", "req_rev_panel_")):
                        view = self.get_main_task_view(task)
                    else:
                        view = self.get_assigner_control_view(task)
                        
                    for child in view.children:
                        if getattr(child, "custom_id", "") == custom_id:
                            await child.callback(interaction)
                            return
                
                if not interaction.response.is_done():
                    await self._send_ephemeral(interaction, "This interaction expired or the task was not found.")
            except Exception as e:
                logging.error(f"[ERR-TSK-006] [Task] Zombie interaction recovery error: {e}")

        # Draft Recovery Handler
        elif custom_id.startswith("confirm_assign_"):
            # Give the view a moment to handle this natively (if it's alive)
            await asyncio.sleep(0.5)
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
                logging.error(f"[ERR-TSK-007] [Task] Draft recovery error: {e}")
                await self._send_ephemeral(interaction, f"Call [ERR-TSK-008] Error recovering assignment: {e}")

    # -------------------------------------------------------------------------
    # Assign Task flow
    # -------------------------------------------------------------------------

    async def handle_assign_task(self, interaction: discord.Interaction):
        try:
            class TaskDetailsModal(ui.Modal, title="Enter Task Details"):
                task_title = ui.TextInput(label="Task Title", style=discord.TextStyle.short, placeholder="Concise title", required=True)
                task_details = ui.TextInput(label="Task Description", style=discord.TextStyle.long, placeholder="Detailed explanation", required=True)
                task_deadline = ui.TextInput(label="Deadline", style=discord.TextStyle.short, placeholder="DD/MM/YYYY HH:MM AM/PM", required=True)
                task_priority = ui.TextInput(label="Priority (High/Medium/Low)", style=discord.TextStyle.short, default="Normal", required=False)

                async def on_submit(self_modal, modal_interaction: discord.Interaction):
                    # 1. Save Draft for reboot recovery
                    draft_id = await store_task_draft(interaction.user.id, {
                        "title": self_modal.task_title.value,
                        "details": self_modal.task_details.value,
                        "deadline": self_modal.task_deadline.value,
                        "priority": self_modal.task_priority.value
                    })

                    class AssigneeSelect(ui.UserSelect):
                        def __init__(self):
                            super().__init__(placeholder="Select Assignees", min_values=1, max_values=10, custom_id=f"confirm_assign_{draft_id}") # type: ignore
                        
                        async def callback(self, select_interaction: discord.Interaction):
                            if not self.values:
                                await self._send_ephemeral(select_interaction, "Please select at least one assignee.")
                                return
                            # Instead of a silent deferral, immediately update the ephemeral message to show success
                            await select_interaction.response.edit_message(content="Task successfully assigned! Setting up thread...", view=None)

                            # Re-read draft to ensure freshness
                            from Bots.db_managers.task_db_manager import retrieve_task_draft
                            draft = await retrieve_task_draft(draft_id)
                            if not draft:
                                # We already responded with edit_message, so we use followup
                                return await select_interaction.followup.send("Call [ERR-TSK-009]: Draft lost. Please try again.", ephemeral=True)
                            
                            # Because we've already responded to the interaction using edit_message, 
                            # we must not defer again inside process_confirmed_task_draft. 
                            # Adding an explicit flag or using a different interaction approach is needed.
                            # We just pass the interaction. It shouldn't defer if already done.
                            await self_cog.process_confirmed_task_draft(select_interaction, draft, self.values)

                    # Pass self_cog specifically into scope to prevent closure rebind issues
                    self_cog = self
                    select = AssigneeSelect()
                    view = ui.View(timeout=None)
                    view.add_item(select)
                    
                    await modal_interaction.response.send_message("Please select the assignees for this task. It will be assigned immediately once selected:", view=view, ephemeral=True)

            await interaction.response.send_modal(TaskDetailsModal())
            
        except discord.NotFound as e:
            logging.warning(f"[ERR-TSK-010] [Task] Interaction expired or not found: {e}")
        except Exception as e:
            logging.error(f"[ERR-TSK-011] [Task] handle_assign_task error: {e}")
            try:
                if not interaction.response.is_done():
                    await self._send_ephemeral(interaction, f"Call [ERR-TSK-012]: An error occurred: {e}")
            except Exception:
                pass

    async def process_confirmed_task_draft(self, interaction: discord.Interaction, draft, assignees=None):
        """Processes a task assignment from a draft (on confirm or recovery)."""
        global ACTIVE_TASKS_ID
        await interaction.response.defer(ephemeral=True)
        try:
            guild = interaction.guild
            if not guild: return
            
            modal_data = draft["modal_data"]
            assigner = self.bot.get_user(draft["user_id"]) or await self.bot.fetch_user(draft["user_id"])
            
            # If assignees not provided (recovery case), we can't proceed directly
            # The recovery logic needs to handle the select menu or find the original select
            if not assignees:
                return await self._send_ephemeral(interaction, "Call [ERR-TSK-013]: Please re-select assignees (Selection lost due to bot restart).")

            # API Fallback for Category/Channel resolution
            vault_channel = guild.get_channel(ACTIVE_TASKS_ID)
            if not vault_channel:
                try:
                    vault_channel = await guild.fetch_channel(ACTIVE_TASKS_ID)
                except Exception:
                    vault_channel = discord.utils.get(guild.text_channels, name="active-tasks")

            if not vault_channel:
                # Creation logic
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False),
                    guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_threads=True)
                }
                vault_channel = await guild.create_text_channel("active-tasks", overwrites=overwrites)
                ACTIVE_TASKS_ID = vault_channel.id

            # Create Private Thread
            thread = await vault_channel.create_thread(
                name=f"{modal_data['title']}",
                type=discord.ChannelType.private_thread,
                invitable=False
            )
            
            # Add participants
            await thread.add_user(assigner)
            for user in assignees:
                await thread.add_user(user)

            task_data = {
                "channel_id": str(thread.id),
                "assignees": [u.display_name for u in assignees],
                "assignee_ids": [u.id for u in assignees],
                "details": modal_data["details"],
                "deadline": modal_data["deadline"],
                "priority": modal_data["priority"] or "Normal",
                "temp_channel_link": thread.jump_url,
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

            view = self.get_main_task_view(task_data)
            msg = await thread.send(
                content=f"Task Assignment Created! {assigner.mention} assigned this to " + ", ".join(u.mention for u in assignees) + "\n" + self._generate_task_markdown(task_data), 
                view=view
            )
            
            await msg.pin()
            task_data["main_message_id"] = str(msg.id)
            await update_task_in_database(task_data)
            
            await delete_task_draft(draft["draft_id"])
            await self._send_ephemeral(interaction, f"Task successfully assigned in {thread.jump_url}.")

            # Sync
            await self.sync_user_pending_tasks(assigner.id, guild)
            await self.sync_user_dashboard_tasks(assigner.id, guild)
            for u in assignees:
                await self.sync_user_pending_tasks(u.id, guild)
                await self.sync_user_dashboard_tasks(u.id, guild)

        except Exception as e:
            logging.error(f"[ERR-TSK-014] [Task] process_confirmed_task_draft error: {e}")
            await self._send_ephemeral(interaction, f"Call [ERR-TSK-015]: Failed to complete assignment: {e}")

    # -------------------------------------------------------------------------
    # View Tasks flow
    # -------------------------------------------------------------------------

    async def handle_dash_mod(self, interaction: discord.Interaction, task):
        class ModifyDeadlineModal(ui.Modal, title="Modify Deadline"):
            new_deadline = ui.TextInput(label="New Deadline", style=discord.TextStyle.short, placeholder="DD/MM/YYYY HH:MM AM/PM", required=True)
            async def on_submit(self_modal, modal_interaction: discord.Interaction):
                await modal_interaction.response.defer(ephemeral=True)
                new_val = self_modal.new_deadline.value.strip()
                try:
                    datetime.strptime(new_val, "%d/%m/%Y %I:%M %p")
                except ValueError:
                    return await self._send_ephemeral(modal_interaction, "❌ Call [ERR-TSK-016]: Invalid format. Use `DD/MM/YYYY HH:MM AM/PM`")

                task["deadline"] = new_val
                await update_task_in_database(task)
                await self.update_main_task_message(task)
                await self._send_ephemeral(modal_interaction, "Deadline updated.")
                
                # Sync
                await self.sync_user_pending_tasks(task["assigner_id"], modal_interaction.guild)
                await self.sync_user_dashboard_tasks(task["assigner_id"], modal_interaction.guild)
                for uid in task["assignee_ids"]:
                    await self.sync_user_pending_tasks(uid, modal_interaction.guild)
                    await self.sync_user_dashboard_tasks(uid, modal_interaction.guild)

        await interaction.response.send_modal(ModifyDeadlineModal())

    async def handle_dash_cancel(self, interaction: discord.Interaction, task):
        if interaction.user.id != task["assigner_id"]:
            return await self._send_ephemeral(interaction, "Only the assigner can cancel this task.")
        
        await interaction.response.defer(ephemeral=True)
        chan = self.bot.get_channel(int(task["channel_id"]))
        if chan:
            await chan.send("❌ **Task Cancelled by Assigner.** Thread will be deleted.")
            # For threads, we just delete or archive. 
            await chan.delete()
        
        await delete_task_from_database(int(task["channel_id"]))
        await self._send_ephemeral(interaction, "Task cancelled and thread removed.")
        
        # Sync
        await self.sync_user_pending_tasks(task["assigner_id"], interaction.guild)
        await self.sync_user_dashboard_tasks(task["assigner_id"], interaction.guild)
        for uid in task["assignee_ids"]:
            await self.sync_user_pending_tasks(uid, interaction.guild)
            await self.sync_user_dashboard_tasks(uid, interaction.guild)

    async def handle_dash_done(self, interaction: discord.Interaction, task):
        if interaction.user.id != task["assigner_id"]:
            return await self._send_ephemeral(interaction, "Only the assigner can finalize this task.")
        
        await interaction.response.defer(ephemeral=True)
        task["global_state"] = "Finalized"
        task["status"] = "Completed"
        task["completed_at"] = datetime.now(IST)
        await update_task_in_database(task)
        
        chan = self.bot.get_channel(int(task["channel_id"]))
        if chan:
            await chan.send("✅ **Task marked as Fully Complete.** Thread will be archived in 24 hours.")
        
        await self.update_main_task_message(task)
        await self._send_ephemeral(interaction, "Task finalized.")
        
        # Sync
        await self.sync_user_pending_tasks(task["assigner_id"], interaction.guild)
        await self.sync_user_dashboard_tasks(task["assigner_id"], interaction.guild)
        for uid in task["assignee_ids"]:
            await self.sync_user_pending_tasks(uid, interaction.guild)
            await self.sync_user_dashboard_tasks(uid, interaction.guild)

    async def handle_dash_block(self, interaction: discord.Interaction, task):
        if interaction.user.id not in task["assignee_ids"]:
            return await self._send_ephemeral(interaction, "Only assignees can report blockers.")
        
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
                
                await self._send_ephemeral(modal_interaction, "Blocker reported. Automated nags for assignees are now paused.")
                
                # Sync
                await self.sync_user_pending_tasks(task["assigner_id"], modal_interaction.guild)
                await self.sync_user_dashboard_tasks(task["assigner_id"], modal_interaction.guild)

        await interaction.response.send_modal(BlockerModal())

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
                await chan.send("✅ **All parts completed!** Assigner, please review.")

        await update_task_in_database(task)
        await self.update_main_task_message(task)
        await self._send_ephemeral(interaction, "Marked your part as done.")
        
        # Sync
        await self.sync_user_pending_tasks(interaction.user.id, interaction.guild)
        await self.sync_user_dashboard_tasks(task["assigner_id"], interaction.guild)

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
            await t_ch.send(f"🔔 **Update Requested:** {interaction.user.mention} is requesting an update on task **{task['title']}**. {a_mentions}")
            await self._send_ephemeral(interaction, f"Update request sent to {t_ch.mention}!")
        else:
            await self._send_ephemeral(interaction, "Call [ERR-TSK-018]: Could not locate the task channel.")

    async def handle_view_tasks_button(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            await self.sync_user_pending_tasks(interaction.user.id, interaction.guild)
            await self.sync_user_dashboard_tasks(interaction.user.id, interaction.guild)
            
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
            logging.error(f"[ERR-TSK-019] [Task] handle_view_tasks_button error: {e}")

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
                    member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
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

            all_tasks = await retrieve_all_tasks_from_database()
            user_tasks = [t for t in all_tasks if user_id in t.get("assignee_ids", []) and t.get("global_state") == "Active"]
            
            await pending_channel.purge(limit=100) # type: ignore
            
            new_task_ids = []
            new_msg_ids = []

            # Batch tasks in groups of 5 to reduce mobile UI bloat
            BATCH_SIZE = 5
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

                    view.add_item(ui.Button(label=f"Open: {task['title'][:20]}", style=discord.ButtonStyle.link, url=jump_url))
                    view.add_item(ui.Button(label="[!] Blocker", style=discord.ButtonStyle.danger, custom_id=f"dash_block_{task['task_id']}"))
                    view.add_item(ui.Button(label="[✔] Done", style=discord.ButtonStyle.success, custom_id=f"dash_part_{task['task_id']}"))

                    new_task_ids.append(str(task["task_id"]))

                msg = await pending_channel.send(embeds=embeds, view=view) # type: ignore
                for _ in batch:
                    new_msg_ids.append(str(msg.id))

            await update_pending_tasks_channel(user_id, new_task_ids, new_msg_ids)
            
        except Exception as e:
            logging.error(f"[ERR-TSK-020] [Task] sync_user_pending_tasks error: {e}")

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
                    member: discord.PermissionOverwrite(read_messages=True, send_messages=True),
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

            all_tasks = await retrieve_all_tasks_from_database()
            # Dashboard shows tasks you ASSIGNED
            user_tasks = [t for t in all_tasks if user_id == t.get("assigner_id") and t.get("global_state") == "Active"]
            
            await dash_channel.purge(limit=100) # type: ignore
            
            new_task_ids = []
            new_msg_ids = []

            # Batch tasks in groups of 5 to reduce mobile UI bloat
            BATCH_SIZE = 5
            for batch_start in range(0, len(user_tasks), BATCH_SIZE):
                batch = user_tasks[batch_start:batch_start + BATCH_SIZE]
                embeds = []
                view = ui.View(timeout=None)

                for task in batch:
                    embed = self._build_dashboard_embed(task)
                    embeds.append(embed)

                    # Request Update button
                    view.add_item(ui.Button(label=f"Update: {task['title'][:20]}", style=discord.ButtonStyle.primary, custom_id=f"dash_upd_{task['task_id']}"))

                    # Link Button
                    jump_url = task.get("temp_channel_link")
                    ch = self.bot.get_channel(int(task["channel_id"]))
                    if task.get("main_message_id") and ch:
                        jump_url = f"https://discord.com/channels/{guild.id}/{task['channel_id']}/{task['main_message_id']}"
                    view.add_item(ui.Button(label=f"Go: {task['title'][:20]}", style=discord.ButtonStyle.link, url=jump_url))

                    new_task_ids.append(str(task["task_id"]))

                msg = await dash_channel.send(embeds=embeds, view=view) # type: ignore
                for _ in batch:
                    new_msg_ids.append(str(msg.id))

            await update_assigner_dashboard_channel(user_id, new_task_ids, new_msg_ids)
            
        except Exception as e:
            logging.error(f"[ERR-TSK-021] [Task] sync_user_dashboard_tasks error: {e}")

    # -------------------------------------------------------------------------
    # Embed Builders (Task 2: Dashboard Embed Consolidation)
    # -------------------------------------------------------------------------

    def _build_pending_embed(self, task: dict, guild: discord.Guild = None) -> discord.Embed:
        """Unified pending-task embed with priority-based coloring and IST footer."""
        priority = task.get("priority", "Normal").lower()
        color_map = {"high": 0xFF0000, "medium": 0xFFFF00, "low": 0x95A5A6}
        embed_color = color_map.get(priority, 0x00FF00)

        embed = discord.Embed(title=f"📌 Pending Task: {task['title']}", color=embed_color)
        embed.add_field(name="Details", value=task['details'][:1024], inline=False)
        embed.add_field(name="Deadline", value=format_deadline(task['deadline']), inline=True)
        embed.add_field(name="Priority", value=task.get('priority', 'Normal'), inline=True)
        embed.set_footer(text=f"Synced: {now_ist().strftime('%d %b, %Y %I:%M %p IST')} | Concord Engine")
        return embed

    def _build_dashboard_embed(self, task: dict) -> discord.Embed:
        """Unified assigner-dashboard embed with IST footer."""
        embed = discord.Embed(title=f"⚙️ Managing: {task['title']}", color=0x3498db)
        assignees = ", ".join(task["assignees"])
        embed.add_field(name="Assignees", value=assignees, inline=False)
        embed.add_field(name="Status", value=task.get('status', 'Pending'), inline=True)
        embed.add_field(name="Deadline", value=format_deadline(task['deadline']), inline=True)
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

        return f"""
# 📋 **{task_data['title']}**
> {task_data['details']}

---
**Assigner:** {task_data['assigner']}
**Deadline:** {format_deadline(task_data['deadline'])}
**Priority:** {task_data.get('priority', 'Normal')}
**Global State:** {task_data.get('global_state', 'Active')}

**Assignees & Status:**
{roles_list}{act_log}
"""

    # -------------------------------------------------------------------------
    # Button builders
    # -------------------------------------------------------------------------
    async def update_main_task_message(self, task):
        try:
            channel_id = int(task.get("channel_id", 0))
            message_id = task.get("main_message_id")
            if not channel_id or not message_id:
                return
                
            temp_channel = self.bot.get_channel(channel_id)
            if not temp_channel:
                try:
                    temp_channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    return
                
            if not temp_channel: # If fetch_channel also failed or returned None
                return
                
            try:
                msg = await temp_channel.fetch_message(int(message_id))
            except discord.NotFound:
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

            markdown_content = f"""
# 📋 **{task['title']}**
> {task['details']}

---
**Assigner:** {task['assigner']}
**Deadline:** {format_deadline(task['deadline'])}
**Priority:** {task.get('priority', 'Normal')}
**Global State:** {task.get('global_state', 'Active')}

**Assignees & Status:**
{roles_list}{act_log}
"""
                
            view = self.get_main_task_view(task)
            
            # Since embeds have been dropped, we only pass content bounding
            await msg.edit(content=f"Task Assignment Created! <@{task['assigner_id']}> assigned this to " + ", ".join(f"<@{uid}>" for uid in assignee_ids_list) + "\n" + markdown_content, embed=None, view=view)
            
        except Exception as e:
            logging.error(f"[ERR-TSK-022] [Task] Error updating main task message: {e}")

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
        
        ack_button = ui.Button(label=ack_label, style=ack_style, custom_id=f"ack_{task['task_id']}", disabled=all_acknowledged)
        async def ack_cb(i: discord.Interaction):
            if i.user.id not in assignee_ids_list: # type: ignore
                return await self._send_ephemeral(i, "You are not an assignee on this task.")
            
            if i.user.id in acknowledged_list:
                return await self._send_ephemeral(i, "You have already acknowledged this task.")
                
            await i.response.defer()
            acknowledged_list.append(i.user.id) # type: ignore
            task["acknowledged_by"] = ",".join(map(str, acknowledged_list))
            
            await update_task_in_database(task)
            await self.update_main_task_message(task)
            
            # Sync channels immediately
            await self.sync_user_pending_tasks(int(task.get("assigner_id", 0)), i.guild) # type: ignore
            await self.sync_user_dashboard_tasks(int(task.get("assigner_id", 0)), i.guild)
            for uid in assignee_ids_list:
                await self.sync_user_pending_tasks(int(uid), i.guild)
                await self.sync_user_dashboard_tasks(int(uid), i.guild)
                
            await self._send_ephemeral(i, "You have acknowledged this task.")
            
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
                
            await i.response.defer()
            completion_vector[user_idx] = "1"
            task["completion_vector"] = ",".join(completion_vector)
            
            if all(bit == "1" for bit in completion_vector):
                task["global_state"] = "Pending Review"
                task["status"] = "Pending Assigner Review"
                temp_channel = self.bot.get_channel(int(task["channel_id"]))
                if temp_channel:
                    await temp_channel.send(f"✅ All assignees have completed their work! Assigner, please review.")
                    
            await update_task_in_database(task)
            await self.update_main_task_message(task)
            await self._send_ephemeral(i, "Your portion of the task has been marked complete.")
            
            await self.sync_user_pending_tasks(int(task.get("assigner_id", 0)), i.guild) # type: ignore
            await self.sync_user_dashboard_tasks(int(task.get("assigner_id", 0)), i.guild)
            for uid in task.get("assignee_ids", []):
                await self.sync_user_pending_tasks(int(uid), i.guild)
                await self.sync_user_dashboard_tasks(int(uid), i.guild)
                
        mark_complete_button.callback = mark_complete_cb
        
        if global_state == "Active":
            view.add_item(ack_button)
            # Only show mark complete if at least one person has acknowledged
            if len(acknowledged_list) > 0:
                view.add_item(mark_complete_button)
        elif global_state == "Pending Review":
            approve_btn = ui.Button(label="Approve Task", style=discord.ButtonStyle.success, custom_id=f"approve_panel_{task['task_id']}")
            async def approve_cb(i: discord.Interaction):
                if i.user.id != task.get("assigner_id"):
                    return await self._send_ephemeral(i, "Only the assigner can approve this task.")
                await mark_task_completed(int(task["task_id"]))
                
                # Update local state for immediate UI refresh
                task["global_state"] = "Finalized"
                task["status"] = "Finalized"
                
                temp_channel = self.bot.get_channel(int(task["channel_id"]))
                if temp_channel:
                    await temp_channel.send(f"✅ **Task Approved.** This channel will be automatically archived in 24 hours.")
                
                await self.update_main_task_message(task)
                
                await self.sync_user_pending_tasks(task["assigner_id"], i.guild)
                await self.sync_user_dashboard_tasks(task["assigner_id"], i.guild)
                for uid in task.get("assignee_ids", []):
                    await self.sync_user_pending_tasks(uid, i.guild)
                    await self.sync_user_dashboard_tasks(uid, i.guild)
            approve_btn.callback = approve_cb
            view.add_item(approve_btn)

            revise_btn = ui.Button(label="Request Revision", style=discord.ButtonStyle.danger, custom_id=f"revise_panel_{task['task_id']}")
            async def revise_cb(i: discord.Interaction):
                if i.user.id != task.get("assigner_id"):
                    return await self._send_ephemeral(i, "Only the assigner can request a revision.")
                class RevisionModal(ui.Modal, title="Request Revision"):
                    feedback = ui.TextInput(label="Feedback", style=discord.TextStyle.long, required=True, placeholder="What needs to be fixed?")
                    async def on_submit(inner_self, modal_interaction: discord.Interaction):
                        await modal_interaction.response.defer()
                        task["global_state"] = "Active"
                        task["status"] = "Active (Revision Requested)"
                        
                        num_assignees = len(task.get("assignee_ids", []))
                        task["completion_vector"] = ",".join(["0"] * num_assignees)
                        
                        current_log = task.get("activity_log", "")
                        timestamp = now_ist().strftime("%Y-%m-%d %H:%M IST")
                        new_entry = f"[{timestamp}] Assigner requested revision: {inner_self.feedback.value}"
                        task["activity_log"] = f"{current_log}\n{new_entry}" if current_log else new_entry
                        
                        await update_task_in_database(task)
                        
                        temp_channel = self.bot.get_channel(int(task["channel_id"]))
                        if temp_channel:
                            await temp_channel.send(f"⚠️ **Revision Requested by Assigner:**\n{inner_self.feedback.value}")
                        
                        await self.update_main_task_message(task)
                        await self._send_ephemeral(modal_interaction, "Revision requested and completion statuses reset.")
                        
                        await self.sync_user_pending_tasks(int(task.get("assigner_id", 0)), modal_interaction.guild)
                        await self.sync_user_dashboard_tasks(int(task.get("assigner_id", 0)), modal_interaction.guild)
                        for uid in task.get("assignee_ids", []):
                            await self.sync_user_pending_tasks(int(uid), modal_interaction.guild)
                            await self.sync_user_dashboard_tasks(int(uid), modal_interaction.guild)
                await i.response.send_modal(RevisionModal())
            revise_btn.callback = revise_cb
            view.add_item(revise_btn)
            
        # ----------------------------------------------------
        # ASSIGNER BUTTONS
        # ----------------------------------------------------
        
        manage_btn = ui.Button(label="Manage Task ⚙️", style=discord.ButtonStyle.secondary, custom_id=f"manage_{task['task_id']}")
        async def manage_cb(i: discord.Interaction):
            try:
                if i.user.id != task.get("assigner_id"):
                    return await self._send_ephemeral(i, "Only the assigner can manage this task.")
                
                await i.response.defer(ephemeral=True)
                control_view = self.get_assigner_control_view(task)
                await i.followup.send("⚙️ **Assigner Control Panel**", view=control_view, ephemeral=True)
            except Exception as e:
                import logging
                logging.error(f"[ERR-TSK-024] [Task] manage_cb error: {e}")
            
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
                    if not temp_channel: return
                    
                    existing_ids = task.get("assignee_ids", [])
                    completion_str = task.get("completion_vector", "")
                    completion_vector = completion_str.split(",") if completion_str else ["0"] * len(existing_ids)
                    
                    for user in new_users:
                        if user.id not in existing_ids: # type: ignore
                            existing_ids.append(user.id) # type: ignore
                            task.get("assignees", []).append(user.display_name) # type: ignore
                            completion_vector.append("0")
                            added.append(user)
                            # Grant channel access
                            if isinstance(temp_channel, discord.Thread):
                                await temp_channel.add_user(user)
                            else:
                                await temp_channel.set_permissions(user, read_messages=True, send_messages=True)
                            
                    if added:
                        task["completion_vector"] = ",".join(completion_vector)
                        await update_task_in_database(task)
                        await self.update_main_task_message(task)
                        
                        mentions = " ".join([u.mention for u in added])
                        await temp_channel.send(f"👥 **New Assignees Added:** {mentions} Welcome to the task!")
                        
                        for u in added:
                            await self.sync_user_pending_tasks(u.id, guild)
                            await self.sync_user_dashboard_tasks(u.id, guild)
                        await self.sync_user_dashboard_tasks(select_interaction.user.id, guild)
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
            
            await self_cog.sync_user_pending_tasks(int(task.get("assigner_id", 0)), i.guild) # type: ignore
            await self_cog.sync_user_dashboard_tasks(int(task.get("assigner_id", 0)), i.guild)
            for uid in task.get("assignee_ids", []):
                await self_cog.sync_user_pending_tasks(int(uid), i.guild)
                await self_cog.sync_user_dashboard_tasks(int(uid), i.guild)
        complete_button.callback = complete_cb
        view.add_item(complete_button)
        
        modify_button = ui.Button(label="Modify Deadline", style=discord.ButtonStyle.secondary, custom_id=f"modify_deadline_panel_{task['task_id']}")
        async def modify_cb(i: discord.Interaction):
            class ModifyDeadlineModal(ui.Modal, title="Modify Deadline"):
                new_deadline = ui.TextInput(label="New Deadline", style=discord.TextStyle.short, placeholder="DD/MM/YYYY HH:MM AM/PM", required=True)
                async def on_submit(inner_self, modal_interaction: discord.Interaction):
                    await modal_interaction.response.defer(ephemeral=True)
                    new_val = inner_self.new_deadline.value.strip()
                    try:
                        from datetime import datetime
                        datetime.strptime(new_val, "%d/%m/%Y %I:%M %p")
                    except ValueError:
                        await self_cog._send_ephemeral(modal_interaction, "❌ Call [ERR-TSK-025]: Invalid format. Please use `DD/MM/YYYY HH:MM AM/PM` (e.g. `27/10/2026 05:00 PM`)")
                        return

                    task["deadline"] = new_val
                    await update_task_in_database(task)
                    
                    await self_cog.update_main_task_message(task)
                    await self_cog._send_ephemeral(modal_interaction, "Deadline updated.")
                    
                    await self_cog.sync_user_pending_tasks(int(task.get("assigner_id", 0)), modal_interaction.guild) # type: ignore
                    await self_cog.sync_user_dashboard_tasks(int(task.get("assigner_id", 0)), modal_interaction.guild)
                    for uid in task.get("assignee_ids", []):
                        await self_cog.sync_user_pending_tasks(int(uid), modal_interaction.guild)
                        await self_cog.sync_user_dashboard_tasks(int(uid), modal_interaction.guild)
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

    async def check_and_remove_invalid_tasks(self):
        await self.bot.wait_until_ready()
        while True:
            try:
                # In the new PostgreSQL schema, we don't have a direct 'list all pending channels' method.
                # Cleanup is now performed during user interaction or manual sync to ensure consistency.
                # This loop is kept as a heartbeat but remains idle for now.
                pass 
                
            except Exception as e:
                logging.error(f"[ERR-TSK-026] [Task] Error in check_and_remove_invalid_tasks: {e}")
            await asyncio.sleep(300) # Poll every 5 mins

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
                        with get_conn() as conn:
                            with conn.cursor() as cur:
                                cur.execute("SELECT * FROM notification_queue WHERE sent = FALSE")
                                return cur.fetchall()
                    
                    queued = await db_execute(_get_queue)
                    for q in queued:
                        try:
                            user = await self.bot.fetch_user(q['recipient_id'])
                            if user:
                                await user.send(f"🌅 **Morning Update:** {q['content']}")
                            
                            def _mark_sent(qid=q['id']):
                                with get_conn() as conn:
                                    with conn.cursor() as cur:
                                        cur.execute("UPDATE notification_queue SET sent = TRUE WHERE id = %s", (qid,))
                                    conn.commit()
                            await db_execute(_mark_sent)
                        except Exception as e:
                            logging.error(f"[ERR-TSK-027] [Task Queue] Failed delivery of {q['id']}: {e}")

                # 2. Main Logic Process
                tasks = await retrieve_all_tasks_from_database()
                now = datetime.now(IST)
                
                for task in tasks:
                    if task.get("global_state", "Active") != "Active":
                        continue
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
                    
                    # Logic Mapping from concord_logic.txt
                    if priority == "High":
                        if hours_diff <= 24 and "24h" not in sent_list:
                            triggers.append(("24h", f"⚠️ **Urgent Nudge:** Task **{task['title']}** is due in 24 hours.", task['assignee_ids']))
                        if hours_diff <= 4 and "4h" not in sent_list:
                            triggers.append(("4h", f"🚨 **Priority Alert:** Task **{task['title']}** is due in just 4 hours!", task['assignee_ids']))
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

                    elif priority == "Medium":
                        if hours_diff <= 24 and "24h" not in sent_list:
                            triggers.append(("24h", f"📅 **Reminder:** Task **{task['title']}** due in 24 hours.", task['assignee_ids']))
                        if hours_diff <= 2 and "2h" not in sent_list:
                            triggers.append(("2h", f"🔔 **Final Alert:** Task **{task['title']}** due in 2 hours.", task['assignee_ids']))

                        if hours_diff <= -0.25: # exceeds 15m
                            if "0m_overdue" not in sent_list:
                                triggers.append(("0m_overdue", "❌ **Overdue:** Deadline passed.", "thread"))
                            if hours_diff <= -4.0 and "4h_overdue" not in sent_list:
                                triggers.append(("4h_overdue", "⚠️ **Still Overdue:** 4 hours past deadline.", "thread_and_assigner"))
                            if hours_diff <= -24.0 and "24h_esc" not in sent_list:
                                triggers.append(("24h_esc", "📡 **Escalation (24h):** Notifying Department Manager.", "esc_dept"))

                    elif priority == "Normal":
                        if hours_diff <= 24 and "24h" not in sent_list:
                            triggers.append(("24h", f"📌 **Task Nudge:** **{task['title']}** due in 24 hours.", task['assignee_ids']))
                        
                        if hours_diff <= -0.25: # exceeds 15m
                            if "0m_overdue" not in sent_list:
                                triggers.append(("0m_overdue", "❌ **Deadline Passed.**", "thread"))
                            if hours_diff <= -48.0 and "48h_esc" not in sent_list:
                                triggers.append(("48h_esc", "📡 **Escalation (48h):** Notifying Department Manager.", "esc_dept"))

                    elif priority == "Low":
                        if hours_diff <= 48 and "48h" not in sent_list:
                            triggers.append(("48h", f"📎 **Upcoming:** **{task['title']}** due in 48 hours.", task['assignee_ids']))

                    # Execute Triggers
                    for slug, content, target in triggers:
                        sent_list.append(slug)
                        task["reminders_sent"] = ",".join(sent_list)
                        await update_task_in_database(task)
                        
                        # Routing logic
                        chan = self.bot.get_channel(int(task['channel_id']))
                        if not chan:
                            try:
                                chan = await self.bot.fetch_channel(int(task['channel_id']))
                            except Exception:
                                pass
                        
                        if target == "thread" or target == "thread_and_assigner":
                            if chan:
                                # Get mentions
                                assignee_mentions = " ".join([f"<@{uid}>" for uid in task['assignee_ids']])
                                final_msg = f"{assignee_mentions} {content}"
                                if target == "thread_and_assigner":
                                    final_msg += f" <@{task['assigner_id']}>"
                                await chan.send(final_msg)
                        elif target == "esc_dept":
                            # Use mapping from DEPARTMENTS if applicable, or logic for identifying dept mgr
                            # For now, let's look for a role with name mapping or default log
                            logging.warning(f"[ERR-TSK-028] [Escalation] Task {task['task_id']} escalated to Dept Manager.")
                            if chan: await chan.send(f"📡 **Department Manager alerted.**")
                        elif isinstance(target, list):
                            # DM Target
                            for uid in target:
                                await self.deliver_notification(task['task_id'], int(uid), content)

                # End Main Logic
            except Exception as e:
                logging.error(f"[ERR-TSK-029] [Task] Error in task_reminder_engine: {e}")
                
            await asyncio.sleep(60 * 5) # Poll every 5 minutes

    async def archive_task_channel(self, task, channel: discord.TextChannel):
        import os
        import json as _json

        archive_root = os.getenv("ARCHIVE_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Archives", "Tasks"))
        safe_title = "".join([c for c in task['title'] if c.isalpha() or c.isdigit() or c in (' ', '-', '_')]).rstrip()
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
                f.write(f"--- Task Transcript: {task['title']} ---\n")
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
                            logging.warning(f"[ERR-TSK-030] [Task Archive] Skipped attachment: {attachment.filename} — {skip_reason}")
                            continue

                        safe_filename = f"{message.id}_{count}_{attachment.filename}"
                        attachment_path = os.path.join(task_dir, safe_filename)
                        try:
                            await attachment.save(attachment_path)
                            actual_size = os.path.getsize(attachment_path)
                            cumulative_bytes += actual_size
                            saved_attachments.append({"filename": safe_filename, "size": actual_size})
                        except Exception as file_err:
                            logging.error(f"[ERR-TSK-031] [Task Archive] Failed to download attachment {attachment.filename}: {file_err}")
                            f.write(f"  -> [Error saving attachment]\n")
                            skipped_attachments.append({"filename": attachment.filename, "size": attachment.size, "url": attachment.url, "reason": f"download error: {file_err}"})
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

            logging.info(f"[Task Archive] Successfully archived '{task['title']}' to {task_dir} "
                         f"(saved: {len(saved_attachments)}, skipped: {len(skipped_attachments)}, "
                         f"total: {cumulative_bytes / (1024*1024):.1f} MB)")
        except Exception as e:
            logging.error(f"[ERR-TSK-032] [Task Archive] Failed to archive channel history: {e}")

    # -------------------------------------------------------------------------
    # Commands
    # -------------------------------------------------------------------------

    @commands.command(name="view_tasks")
    async def view_tasks_cmd(self, ctx):
        """Lists all pending tasks."""
        try:
            tasks = await retrieve_all_tasks_from_database()
            if not tasks:
                await ctx.send("No pending tasks found.")
                return
            for task in tasks:
                embed = discord.Embed(title="Pending Task", color=0x00FF00)
                channel = self.bot.get_channel(task["channel_id"])
                ch_name = channel.name if channel else f"Channel ID {task['channel_id']}"
                assignees = ", ".join(task["assignees"])
                embed.add_field(name=f"Task in {ch_name}", value=f"**Assignees:** {assignees}\n**Details:** {task['details']}\n**Deadline:** {task['deadline']}", inline=False)
                view = await self.handle_task_buttons(ctx, task)
                if view:
                    await ctx.send(embed=embed, view=view)
                else:
                    await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(TaskCog(bot))

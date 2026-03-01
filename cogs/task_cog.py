"""
cogs/task_cog.py — Task Management Cog
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import asyncio
import sqlite3
import logging
import discord
from discord import ui
from discord.ext import commands
import difflib
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Bots'))

from db_managers.task_db_manager import (
    check_and_create_database,
    store_task_in_database,
    retrieve_task_from_database,
    update_task_in_database,
    retrieve_all_tasks_from_database,
    _store_task_in_database_sync,
    _retrieve_task_from_database_sync,
    _update_task_in_database_sync,
    _retrieve_all_tasks_from_database_sync,
    _delete_task_from_database_sync,
    store_pending_tasks_channel,
    update_pending_tasks_channel,
    retrieve_pending_tasks_channel,
    _delete_pending_tasks_channel_from_database,
    db_path,
)

COMMAND_CHANNEL_ID = 1293531912496746638
TASK_CATEGORY_ID = 1299338707605651537
EMP_ROLE_ID = 1290199089371287562

DEPARTMENTS = {
    "Administration": 1281171713299714059,
    "Architects": 1281172225432752149,
    "CAD": 1281172603217645588,
    "Site": 1285183387258327050,
    "Interns": 1281195640109400085,
}


def find_closest_match(name: str, members):
    names = [m.display_name.lower() for m in members]
    matches = difflib.get_close_matches(name.lower(), names, n=1, cutoff=0.6)
    if matches:
        for m in members:
            if m.display_name.lower() == matches[0]:
                return m
    return None


class TaskCog(commands.Cog, name="Tasks"):
    """Handles task assignment and tracking."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def cog_load(self):
        check_and_create_database()
        asyncio.ensure_future(self.check_and_remove_invalid_tasks())

    # -------------------------------------------------------------------------
    # Events
    # -------------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        command_channel = self.bot.get_channel(COMMAND_CHANNEL_ID)
        if not command_channel:
            logging.warning("[Task] Command channel not found.")
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
        if custom_id == "assign_task_button":
            await self.handle_assign_task(interaction)
        elif custom_id == "view_tasks_button":
            await self.handle_view_tasks_button(interaction)

    # -------------------------------------------------------------------------
    # Assign Task flow
    # -------------------------------------------------------------------------

    async def handle_assign_task(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            }
            category = interaction.guild.get_channel(TASK_CATEGORY_ID)
            temp_channel = await interaction.guild.create_text_channel(
                f"task-assignment-{interaction.user.name}", overwrites=overwrites, category=category
            )

            await interaction.followup.send(
                f"Task assignment started. Check the new channel: [Click here]({temp_channel.jump_url})",
                ephemeral=True,
            )

            emp_role = interaction.guild.get_role(EMP_ROLE_ID)
            assignee_ids = []
            task_data = {
                "channel_id": temp_channel.id,
                "assignees": [],
                "details": "",
                "deadline": "",
                "temp_channel_link": temp_channel.jump_url,
                "assigner": interaction.user.display_name,
                "assigner_id": interaction.user.id,
                "assignee_ids": assignee_ids,
                "status": "Pending",
                "title": "",
            }

            self.bot.loop.create_task(
                self.monitor_task_assignment_channel(task_data, temp_channel, interaction)
            )

            class TaskDetailsModal(ui.Modal, title="Enter Task Details"):
                task_title = ui.TextInput(label="Task Title", style=discord.TextStyle.short, placeholder="Concise title", required=True)
                task_details = ui.TextInput(label="Task Description", style=discord.TextStyle.long, placeholder="Detailed explanation", required=True)
                task_deadline = ui.TextInput(label="Deadline", style=discord.TextStyle.short, placeholder="DD/MM/YYYY HH:MM AM/PM", required=True)

                async def on_submit(inner_self, modal_interaction: discord.Interaction):
                    await modal_interaction.response.defer()
                    task_data["title"] = inner_self.task_title.value
                    task_data["details"] = inner_self.task_details.value
                    task_data["deadline"] = inner_self.task_deadline.value
                    await temp_channel.edit(name=f"task-{inner_self.task_title.value.replace(' ', '-')}")
                    for aid in assignee_ids:
                        member = interaction.guild.get_member(int(aid))
                        if member:
                            await temp_channel.set_permissions(member, read_messages=True, send_messages=True)
                    task_data["assignees"] = [
                        interaction.guild.get_member(int(aid)).display_name for aid in assignee_ids
                    ]
                    await self.prompt_deadline_confirmation(temp_channel, task_data, interaction.user.id, assignee_ids)

            class AssigneeModal(ui.Modal, title="Select Assignees"):
                assignees_input = ui.TextInput(label="Assignee names (comma separated)", style=discord.TextStyle.short, placeholder="E.g., John, Jane", required=True)

                async def on_submit(inner_self, modal_interaction: discord.Interaction):
                    await modal_interaction.response.defer()
                    names = inner_self.assignees_input.value.split(",")
                    assignees = []
                    assignee_ids.clear()
                    for name in names:
                        name = name.strip()
                        match = find_closest_match(name, emp_role.members)
                        if match:
                            assignees.append(match)
                            assignee_ids.append(str(match.id))
                        else:
                            await temp_channel.send(f"No match found for '{name}'. Please retry.")
                            retry_view = ui.View(timeout=None)
                            retry_btn = ui.Button(label="Retry Selection", style=discord.ButtonStyle.secondary)
                            async def retry_cb(m_interaction):
                                await m_interaction.response.send_modal(AssigneeModal())
                            retry_btn.callback = retry_cb
                            retry_view.add_item(retry_btn)
                            await temp_channel.send("Retry selecting assignees:", view=retry_view)
                            return

                    names_str = ", ".join(a.display_name for a in assignees)
                    await temp_channel.send(f"Selected assignees: {names_str}")

                    v = ui.View(timeout=None)
                    retry_button = ui.Button(label="Retry Selection", style=discord.ButtonStyle.secondary)
                    confirm_button = ui.Button(label="Confirm Submission", style=discord.ButtonStyle.success)

                    async def retry_button_callback(btn_i):
                        await btn_i.response.send_modal(AssigneeModal())
                    async def confirm_button_callback(btn_i):
                        await btn_i.response.send_modal(TaskDetailsModal())

                    retry_button.callback = retry_button_callback
                    confirm_button.callback = confirm_button_callback
                    v.add_item(retry_button)
                    v.add_item(confirm_button)
                    await temp_channel.send("Confirm the assignees or retry:", view=v)

            start_view = ui.View(timeout=None)
            start_button = ui.Button(label="Enter Assignees", style=discord.ButtonStyle.primary)
            async def start_button_callback(btn_i):
                await btn_i.response.send_modal(AssigneeModal())
            start_button.callback = start_button_callback
            start_view.add_item(start_button)
            await temp_channel.send("Welcome to task assignment! Click below to enter assignees.", view=start_view)

        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    # -------------------------------------------------------------------------
    # View Tasks flow
    # -------------------------------------------------------------------------

    async def handle_view_tasks_button(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
            user_id = interaction.user.id
            user_nickname = interaction.user.display_name
            category = interaction.guild.get_channel(TASK_CATEGORY_ID)
            channel_id, sent_task_ids, task_message_ids = retrieve_pending_tasks_channel(user_id)

            if channel_id:
                existing_channel = self.bot.get_channel(channel_id)
                if existing_channel:
                    await interaction.followup.send("Tasks have been refreshed.", ephemeral=True)
                else:
                    _delete_pending_tasks_channel_from_database(user_id)
                    channel_id = None

            if not channel_id:
                overwrites = {
                    interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
                }
                pending_tasks_channel = await interaction.guild.create_text_channel(
                    f"pending-tasks-{user_nickname}", overwrites=overwrites, category=category
                )
                store_pending_tasks_channel(user_id, pending_tasks_channel.id)
                await interaction.followup.send(f"Pending tasks channel: {pending_tasks_channel.jump_url}", ephemeral=True)
            else:
                pending_tasks_channel = self.bot.get_channel(channel_id)

            tasks = await retrieve_all_tasks_from_database()
            user_tasks = [
                t for t in tasks
                if interaction.user.display_name in t["assignees"] or t["assigner"] == interaction.user.display_name
            ]
            new_tasks_found = False

            for task in user_tasks:
                if str(task["task_id"]) in sent_task_ids:
                    continue
                new_tasks_found = True
                embed = discord.Embed(title="Pending Task", color=0x00FF00)
                channel = self.bot.get_channel(task["channel_id"])
                channel_name = channel.name if channel else f"Channel ID {task['channel_id']}"
                assignees = ", ".join(task["assignees"])
                embed.add_field(name=f"Task in {channel_name}", value=f"**Assignees:** {assignees}\n**Details:** {task['details']}\n**Deadline:** {task['deadline']}", inline=False)
                view = await self.handle_task_buttons(interaction, task)
                if view:
                    message = await pending_tasks_channel.send(embed=embed, view=view)
                else:
                    message = await pending_tasks_channel.send(embed=embed)
                sent_task_ids.append(str(task["task_id"]))
                task_message_ids.append(str(message.id))
                update_pending_tasks_channel(user_id, sent_task_ids, task_message_ids)

            if not new_tasks_found:
                await interaction.followup.send("No new tasks found.", ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    # -------------------------------------------------------------------------
    # Button builders
    # -------------------------------------------------------------------------

    async def handle_task_buttons(self, interaction, task):
        try:
            if "status" not in task:
                task["status"] = "Pending"
            if interaction.user.display_name in task["assignees"]:
                return await self.handle_assignee_buttons(interaction, task)
            elif interaction.user.display_name == task["assigner"]:
                return await self.handle_assigner_buttons(interaction, task)
            return None
        except Exception as e:
            print(f"[Task] Error in handle_task_buttons: {e}")
            return None

    async def handle_assignee_buttons(self, interaction, task):
        view = ui.View(timeout=None)
        link_button = ui.Button(label="Task Link", style=discord.ButtonStyle.link, url=task["temp_channel_link"])
        view.add_item(link_button)

        modify_button = ui.Button(label="Modify Deadline", style=discord.ButtonStyle.secondary, custom_id=f"modify_deadline_{task['task_id']}")
        async def modify_cb(i):
            try:
                await i.response.defer()
                temp_channel = self.bot.get_channel(task["channel_id"])
                if temp_channel:
                    await temp_channel.send("Please enter the new deadline (DD/MM/YYYY HH:MM AM/PM):")
                    msg = await self.bot.wait_for("message", check=lambda m: m.author == i.user and m.channel == temp_channel)
                    task["new_deadline"] = msg.content
                    task["assigner_id"] = i.guild.get_member_named(task["assigner"]).id
                    task["assignee_ids"] = [i.guild.get_member_named(n).id for n in task["assignees"]]
                    task["status"] = "Pending"
                    await self.deadline_modification_prompt(temp_channel, task, task["assigner_id"], task["assignee_ids"])
            except Exception as e:
                await i.followup.send(f"An error occurred: {e}", ephemeral=True)
        modify_button.callback = modify_cb
        view.add_item(modify_button)

        mark_complete_button = ui.Button(label="Mark as Complete", style=discord.ButtonStyle.success, custom_id=f"mark_complete_{task['task_id']}")
        async def mark_complete_cb(i):
            try:
                await i.response.defer()
                task["status"] = "Completed by Assignee"
                await update_task_in_database(task)
                await i.followup.send("Task marked as complete. The assigner will be notified.", ephemeral=True)
                assigner_id = i.guild.get_member_named(task["assigner"]).id
                await self.update_assigner_view(task, assigner_id, i)
            except Exception as e:
                await i.followup.send(f"An error occurred: {e}", ephemeral=True)
        mark_complete_button.callback = mark_complete_cb
        view.add_item(mark_complete_button)

        return view

    async def handle_assigner_buttons(self, interaction, task):
        view = ui.View(timeout=None)
        link_button = ui.Button(label="Task Link", style=discord.ButtonStyle.link, url=task["temp_channel_link"])
        complete_button = ui.Button(
            label="Task Completed",
            style=discord.ButtonStyle.success if task["status"] == "Completed by Assignee" else discord.ButtonStyle.danger,
            custom_id=f"complete_task_{task['task_id']}",
        )

        async def complete_cb(i):
            try:
                await i.response.defer()
                temp_channel = self.bot.get_channel(task["channel_id"])
                if temp_channel:
                    await temp_channel.delete()
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, _delete_task_from_database_sync, task["channel_id"])
                await i.message.delete()
                await i.followup.send("Task completed and channel deleted.", ephemeral=True)
                # Cleanup assigner's pending channel
                uid = i.user.id
                cid, stids, tmids = retrieve_pending_tasks_channel(uid)
                if str(task["task_id"]) in stids:
                    idx = stids.index(str(task["task_id"]))
                    stids.pop(idx)
                    tmids.pop(idx)
                    update_pending_tasks_channel(uid, stids, tmids)
                # Cleanup assignees' pending channels
                for assignee_name in task["assignees"]:
                    assignee = discord.utils.get(i.guild.members, display_name=assignee_name)
                    if assignee:
                        acid, astids, atmids = retrieve_pending_tasks_channel(assignee.id)
                        if str(task["task_id"]) in astids:
                            aidx = astids.index(str(task["task_id"]))
                            mid = atmids[aidx]
                            astids.pop(aidx)
                            atmids.pop(aidx)
                            update_pending_tasks_channel(assignee.id, astids, atmids)
                            ach = self.bot.get_channel(acid)
                            if ach:
                                try:
                                    m = await ach.fetch_message(int(mid))
                                    await m.delete()
                                except discord.NotFound:
                                    pass
            except Exception as e:
                await i.followup.send(f"An error occurred: {e}", ephemeral=True)

        complete_button.callback = complete_cb
        view.add_item(link_button)
        view.add_item(complete_button)

        remind_button = ui.Button(label="Remind Assignee", style=discord.ButtonStyle.primary, custom_id=f"remind_task_{task['task_id']}")
        async def remind_cb(i):
            try:
                await i.response.defer()
                for name in task["assignees"]:
                    m = discord.utils.get(i.guild.members, display_name=name)
                    if m:
                        await m.send(f"Pending task: {task['details']}\nDeadline: {task['deadline']}\nChannel: {task['temp_channel_link']}")
                await i.followup.send("Assignees reminded.", ephemeral=True)
            except Exception as e:
                await i.followup.send(f"An error occurred: {e}", ephemeral=True)
        remind_button.callback = remind_cb
        view.add_item(remind_button)

        return view

    # -------------------------------------------------------------------------
    # Deadline prompts
    # -------------------------------------------------------------------------

    async def prompt_deadline_confirmation(self, channel, task_data, assigner_id, assignee_ids):
        embed = discord.Embed(title=task_data["title"], description=task_data["details"], color=0x00FF00)
        embed.add_field(name="Proposed Deadline", value=task_data.get("new_deadline", task_data["deadline"]), inline=False)
        embed.set_footer(text="Please confirm or modify the deadline below.")

        confirm_button = ui.Button(label="Confirm Deadline", style=discord.ButtonStyle.success, custom_id="confirm_deadline_button")
        modify_button = ui.Button(label="Modify Deadline", style=discord.ButtonStyle.secondary, custom_id="modify_deadline_button")
        confirmed_users = set()
        view = ui.View(timeout=None)

        async def confirm_cb(i):
            try:
                await i.response.defer()
                confirmed_users.add(i.user.id)
                if assigner_id in confirmed_users and all(int(aid) in confirmed_users for aid in assignee_ids):
                    task_data["deadline"] = task_data.get("new_deadline", task_data["deadline"])
                    task_data["status"] = "Confirmed"
                    await store_task_in_database(task_data)
                    await i.followup.send("Deadline confirmed by all parties! Task stored.", ephemeral=False)
                else:
                    await i.followup.send("Confirmed. Waiting for the other party.", ephemeral=True)
            except Exception as e:
                await i.followup.send(f"An error occurred: {e}", ephemeral=True)

        async def modify_cb(i):
            await i.response.send_message("Please enter the new deadline (DD/MM/YYYY HH:MM AM/PM):", ephemeral=True)
            msg = await self.bot.wait_for("message", check=lambda m: m.author == i.user and m.channel == channel)
            task_data["new_deadline"] = msg.content
            confirmed_users.clear()
            embed.set_field_at(0, name="Proposed Deadline", value=msg.content, inline=False)
            await channel.send("Deadline modified.", embed=embed, view=view)

        confirm_button.callback = confirm_cb
        modify_button.callback = modify_cb
        view.add_item(confirm_button)
        view.add_item(modify_button)
        await channel.send(embed=embed, view=view)

    async def deadline_modification_prompt(self, channel, task_data, assigner_id, assignee_ids):
        embed = discord.Embed(title=task_data["title"], description=task_data["details"], color=0x00FF00)
        embed.add_field(name="Proposed Deadline", value=task_data.get("new_deadline", task_data["deadline"]), inline=False)
        embed.set_footer(text="Please confirm or modify the deadline below.")

        confirm_button = ui.Button(label="Confirm Deadline", style=discord.ButtonStyle.success, custom_id="confirm_deadline_button")
        modify_button = ui.Button(label="Modify Deadline", style=discord.ButtonStyle.secondary, custom_id="modify_deadline_button")
        confirmed_users = set()
        view = ui.View(timeout=None)

        async def confirm_cb(i):
            try:
                await i.response.defer()
                confirmed_users.add(i.user.id)
                if assigner_id in confirmed_users and all(int(aid) in confirmed_users for aid in assignee_ids):
                    task_data["deadline"] = task_data.get("new_deadline", task_data["deadline"])
                    task_data["status"] = "Confirmed"
                    await update_task_in_database(task_data)
                    await self.edit_task_message_with_modified_deadline(task_data, assigner_id, assignee_ids, i)
                    await i.followup.send("Deadline confirmed and updated!", ephemeral=False)
                else:
                    await i.followup.send("Confirmed. Waiting for the other party.", ephemeral=True)
            except Exception as e:
                await i.followup.send(f"An error occurred: {e}", ephemeral=True)

        async def modify_cb(i):
            try:
                await i.response.defer()
                await i.followup.send("Please enter the new deadline (DD/MM/YYYY HH:MM AM/PM):", ephemeral=True)
                msg = await self.bot.wait_for("message", check=lambda m: m.author == i.user and m.channel == channel)
                task_data["new_deadline"] = msg.content
                confirmed_users.clear()
                embed.set_field_at(0, name="Proposed Deadline", value=msg.content, inline=False)
                await channel.send("Deadline modified.", embed=embed, view=view)
            except Exception as e:
                await i.followup.send(f"An error occurred: {e}", ephemeral=True)

        confirm_button.callback = confirm_cb
        modify_button.callback = modify_cb
        view.add_item(confirm_button)
        view.add_item(modify_button)
        await channel.send(embed=embed, view=view)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    async def update_assigner_view(self, task, assigner_id, interaction):
        try:
            cid, stids, tmids = retrieve_pending_tasks_channel(str(assigner_id))
            if cid:
                ach = self.bot.get_channel(cid)
                if ach:
                    for tid, mid in zip(stids, tmids):
                        if str(task["task_id"]) == tid:
                            msg = await ach.fetch_message(int(mid))
                            embed = discord.Embed(title="Pending Task", color=0x00FF00)
                            ch = self.bot.get_channel(task["channel_id"])
                            ch_name = ch.name if ch else f"Channel ID {task['channel_id']}"
                            assignees = ", ".join(task["assignees"])
                            embed.add_field(name=f"Task in {ch_name}", value=f"**Assignees:** {assignees}\n**Details:** {task['details']}\n**Deadline:** {task['deadline']}", inline=False)
                            view = await self.handle_assigner_buttons(interaction, task)
                            await msg.edit(embed=embed, view=view)
                            break
        except Exception as e:
            print(f"[Task] Error updating assigner view: {e}")

    async def edit_task_message_with_modified_deadline(self, task_data, assigner_id, assignee_ids, interaction):
        try:
            acid, astids, atmids = retrieve_pending_tasks_channel(str(assigner_id))
            if acid:
                ach = self.bot.get_channel(acid)
                if ach:
                    for tid, mid in zip(astids, atmids):
                        if str(task_data["task_id"]) == tid:
                            msg = await ach.fetch_message(int(mid))
                            embed = discord.Embed(title=task_data["title"], color=0x00FF00)
                            ch = self.bot.get_channel(task_data["channel_id"])
                            ch_name = ch.name if ch else f"Channel ID {task_data['channel_id']}"
                            assignees = ", ".join(task_data["assignees"])
                            embed.add_field(name=f"Task in {ch_name}", value=f"**Assignees:** {assignees}\n**Details:** {task_data['details']}\n**Deadline:** {task_data['deadline']}", inline=False)
                            view = await self.handle_assigner_buttons(interaction, task_data)
                            await msg.edit(embed=embed, view=view)
                            break

            assignee_channels = [retrieve_pending_tasks_channel(str(aid)) for aid in assignee_ids]
            for a_cid, a_stids, a_tmids in assignee_channels:
                if a_cid:
                    a_ch = self.bot.get_channel(a_cid)
                    if a_ch:
                        for tid, mid in zip(a_stids, a_tmids):
                            if str(task_data["task_id"]) == tid:
                                msg = await a_ch.fetch_message(int(mid))
                                embed = discord.Embed(title=task_data["title"], color=0x00FF00)
                                ch = self.bot.get_channel(task_data["channel_id"])
                                ch_name = ch.name if ch else f"Channel ID {task_data['channel_id']}"
                                assignees = ", ".join(task_data["assignees"])
                                embed.add_field(name=f"Task in {ch_name}", value=f"**Assignees:** {assignees}\n**Details:** {task_data['details']}\n**Deadline:** {task_data['deadline']}", inline=False)
                                view = await self.handle_assignee_buttons(interaction, task_data)
                                await msg.edit(embed=embed, view=view)
                                break
        except Exception as e:
            print(f"[Task] Error editing task message: {e}")

    async def monitor_task_assignment_channel(self, task_data, temp_channel, interaction):
        last_update = asyncio.get_event_loop().time()
        while True:
            await asyncio.sleep(5)
            if task_data.get("details") or task_data.get("deadline"):
                last_update = asyncio.get_event_loop().time()
            if asyncio.get_event_loop().time() - last_update > 300:
                try:
                    await temp_channel.delete()
                    await interaction.followup.send("Task assignment channel deleted due to inactivity.", ephemeral=True)
                except discord.NotFound:
                    pass
                break

    async def check_and_remove_invalid_tasks(self):
        while True:
            try:
                tasks = await retrieve_all_tasks_from_database()
                task_ids_in_db = {str(t["task_id"]) for t in tasks}
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT user_id, tasks, task_message_ids FROM pending_tasks_channels")
                rows = cursor.fetchall()
                conn.close()
                for row in rows:
                    user_id, task_str, msg_str = row
                    task_ids = task_str.split(",") if task_str else []
                    msg_ids = msg_str.split(",") if msg_str else []
                    invalid = [tid for tid in task_ids if tid not in task_ids_in_db]
                    if invalid:
                        cid, _, _ = retrieve_pending_tasks_channel(user_id)
                        if cid:
                            ch = self.bot.get_channel(cid)
                            if ch:
                                for tid in invalid:
                                    if tid in task_ids:
                                        idx = task_ids.index(tid)
                                        mid = msg_ids[idx]
                                        try:
                                            m = await ch.fetch_message(int(mid))
                                            await m.delete()
                                        except discord.NotFound:
                                            pass
                                        task_ids.pop(idx)
                                        msg_ids.pop(idx)
                        update_pending_tasks_channel(user_id, task_ids, msg_ids)
            except Exception as e:
                print(f"[Task] Error in check_and_remove_invalid_tasks: {e}")
            await asyncio.sleep(60)

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

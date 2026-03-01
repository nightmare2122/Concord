"""
cogs/leave_cog.py — Leave Management Cog
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import sys
import os
import re
import asyncio
import logging
import pandas as pd
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.table import Table, TableStyleInfo

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Bots'))
from db_managers import leave_db_manager as db

# ─── Channel / Role Configuration ────────────────────────────────────────────

SUBMIT_CHANNEL_ID = 1281201690904629289
EMP_ROLE_ID = 1290199089371287562

APPROVAL_CHANNELS = {
    'architects': 1298229045229781052,
    'site': 1298229146228359200,
    'cad': 1298229187865346048,
    'administration': 1298229241338662932,
    'hr': 1283723426103562343,
    'pa': 1283723484698120233,
    'interns': 1298229045229781052,
    'heads': 1283723426103562343,
    'project_coordinator': 1283723426103562343,
}

DEPARTMENT_ROLES = {
    'architects': 1281172225432752149,
    'site': 1285183387258327050,
    'cad': 1281172603217645588,
    'administration': 1281171713299714059,
    'interns': 1281195640109400085,
}

DIRECT_SECOND_APPROVAL_ROLES = {
    'project_coordinator': 1298230195991478322,
    'heads': 1281173876704804937,
}


# ─── Embed builder ────────────────────────────────────────────────────────────

def create_leave_embed(leave_details, user_id, nickname, current_stage):
    embed = discord.Embed(title="Leave Application", color=5810975)
    embed.add_field(name="Name", value=nickname, inline=False)
    if leave_details.get('leave_type'):
        embed.add_field(name="Leave Type", value=leave_details['leave_type'], inline=False)
    if leave_details.get('leave_reason'):
        embed.add_field(name="Leave Reason", value=leave_details['leave_reason'], inline=False)
    if leave_details.get('leave_duration'):
        embed.add_field(name="Leave Duration", value=leave_details['leave_duration'], inline=False)
    if leave_details.get('date_from'):
        embed.add_field(name="Date From", value=leave_details['date_from'], inline=False)
    if leave_details.get('date_to'):
        embed.add_field(name="Date To", value=leave_details['date_to'], inline=False)
    if leave_details.get('number_of_days_off') is not None:
        embed.add_field(name="Number of Days Off", value=leave_details['number_of_days_off'], inline=False)
    if leave_details.get('resume_office_on'):
        embed.add_field(name="Resume Office On", value=leave_details['resume_office_on'], inline=False)
    if leave_details.get('time_off'):
        embed.add_field(name="Time Off", value=leave_details['time_off'], inline=False)
    if leave_details.get('time_period'):
        embed.add_field(name="Time Period", value=leave_details['time_period'], inline=False)
    if leave_details.get('leave_id'):
        embed.add_field(name="Leave ID", value=leave_details['leave_id'], inline=False)
    if leave_details.get('approved_by'):
        embed.add_field(name="Approved By", value=leave_details['approved_by'], inline=False)
    embed.set_footer(text=f"Stage: {current_stage} | User ID: {user_id}")
    return embed


def extract_leave_details_from_embed(embed):
    leave_details = {}
    for field in embed.fields:
        if field.name == "Leave Type":
            leave_details['leave_type'] = field.value
        elif field.name == "Leave Reason":
            leave_details['leave_reason'] = field.value
        elif field.name == "Date From":
            leave_details['date_from'] = field.value
        elif field.name == "Date To":
            leave_details['date_to'] = field.value
        elif field.name == "Number of Days Off":
            leave_details['number_of_days_off'] = float(field.value)
        elif field.name == "Resume Office On":
            leave_details['resume_office_on'] = field.value
        elif field.name == "Time Off":
            leave_details['time_off'] = field.value
        elif field.name == "Leave ID":
            leave_details['leave_id'] = int(field.value)
        elif field.name == "Approved By":
            leave_details['approved_by'] = field.value
    return leave_details


# ─── UI Components ────────────────────────────────────────────────────────────

class LeaveApplicationView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Full Day", style=discord.ButtonStyle.primary, custom_id="FormID1")
    async def full_day_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FullDayLeaveModal())

    @discord.ui.button(label="Half Day", style=discord.ButtonStyle.primary, custom_id="FormID2")
    async def half_day_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(HalfDayLeaveModal())

    @discord.ui.button(label="Off Duty", style=discord.ButtonStyle.primary, custom_id="FormID3")
    async def off_duty_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(OffDutyLeaveModal())

    @discord.ui.button(label="Leave Details", style=discord.ButtonStyle.secondary, custom_id="FormID4")
    async def leave_details_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        result = await db.fetch_dynamic_user(interaction.user.id)
        if result:
            last_leave_taken, total_casual_leave, total_sick_leave = result
            await interaction.response.send_message(
                f"Last Accepted Leave Date: {last_leave_taken}\n"
                f"Total Casual Leave: {total_casual_leave}\n"
                f"Total Sick Leave: {total_sick_leave}",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message("No leave details found.", ephemeral=True)

    @discord.ui.button(label="Withdraw Leave", style=discord.ButtonStyle.danger, custom_id="FormID5")
    async def withdraw_leave_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WithdrawLeaveModal())


class DMLeaveActionView(discord.ui.View):
    def __init__(self, leave_id: int, stage: str, bot_ref=None):
        super().__init__(timeout=None)
        self.leave_id = leave_id
        self.stage = stage
        self._bot = bot_ref

        if stage == 'first':
            # Add Cancel button
            btn = discord.ui.Button(label="Cancel Leave", style=discord.ButtonStyle.danger, custom_id=f"cancel_leave_{leave_id}")
            btn.callback = self.cancel_leave
            self.add_item(btn)
        elif stage == 'second':
            # Add Request Withdraw button
            btn = discord.ui.Button(label="Request Withdraw", style=discord.ButtonStyle.danger, custom_id=f"req_withdraw_leave_{leave_id}")
            btn.callback = self.request_withdraw
            self.add_item(btn)

    async def cancel_leave(self, interaction: discord.Interaction):
        bot = self._bot or interaction.client
        guild = bot.guilds[0]
        member = guild.get_member(interaction.user.id)
        nickname = member.display_name if member else interaction.user.display_name
        
        leave_id = self.leave_id
        result = await db.get_pending_leave_status(nickname, leave_id)
        if result:
            leave_reason, number_of_days_off = result
            await db.withdraw_leave(nickname, leave_id)
            
            await interaction.response.send_message(f"Leave {leave_id} cancelled successfully.", ephemeral=True)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            
            try:
                footer = await db.get_footer_text(nickname, leave_id)
                if footer and footer[0]:
                    parts = footer[0].split(" | ")
                    channel_id = int(parts[3].split(": ")[1])
                    message_id = int(parts[4].split(": ")[1])
                    channel = bot.get_channel(channel_id)
                    if channel:
                        msg = await channel.fetch_message(message_id)
                        await msg.delete()
            except Exception as e:
                logging.error(f"[Leave] Error deleting pending leave embed: {e}")
        else:
            await interaction.response.send_message(f"Leave {leave_id} not found or is no longer pending.", ephemeral=True)

    async def request_withdraw(self, interaction: discord.Interaction):
        # Trigger the withdraw modal or process request
        leave_id = self.leave_id
        await interaction.response.send_message(f"Withdraw request sent for Leave ID {leave_id}. Please wait for HR processing.", ephemeral=True)
        # Real withdrawal logic handled in the main HR view, here we just notify.
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)


class ApprovedActionsView(View):
    def __init__(self, user_id, leave_details, nickname, bot_ref=None):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.leave_details = leave_details
        self.nickname = nickname
        self._bot = bot_ref

    @discord.ui.button(label="Withdraw", style=discord.ButtonStyle.danger, custom_id="withdraw_approved_leave")
    async def withdraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        leave_id = self.leave_details['leave_id']
        result = await db.get_leave_status(self.nickname, leave_id)
        if result:
            leave_reason, number_of_days_off = result
            await db.withdraw_leave(self.nickname, leave_id)
            await db.reduce_leave_balance(self.user_id, leave_reason.lower(), number_of_days_off)
            await db.update_last_leave_date_after_withdrawal(self.nickname, self.user_id)
            await interaction.response.send_message(f"Leave {leave_id} withdrawn.", ephemeral=True)
            for item in self.children:
                item.disabled = True
            await interaction.message.edit(view=self)
            
            # Message user about the HR withdrawal
            try:
                bot = self._bot or interaction.client
                user = await bot.fetch_user(self.user_id)
                await user.send(f"Your leave (ID: {leave_id}) has been formally withdrawn by HR/Management.")
            except Exception as e:
                pass
        else:
            await interaction.response.send_message(f"Leave {leave_id} not found or could not be withdrawn.", ephemeral=True)


class LeaveApprovalView(View):
    def __init__(self, user_id, leave_details, current_stage, nickname, bot_ref=None):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.leave_details = leave_details
        self.current_stage = current_stage
        self.nickname = nickname
        self._bot = bot_ref  # injected by LeaveCog so we can fetch channels/users

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, custom_id="accept_leave")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_approval(interaction, approved=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger, custom_id="decline_leave")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_approval(interaction, approved=False)

    async def handle_approval(self, interaction: discord.Interaction, approved: bool):
        bot = self._bot or interaction.client
        try:
            if approved:
                self.leave_details['approved_by'] = interaction.user.display_name
                await db.update_approval(self.nickname, self.leave_details['leave_id'], interaction.user.display_name)
                embed = create_leave_embed(self.leave_details, self.user_id, self.nickname, self.current_stage)
                if 'Approved By' not in [f.name for f in embed.fields]:
                    embed.add_field(name="Approved By", value=interaction.user.display_name, inline=False)

                if self.current_stage == 'first':
                    second_ch_id = APPROVAL_CHANNELS.get('hr')
                    for role_name, role_id in DIRECT_SECOND_APPROVAL_ROLES.items():
                        if role_id in [r.id for r in interaction.user.roles]:
                            second_ch_id = APPROVAL_CHANNELS.get(role_name)
                            break
                    second_ch = bot.get_channel(second_ch_id)
                    if not second_ch:
                        raise ValueError(f"Channel {second_ch_id} not found.")
                    msg = await second_ch.send(
                        embed=embed,
                        view=LeaveApprovalView(self.user_id, self.leave_details, 'second', self.nickname, bot_ref=bot),
                    )
                    new_footer = f"Stage: second | User ID: {self.user_id} | Nickname: {self.nickname} | Channel ID: {second_ch_id} | Message ID: {msg.id}"
                    embed.set_footer(text=new_footer)
                    await msg.edit(embed=embed)
                    await db.update_footer_text(self.nickname, self.leave_details['leave_id'], new_footer)
                    await interaction.message.edit(
                        content="Leave Approved",
                        view=View().add_item(Button(label="Approved", style=discord.ButtonStyle.success, disabled=True)),
                    )
                    await interaction.response.send_message("Leave approved and sent to next stage.", ephemeral=True)
                    user = await bot.fetch_user(self.user_id)
                    await user.send("Your leave has been recommended by your head of department to the HR.")

                elif self.current_stage == 'second':
                    await db.confirm_leave_acceptance(
                        self.nickname, self.leave_details['leave_id'],
                        self.leave_details.get('leave_reason', 'N/A').lower(),
                        self.leave_details.get('number_of_days_off', 0.0),
                        self.leave_details.get('date_to', self.leave_details.get('date_from', 'N/A')), self.user_id,
                    )
                    new_footer = f"Stage: third | User ID: {self.user_id} | Nickname: {self.nickname} | Channel ID: {APPROVAL_CHANNELS['pa']} | Message ID: {interaction.message.id}"
                    embed.set_footer(text=new_footer)
                    await interaction.message.edit(embed=embed)
                    await interaction.message.edit(
                        content="Leave Approved",
                        view=ApprovedActionsView(self.user_id, self.leave_details, self.nickname, bot_ref=bot),
                    )
                    await interaction.response.send_message("Leave approved and confirmed by HR.", ephemeral=True)
                    user = await bot.fetch_user(self.user_id)
                    await user.send("Your leave has been approved by the HR and has been confirmed.")

                elif self.current_stage == 'third':
                    await db.confirm_leave_acceptance(
                        self.nickname, self.leave_details['leave_id'],
                        self.leave_details.get('leave_reason', 'N/A').lower(),
                        self.leave_details.get('number_of_days_off', 0.0),
                        self.leave_details.get('date_to', self.leave_details.get('date_from', 'N/A')), self.user_id,
                    )
                    new_footer = f"Stage: final | User ID: {self.user_id} | Nickname: {self.nickname} | Channel ID: {APPROVAL_CHANNELS['pa']} | Message ID: {interaction.message.id}"
                    embed.set_footer(text=new_footer)
                    await interaction.message.edit(embed=embed)
                    await db.update_footer_text(self.nickname, self.leave_details['leave_id'], new_footer)
                    await interaction.message.edit(
                        content="Leave Approved",
                        view=ApprovedActionsView(self.user_id, self.leave_details, self.nickname, bot_ref=bot),
                    )
                    await interaction.response.send_message("Leave approved and confirmed by the Principal Architect.", ephemeral=True)
                    user = await bot.fetch_user(self.user_id)
                    await user.send("Your leave has been approved by the Principal Architect.")

            else:
                await interaction.response.send_modal(
                    DeclineReasonModal(self.user_id, self.leave_details, self.current_stage, self.nickname, bot_ref=bot)
                )

        except Exception as e:
            print(f"[Leave] handle_approval error: {e}")
            try:
                await interaction.followup.send("An error occurred while processing the approval.", ephemeral=True)
            except discord.errors.NotFound:
                pass


class DeclineReasonModal(Modal):
    def __init__(self, user_id, leave_details, current_stage, nickname, bot_ref=None):
        super().__init__(title="Reason for Decline")
        self.user_id = user_id
        self.leave_details = leave_details
        self.current_stage = current_stage
        self.nickname = nickname
        self._bot = bot_ref
        self.add_item(TextInput(label="Reason for Decline", style=discord.TextStyle.short, max_length=1024, placeholder="Enter the reason for decline"))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = self._bot or interaction.client
        try:
            reason = self.children[0].value.strip()
            self.leave_details['reason_for_decline'] = reason
            embed = create_leave_embed(self.leave_details, self.user_id, self.nickname, self.current_stage)
            embed.add_field(name="Declined By", value=interaction.user.display_name, inline=False)
            embed.add_field(name="Reason for Decline", value=reason, inline=False)

            await interaction.message.edit(
                content="Leave Declined",
                view=View().add_item(Button(label="Declined", style=discord.ButtonStyle.danger, disabled=True)),
            )
            await interaction.followup.send("Leave declined.", ephemeral=True)

            user = await bot.fetch_user(self.user_id)
            if self.current_stage == 'first':
                await user.send(f"Your leave has been declined by your HOD. Reason: {reason}.")
            elif self.current_stage == 'second':
                await user.send(f"Your leave has been declined by HR. Reason: {reason}.")
                pa_channel = bot.get_channel(APPROVAL_CHANNELS['pa'])
                if pa_channel:
                    await pa_channel.send(
                        embed=embed,
                        view=LeaveApprovalView(self.user_id, self.leave_details, 'third', self.nickname, bot_ref=bot),
                    )
            elif self.current_stage == 'third':
                await user.send(f"Your leave has been declined by the Principal Architect. Reason: {reason}.")

        except Exception as e:
            print(f"[Leave] DeclineReasonModal error: {e}")
            try:
                await interaction.followup.send("An error occurred while processing the decline.", ephemeral=True)
            except discord.errors.NotFound:
                pass


class WithdrawLeaveModal(Modal):
    def __init__(self):
        super().__init__(title="Withdraw Leave Application")
        self.add_item(TextInput(label="Leave ID", style=discord.TextStyle.short, max_length=10, placeholder="Enter Leave ID"))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            leave_id = int(self.children[0].value.strip())
            user_id = interaction.user.id
            nickname = interaction.user.display_name
            result = await db.get_leave_status(nickname, leave_id)
            if result:
                leave_reason, number_of_days_off = result
                dynamic_result = await db.check_leave_owner(nickname)
                if dynamic_result and dynamic_result[0] != user_id:
                    await interaction.response.send_message("You can only withdraw your own leave applications.", ephemeral=True)
                    return
                await db.withdraw_leave(nickname, leave_id)
                await db.reduce_leave_balance(user_id, leave_reason.lower(), number_of_days_off)
                await db.update_last_leave_date_after_withdrawal(nickname, user_id)
                await interaction.response.send_message(f"Leave {leave_id} has been withdrawn.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Leave {leave_id} not found or not accepted.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message("Invalid Leave ID.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)


class FullDayLeaveModal(Modal):
    def __init__(self):
        super().__init__(title="FULL DAY LEAVE APPLICATION")
        self.add_item(TextInput(label="LEAVE REASON", style=discord.TextStyle.short, max_length=10, placeholder="CASUAL / SICK / C. OFF"))
        self.add_item(TextInput(label="START DATE", style=discord.TextStyle.short, max_length=10, placeholder="DD-MM-YYYY"))
        self.add_item(TextInput(label="END DATE", style=discord.TextStyle.short, max_length=10, placeholder="DD-MM-YYYY"))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nickname = interaction.user.display_name
            leave_reason = self.children[0].value.strip().upper()
            date_from_str = self.children[1].value.strip().upper()
            date_to_str = self.children[2].value.strip().upper()

            if leave_reason not in ["CASUAL", "SICK", "C. OFF"]:
                await interaction.response.send_message("INVALID LEAVE REASON.", ephemeral=True, delete_after=15)
                return

            try:
                date_from = datetime.strptime(date_from_str, "%d-%m-%Y")
                date_to = datetime.strptime(date_to_str, "%d-%m-%Y")
            except ValueError:
                await interaction.response.send_message("INVALID DATE FORMAT. USE DD-MM-YYYY.", ephemeral=True, delete_after=15)
                return

            if date_from > date_to:
                await interaction.response.send_message("START DATE CANNOT BE AFTER END DATE.", ephemeral=True, delete_after=15)
                return

            # Calculate days off excluding Sundays (weekday() == 6)
            # Adjusting per usual standard that Sunday is a weekly off
            days_off = 0
            current_date = date_from
            while current_date <= date_to:
                if current_date.weekday() != 6:  # Skip Sundays
                    days_off += 1
                current_date += timedelta(days=1)
            
            number_of_days_off = float(days_off)

            # Next working day (Resume Office On)
            resume_date = date_to + timedelta(days=1)
            if resume_date.weekday() == 6:  # If resume date is Sunday, move to Monday
                resume_date += timedelta(days=1)
            
            resume_office_on = resume_date.strftime("%d-%m-%Y")

            leave_details = {
                'leave_type': 'FULL DAY', 'leave_reason': leave_reason,
                'date_from': date_from_str, 'date_to': date_to_str,
                'number_of_days_off': number_of_days_off, 'resume_office_on': resume_office_on,
            }
            
            await interaction.response.defer(ephemeral=True)
            
            data = (leave_details['leave_type'], leave_details['leave_reason'], date_from_str, date_to_str, number_of_days_off, resume_office_on, None, "PENDING", None)
            leave_id = await db.submit_leave_application(nickname, leave_details, data)
            leave_details['leave_id'] = leave_id
            await send_leave_application_to_approval_channel(interaction, leave_details, [r.id for r in interaction.user.roles])
            await interaction.followup.send(f"FULL DAY LEAVE SUBMITTED. LEAVE ID: {leave_id}\nResume Date: {resume_office_on} ({number_of_days_off} day(s))", ephemeral=True)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"AN ERROR OCCURRED: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"AN ERROR OCCURRED: {e}", ephemeral=True)


class HalfDayLeaveModal(Modal):
    def __init__(self):
        super().__init__(title="HALF DAY LEAVE APPLICATION")
        self.add_item(TextInput(label="LEAVE REASON", style=discord.TextStyle.short, max_length=10, placeholder="CASUAL / SICK / C. OFF"))
        self.add_item(TextInput(label="DATE", style=discord.TextStyle.short, max_length=1024, placeholder="DD-MM-YYYY"))
        self.add_item(TextInput(label="TIME PERIOD", style=discord.TextStyle.short, max_length=1024, placeholder="FORENOON/AFTERNOON"))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nickname = interaction.user.display_name
            leave_reason = self.children[0].value.strip().upper()
            date = self.children[1].value.strip().upper()
            time_period = self.children[2].value.strip().upper()

            if leave_reason not in ["CASUAL", "SICK", "C. OFF"]:
                await interaction.response.send_message("INVALID LEAVE REASON.", ephemeral=True)
                return
            try:
                datetime.strptime(date, "%d-%m-%Y")
            except ValueError:
                await interaction.response.send_message("INVALID DATE FORMAT.", ephemeral=True)
                return
            if time_period not in ["FORENOON", "AFTERNOON"]:
                await interaction.response.send_message("INVALID TIME PERIOD.", ephemeral=True)
                return

            leave_details = {
                'leave_type': 'HALF DAY', 'leave_reason': leave_reason,
                'date_from': date, 'date_to': None,
                'number_of_days_off': 0.5, 'resume_office_on': None, 'time_period': time_period,
            }
            
            await interaction.response.defer(ephemeral=True)
            
            data = (leave_details['leave_type'], leave_details['leave_reason'], date, None, 0.5, None, time_period, "PENDING", None)
            leave_id = await db.submit_leave_application(nickname, leave_details, data)
            leave_details['leave_id'] = leave_id
            await send_leave_application_to_approval_channel(interaction, leave_details, [r.id for r in interaction.user.roles])
            await interaction.followup.send(f"HALF DAY LEAVE SUBMITTED. LEAVE ID: {leave_id}", ephemeral=True)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"AN ERROR OCCURRED: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"AN ERROR OCCURRED: {e}", ephemeral=True)


class OffDutyLeaveModal(Modal):
    def __init__(self):
        super().__init__(title="OFF DUTY APPLICATION")
        self.add_item(TextInput(label="LEAVE REASON", style=discord.TextStyle.short, max_length=10, placeholder="CASUAL / SICK / C. OFF"))
        self.add_item(TextInput(label="DATE", style=discord.TextStyle.short, max_length=1024, placeholder="DD-MM-YYYY"))
        self.add_item(TextInput(label="TIME OFF", style=discord.TextStyle.short, max_length=1024, placeholder="HH-MM AM/PM TO HH-MM AM/PM"))
        self.add_item(TextInput(label="CUMULATED HOURS", style=discord.TextStyle.short, max_length=1024, placeholder="NO. OF HOURS"))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nickname = interaction.user.display_name
            user_id = interaction.user.id
            leave_reason = self.children[0].value.strip().upper()
            date = self.children[1].value.strip().upper()
            time_off = self.children[2].value.strip().upper()
            cumulated_hours_str = self.children[3].value.strip()

            if leave_reason not in ["CASUAL", "SICK", "C. OFF"]:
                await interaction.response.send_message("INVALID LEAVE REASON.", ephemeral=True)
                return
            try:
                datetime.strptime(date, "%d-%m-%Y")
            except ValueError:
                await interaction.response.send_message("INVALID DATE FORMAT.", ephemeral=True)
                return
            if not re.match(r'^\d{2}-\d{2} (AM|PM) TO \d{2}-\d{2} (AM|PM)$', time_off):
                await interaction.response.send_message("INVALID TIME OFF FORMAT.", ephemeral=True)
                return
            try:
                cumulated_hours = float(re.findall(r'\d+\.?\d*', cumulated_hours_str)[0])
            except (ValueError, IndexError):
                await interaction.response.send_message("INVALID CUMULATED HOURS.", ephemeral=True)
                return

            leave_details = {
                'leave_type': 'OFF DUTY', 'leave_reason': leave_reason,
                'date_from': date, 'date_to': None,
                'number_of_days_off': None, 'resume_office_on': None, 'time_off': time_off,
            }
            
            await interaction.response.defer(ephemeral=True)
            
            data = (leave_details['leave_type'], leave_details['leave_reason'], date, None, None, None, None, time_off, "PENDING", None)
            leave_id = await db.submit_leave_application(nickname, leave_details, data)
            leave_details['leave_id'] = leave_id
            await db.add_off_duty_hours(user_id, cumulated_hours)
            await send_leave_application_to_approval_channel(interaction, leave_details, [r.id for r in interaction.user.roles])
            await interaction.followup.send(f"OFF DUTY SUBMITTED. LEAVE ID: {leave_id}", ephemeral=True)
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"AN ERROR OCCURRED: {e}", ephemeral=True)
            else:
                await interaction.followup.send(f"AN ERROR OCCURRED: {e}", ephemeral=True)


async def send_leave_application_to_approval_channel(interaction, leave_details, user_roles):
    first_ch_id = None
    for role_name, role_id in DEPARTMENT_ROLES.items():
        if role_id in user_roles:
            first_ch_id = APPROVAL_CHANNELS[role_name]
            break
    for role_name, role_id in DIRECT_SECOND_APPROVAL_ROLES.items():
        if role_id in user_roles:
            first_ch_id = None
            break

    approval_ch_id = first_ch_id if first_ch_id else APPROVAL_CHANNELS['hr']
    bot = interaction.client
    channel = bot.get_channel(approval_ch_id)
    if channel is None:
        await interaction.followup.send(f"Error: approval channel {approval_ch_id} not found.", ephemeral=True)
        return

    current_stage = 'first' if first_ch_id else 'hr'
    view = LeaveApprovalView(interaction.user.id, leave_details, current_stage, interaction.user.display_name, bot_ref=bot)
    embed = create_leave_embed(leave_details, interaction.user.id, interaction.user.display_name, current_stage)
    message = await channel.send(embed=embed, view=view)
    footer_text = f"Stage: {current_stage} | User ID: {interaction.user.id} | Nickname: {interaction.user.display_name} | Channel ID: {approval_ch_id} | Message ID: {message.id}"
    embed.set_footer(text=footer_text)
    await message.edit(embed=embed)
    await db.update_footer_text(interaction.user.display_name, leave_details['leave_id'], footer_text)

    # Send DM to the user with Leave ID and Date
    try:
        user = await bot.fetch_user(interaction.user.id)
        date_display = leave_details.get('date_from', 'N/A')
        if leave_details.get('date_to'):
            date_display += f" TO {leave_details['date_to']}"
        dm_embed = discord.Embed(title="Leave Application Submitted", color=5810975)
        dm_embed.add_field(name="Leave ID", value=leave_details['leave_id'], inline=False)
        dm_embed.add_field(name="Date", value=date_display, inline=False)
        
        # Attach Cancel view for the first step
        dm_view = DMLeaveActionView(leave_details['leave_id'], 'first', bot_ref=bot)
        await user.send(embed=dm_embed, view=dm_view)
    except discord.Forbidden:
        logging.warning(f"Could not send DM to user {interaction.user.display_name}")


# ─── Cog ─────────────────────────────────────────────────────────────────────

class LeaveCog(commands.Cog, name="Leave"):
    """Handles leave applications and approvals."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Start the DB worker as soon as the cog is loaded."""
        asyncio.ensure_future(db.db_worker())

    @commands.Cog.listener()
    async def on_ready(self):
        guild = self.bot.guilds[0]
        emp_role = guild.get_role(EMP_ROLE_ID)
        await db.create_dynamic_table()
        for member in emp_role.members:
            await db.create_user_table(member.display_name)
            await db.insert_dynamic_user(member.display_name, member.id)

        # Create base styled embed for Leave app logic
        leave_embed = discord.Embed(
            title="🌴 Leave Management System",
            description="Welcome to the Concord Leave Center. Please select your leave type using the buttons below.",
            color=0x2ecc71
        )
        leave_embed.add_field(name="Full Day", value="Apply for a standard full day leave.", inline=True)
        leave_embed.add_field(name="Half Day", value="Apply for a forenoon or afternoon half-day leave.", inline=True)
        leave_embed.add_field(name="Off Duty", value="Apply for hourly off-duty time.", inline=True)
        leave_embed.add_field(name="Leave Details", value="View your current leave balances.", inline=False)
        leave_embed.add_field(name="Withdraw Leave", value="Withdraw a pending application.", inline=False)
        leave_embed.set_footer(text="Concord Unified Engine")

        # Reattach submit channel buttons
        submit_channel = self.bot.get_channel(SUBMIT_CHANNEL_ID)
        found_existing = False
        async for message in submit_channel.history(limit=10):
            if (
                message.author == self.bot.user
                and message.embeds
                and ("Leave Management System" in message.embeds[0].title or "Please select your leave type" in message.embeds[0].title)
            ):
                view = LeaveApplicationView()
                await asyncio.sleep(1)
                await message.edit(embed=leave_embed, view=view)
                logging.info("[Leave] Reattached view to existing message in submit channel.")
                found_existing = True
                break
        if not found_existing:
            view = LeaveApplicationView()
            await asyncio.sleep(1)
            await submit_channel.send(embed=leave_embed, view=view)
            logging.info("[Leave] Created new leave application message in submit channel.")

        # Reattach approval channel buttons
        for channel_id in set(APPROVAL_CHANNELS.values()):
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                continue
            async for message in channel.history(limit=50):
                if (
                    message.author == self.bot.user
                    and message.embeds
                    and "Leave Application" in message.embeds[0].title
                ):
                    if message.components and not any(btn.disabled for btn in message.components[0].children):
                        leave_details = extract_leave_details_from_embed(message.embeds[0])
                        footer_text = message.embeds[0].footer.text if message.embeds[0].footer else None
                        if footer_text:
                            parts = footer_text.split(" | ")
                            if len(parts) >= 5:
                                try:
                                    current_stage = parts[0].split(": ")[1]
                                    user_id = int(parts[1].split(": ")[1])
                                    nickname = parts[2].split(": ")[1]
                                    message_id = int(parts[4].split(": ")[1])
                                    view = LeaveApprovalView(user_id, leave_details, current_stage, nickname, bot_ref=self.bot)
                                    self.bot.add_view(view, message_id=message_id)
                                    print(f"[Leave] Reattached approval view for message {message_id} in channel {channel_id}.")
                                except (IndexError, ValueError) as e:
                                    print(f"[Leave] Footer parse error in channel {channel_id}: {e}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        before_roles = [r.id for r in before.roles]
        after_roles = [r.id for r in after.roles]
        if EMP_ROLE_ID in after_roles and EMP_ROLE_ID not in before_roles:
            await db.create_user_table(after.display_name)
            await db.insert_dynamic_user(after.display_name, after.id)
        elif EMP_ROLE_ID not in after_roles and EMP_ROLE_ID in before_roles:
            await db.delete_user_table(after.display_name)
            await db.remove_dynamic_user(after.id)

    @commands.command(name="export_leave")
    async def export_leave(self, ctx):
        """Exports current month's leave details to an Excel file."""
        try:
            export_directory = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Database', 'Leave details'))
            os.makedirs(export_directory, exist_ok=True)
            current_date = datetime.now().strftime("%d-%m-%Y")
            export_path = os.path.join(export_directory, f"leave_details_export_{current_date}.xlsx")
            start_of_month = datetime.now().replace(day=1).strftime("%d-%m-%Y")
            end_of_month = ((datetime.now().replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).strftime("%d-%m-%Y")

            tables = await db.get_all_tables()
            wb = Workbook()
            wb.remove(wb.active)

            for (table_name,) in tables:
                sheet_name = table_name[:31]
                df = await db.fetch_table_data(table_name, start_of_month, end_of_month)
                if df.empty:
                    continue
                ws = wb.create_sheet(title=sheet_name)
                for r_idx, row in enumerate(dataframe_to_rows(df, index=False, header=True), 1):
                    for c_idx, value in enumerate(row, 1):
                        cell = ws.cell(row=r_idx, column=c_idx, value=value)
                        if r_idx == 1:
                            cell.font = Font(bold=True)
                            cell.alignment = Alignment(horizontal='center', vertical='center')
                        else:
                            cell.alignment = Alignment(horizontal='left', vertical='center')
                tab = Table(
                    displayName=f"Table_{sheet_name}",
                    ref=f"A1:{ws.cell(row=ws.max_row, column=ws.max_column).coordinate}",
                )
                tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True, showColumnStripes=True)
                ws.add_table(tab)
                for col in ws.columns:
                    max_length = max((len(str(cell.value)) for cell in col if cell.value), default=0)
                    ws.column_dimensions[col[0].column_letter].width = max_length + 2

            if not wb.sheetnames:
                await ctx.send("No data available to export.")
                return
            wb.save(export_path)
            await ctx.send(f"Leave details exported to `{export_path}`")
        except Exception as e:
            await ctx.send(f"An error occurred: {e}")


async def setup(bot: commands.Bot):
    await bot.add_cog(LeaveCog(bot))

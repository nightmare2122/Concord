"""
cogs/leave_views.py — Leave Management UI Components
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.

Contains all Discord UI classes (Views, Modals) and helper functions
for the leave workflow. Config globals are accessed via the leave_config
module to always reflect the live post-startup values.
"""

import asyncio
import re
import logging
from datetime import timedelta

import discord
from discord.ui import Button, View, Modal, TextInput

from Bots.db_managers import leave_db_manager as db
from Bots.db_managers import discovery_db_manager as discovery
from Bots.utils.timezone import parse_date_flexible, parse_time_flexible

import cogs.leave_config as cfg

logger = logging.getLogger("Concord")


# ─── Embed helpers ────────────────────────────────────────────────────────────

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
    if leave_details.get('total_sick_leave') is not None or leave_details.get('total_casual_leave') is not None:
        sick = leave_details.get('total_sick_leave', 0) or 0
        casual = leave_details.get('total_casual_leave', 0) or 0
        c_off = leave_details.get('total_c_off', 0) or 0
        embed.add_field(
            name="Total Leaves Taken (Historical)",
            value=f"🤒 Sick: **{sick}** | 🌴 Casual: **{casual}** | 🔄 C-Off: **{c_off}**",
            inline=False
        )
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


# ─── Ephemeral helper ─────────────────────────────────────────────────────────

async def _send_ephemeral(interaction: discord.Interaction, content: str, delay: int = 10) -> None:
    """Send an ephemeral followup message and auto-delete it after `delay` seconds.

    ``interaction.followup.send`` returns a WebhookMessage whose id can be used
    with ``interaction.followup.delete_message`` — the only Discord-supported way
    to delete an ephemeral message sent via a followup.
    """
    msg = await interaction.followup.send(content, ephemeral=True)
    async def _del():
        await asyncio.sleep(delay)
        try:
            await interaction.followup.delete_message(msg.id)
        except Exception:
            pass
    asyncio.create_task(_del())


# ─── Application entry view ───────────────────────────────────────────────────

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
            last_leave_taken = result.get('last_leave_taken', 'N/A')
            total_casual_leave = result.get('total_casual_leave', 0)
            total_sick_leave = result.get('total_sick_leave', 0)

            await interaction.response.send_message(
                f"Last Accepted Leave Date: {last_leave_taken}\n"
                f"Total Casual Leave: {total_casual_leave}\n"
                f"Total Sick Leave: {total_sick_leave}",
                ephemeral=True,
                delete_after=10
            )
        else:
            await interaction.response.send_message("No leave details found.", ephemeral=True, delete_after=10)


# ─── Generic reason modal ─────────────────────────────────────────────────────

class ReasonModal(discord.ui.Modal):
    def __init__(self, title: str, label_text: str, callback_func):
        super().__init__(title=title)
        self.callback_func = callback_func
        self.add_item(discord.ui.TextInput(
            label=label_text,
            style=discord.TextStyle.paragraph,
            max_length=1024,
            placeholder="Please provide a reason...",
            required=True
        ))

    async def on_submit(self, interaction: discord.Interaction):
        reason = self.children[0].value.strip()
        await self.callback_func(interaction, reason)


# ─── DM action view (applicant) ───────────────────────────────────────────────

class DMLeaveActionView(discord.ui.View):
    def __init__(self, leave_id: int, stage: str, bot_ref=None):
        super().__init__(timeout=None)
        self.leave_id = leave_id
        self.stage = stage
        self._bot = bot_ref

        if stage in ('first', 'second'):
            # Direct cancellation available while pending HOD or HR approval
            btn = discord.ui.Button(label="Cancel Leave", style=discord.ButtonStyle.danger, custom_id=f"cancel_leave_{leave_id}")
            btn.callback = self.cancel_leave
            self.add_item(btn)
        elif stage == 'final':
            # After HR approval, user can only request a cancellation
            btn = discord.ui.Button(label="Request Cancellation", style=discord.ButtonStyle.secondary, custom_id=f"req_withdraw_leave_{leave_id}")
            btn.callback = self.request_withdraw
            self.add_item(btn)

    async def cancel_leave(self, interaction: discord.Interaction):
        async def cancel_callback(modal_interaction: discord.Interaction, reason: str):
            bot = self._bot or modal_interaction.client
            guild = bot.guilds[0]
            member = guild.get_member(modal_interaction.user.id)
            nickname = member.display_name if member else modal_interaction.user.display_name

            leave_id = self.leave_id
            result = await db.get_pending_leave_status(nickname, leave_id)
            if result:
                leave_reason = result['leave_reason']
                number_of_days_off = result['number_of_days_off']
                await db.withdraw_leave(nickname, leave_id, cancelled_by=nickname, cancellation_reason=reason)
                # Do not modify balance because it was only pending
                await db.update_last_leave_date_after_withdrawal(nickname, modal_interaction.user.id)

                await modal_interaction.response.send_message(f"Leave {leave_id} cancelled successfully.", ephemeral=True, delete_after=10)
                for item in self.children:
                    item.disabled = True

                embed = interaction.message.embeds[0] if interaction.message.embeds else None
                if embed:
                    for i, field in enumerate(embed.fields):
                        if field.name == "Status":
                            embed.set_field_at(i, name="Status", value="Cancelled", inline=False)
                            break
                    embed.add_field(name="Cancelled By", value=nickname, inline=True)
                    embed.add_field(name="Reason", value=reason, inline=True)

                await interaction.message.edit(view=self, embed=embed)

                try:
                    res = await db.get_footer_text(nickname, leave_id)
                    if res and res.get('footer_text'):
                        parts = res['footer_text'].split(" | ")
                        channel_id = int(parts[3].split(": ")[1])
                        message_id = int(parts[4].split(": ")[1])
                        channel = bot.get_channel(channel_id)
                        if channel:
                            msg = await channel.fetch_message(message_id)
                            await msg.delete()
                except Exception as e:
                    logger.error(f"[ERR-LV-006] [Leave] Error deleting pending leave embed: {e}")
            else:
                await modal_interaction.response.send_message(f"Leave {leave_id} not found or is no longer pending.", ephemeral=True, delete_after=10)

        await interaction.response.send_modal(ReasonModal("Cancel Leave", "Reason for Cancellation", cancel_callback))

    async def request_withdraw(self, interaction: discord.Interaction):
        async def withdraw_request_callback(modal_interaction: discord.Interaction, reason: str):
            try:
                await modal_interaction.response.defer(ephemeral=True)
                leave_id = self.leave_id
                bot = self._bot or modal_interaction.client

                logger.info(f"[Leave] Initiating withdraw_request_callback for Leave ID {leave_id}")

                guild = bot.guilds[0] if bot.guilds else None
                if not guild:
                    logger.error("[ERR-LV-007] [Leave] Bot is not in any guilds. Cannot process request.")
                    await _send_ephemeral(modal_interaction, "❌ Call [ERR-LV-008]: Bot connection error. Please try again later.")
                    return

                member = guild.get_member(modal_interaction.user.id)
                nickname = member.display_name if member else modal_interaction.user.display_name
                logger.info(f"[Leave] User: {nickname} (ID: {modal_interaction.user.id})")

                # Update DB status
                await db.request_withdraw_leave(nickname, leave_id, requested_by=nickname, reason=reason)
                logger.info(f"[Leave] DB updated to 'Withdrawal Requested' for ID {leave_id}")

                # Update local message
                for item in self.children:
                    item.disabled = True
                embed = interaction.message.embeds[0] if interaction.message.embeds else discord.Embed(title="Leave Application Status")

                # Update Status field if it exists
                status_updated = False
                for i, field in enumerate(embed.fields):
                    if field.name == "Status":
                        embed.set_field_at(i, name="Status", value="⏳ Cancellation Requested — awaiting HR approval", inline=False)
                        status_updated = True
                        break
                if not status_updated:
                    embed.add_field(name="Status", value="⏳ Cancellation Requested — awaiting HR approval", inline=False)

                embed.add_field(name="Reason", value=reason, inline=False)
                await interaction.message.edit(view=self, embed=embed)
                logger.info(f"[Leave] Local DM message updated for ID {leave_id}")

                await _send_ephemeral(modal_interaction, f"Cancellation request sent for Leave ID {leave_id}. HR will review it shortly.")

                # Resolve HR Channel
                hr_ch_id = cfg.APPROVAL_CHANNELS.get('hr')
                if not hr_ch_id:
                    logger.error("[ERR-LV-009] [Leave] HR Channel ID not found in APPROVAL_CHANNELS config.")
                    await _send_ephemeral(modal_interaction, "❌ Call [ERR-LV-010]: Configuration error: HR channel not set.")
                    return

                logger.info(f"[Leave] Resolving HR Channel ID: {hr_ch_id}")
                hr_channel = bot.get_channel(int(hr_ch_id))
                if not hr_channel:
                    try:
                        logger.info(f"[Leave] Channel not in cache, fetching ID: {hr_ch_id}")
                        hr_channel = await bot.fetch_channel(int(hr_ch_id))
                    except Exception as fe:
                        logger.error(f"[ERR-LV-011] [Leave] Failed to fetch channel {hr_ch_id}: {fe}")
                        hr_channel = None

                if hr_channel:
                    res = await db.get_footer_text(nickname, leave_id)
                    footer_text = res['footer_text'] if res and res.get('footer_text') else ""

                    leave_row = await db.get_leave_full_details(nickname, leave_id)

                    cancel_embed = discord.Embed(
                        title="📥 Cancellation Request",
                        description=f"**{nickname}** has requested cancellation of an approved leave.",
                        color=0xF39C12
                    )
                    cancel_embed.add_field(name="Leave ID",   value=leave_id,  inline=True)
                    cancel_embed.add_field(name="Member",     value=nickname,  inline=True)
                    cancel_embed.add_field(name="\u200b",      value="\u200b",  inline=True)

                    if leave_row:
                        leave_type = leave_row.get('leave_type') or leave_row.get('leave_reason') or 'N/A'
                        date_from  = leave_row.get('date_from', 'N/A')
                        date_to    = leave_row.get('date_to') or date_from
                        days_off   = leave_row.get('number_of_days_off', 'N/A')
                        cancel_embed.add_field(name="Leave Type",  value=leave_type,                inline=True)
                        cancel_embed.add_field(name="Dates",       value=f"{date_from} → {date_to}", inline=True)
                        cancel_embed.add_field(name="Days Off",    value=days_off,                  inline=True)
                        cancel_embed.add_field(name="Reason",      value=reason,                    inline=False)

                    cancel_embed.set_footer(text=f"User ID: {modal_interaction.user.id} | Leave ID: {leave_id}")

                    cancel_view = CancellationRequestView(
                        user_id=modal_interaction.user.id,
                        leave_id=leave_id,
                        nickname=nickname,
                        footer_text=footer_text,
                        bot_ref=bot
                    )
                    await hr_channel.send(embed=cancel_embed, view=cancel_view)
                    logger.info(f"[Leave] Cancellation request sent to HR channel for ID {leave_id}")
                else:
                    logger.error(f"[ERR-LV-012] [Leave] HR channel {hr_ch_id} could not be resolved. Notification NOT sent.")
                    await _send_ephemeral(modal_interaction, "⚠️ Call [ERR-LV-013]: Request recorded, but HR notification failed. Please inform HR manually.")

            except Exception as e:
                logger.exception(f"[ERR-LV-014] [Leave] Fatal error in withdraw_request_callback: {e}")
                await _send_ephemeral(modal_interaction, "❌ Call [ERR-LV-015]: A system error occurred while processing your cancellation request.")

        await interaction.response.send_modal(ReasonModal("Request Cancellation", "Reason for Cancellation", withdraw_request_callback))


# ─── HR cancellation request view ────────────────────────────────────────────

class CancellationRequestView(View):
    """Shown in the HR channel when a user requests cancellation of an HR-approved leave."""
    def __init__(self, user_id, leave_id, nickname, footer_text, bot_ref=None):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.leave_id = leave_id
        self.nickname = nickname
        self.footer_text = footer_text
        self._bot = bot_ref

    @staticmethod
    async def _auto_delete_ephemeral(interaction: discord.Interaction, delay: int = 10):
        """Delete the ephemeral response after `delay` seconds using the only supported method."""
        await asyncio.sleep(delay)
        try:
            await interaction.delete_original_response()
        except Exception:
            pass

    @discord.ui.button(label="Approve Cancellation", style=discord.ButtonStyle.success, custom_id="cancel_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        bot = self._bot or interaction.client
        try:
            leave_row = await db.get_leave_full_details(self.nickname, self.leave_id)
            if leave_row:
                leave_reason = leave_row.get('leave_reason', 'N/A')
                days_off = leave_row.get('number_of_days_off', 0.0)

                # Fetch existing cancellation details if they exist to pass through
                existing_cancelled_by = leave_row.get('cancelled_by')
                existing_reason = leave_row.get('cancellation_reason')

                await db.withdraw_leave(self.nickname, self.leave_id, cancelled_by=existing_cancelled_by, cancellation_reason=existing_reason)
                await db.refund_leave_balance(self.user_id, leave_reason.lower(), days_off)
                await db.update_last_leave_date_after_withdrawal(self.nickname, self.user_id)

            # Update the original HR approval message to show Cancelled status
            try:
                if self.footer_text and "Message ID: " in self.footer_text:
                    msg_id_str = self.footer_text.split("Message ID: ")[1].split(" | ")[0].strip()
                    orig_msg_id = int(msg_id_str)
                    hr_channel = bot.get_channel(cfg.APPROVAL_CHANNELS.get('hr'))
                    if hr_channel:
                        try:
                            orig_msg = await hr_channel.fetch_message(orig_msg_id)
                            orig_embed = orig_msg.embeds[0] if orig_msg.embeds else discord.Embed()
                            orig_embed.color = 0xE74C3C
                            updated = False
                            for i, field in enumerate(orig_embed.fields):
                                if field.name in ("Status", "Approved By"):
                                    orig_embed.set_field_at(i, name="Status", value="❌ Cancelled by HR", inline=field.inline)
                                    updated = True
                                    break
                            if not updated:
                                orig_embed.add_field(name="Status", value="❌ Cancelled by HR", inline=False)
                            await orig_msg.edit(
                                content="Leave Cancelled",
                                embed=orig_embed,
                                view=View().add_item(Button(label="Cancelled", style=discord.ButtonStyle.danger, disabled=True))
                            )
                        except discord.NotFound:
                            pass
            except Exception as e:
                logger.error(f"[ERR-LV-016] [Leave] Could not update original HR message after cancellation: {e}")

            # Notify user via DM
            await update_persistent_dm(
                bot, self.user_id,
                {'leave_id': self.leave_id, 'date_from': '', 'date_to': ''},
                'final', self.footer_text,
                status_msg="❌ Leave cancelled — approved by HR.",
                color=0xE74C3C
            )

            # Send ephemeral confirmation then delete the cancellation request card
            await _send_ephemeral(interaction, "✅ Cancellation approved.")
            asyncio.create_task(self._auto_delete_ephemeral(interaction))
            await interaction.message.delete()

        except Exception as e:
            logger.error(f"[ERR-LV-017] [Leave] CancellationRequestView approve error: {e}")
            await _send_ephemeral(interaction, "An error occurred [ERR-LV-018].")

    @discord.ui.button(label="Reject Cancellation", style=discord.ButtonStyle.danger, custom_id="cancel_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        bot = self._bot or interaction.client
        try:
            await db.revert_cancellation_request(self.nickname, self.leave_id)

            # Notify user via DM — leave remains active
            await update_persistent_dm(
                bot, self.user_id,
                {'leave_id': self.leave_id, 'date_from': '', 'date_to': ''},
                'final', self.footer_text,
                status_msg="✅ Cancellation rejected by HR — leave remains approved.",
                color=0x2ecc71
            )

            # Send ephemeral confirmation then delete the cancellation request card
            await _send_ephemeral(interaction, "❌ Cancellation rejected.")
            asyncio.create_task(self._auto_delete_ephemeral(interaction))
            await interaction.message.delete()

        except Exception as e:
            logger.error(f"[ERR-LV-019] [Leave] CancellationRequestView reject error: {e}")
            await _send_ephemeral(interaction, "An error occurred [ERR-LV-020].")


# ─── Post-approval actions view (applicant) ───────────────────────────────────

class ApprovedActionsView(View):
    def __init__(self, user_id, leave_details, nickname, bot_ref=None):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.leave_details = leave_details
        self.nickname = nickname
        self._bot = bot_ref

    @discord.ui.button(label="Withdraw", style=discord.ButtonStyle.danger, custom_id="withdraw_approved_leave")
    async def withdraw_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        async def hr_withdraw_callback(modal_interaction: discord.Interaction, reason: str):
            leave_id = self.leave_details['leave_id']
            result = await db.get_leave_status(self.nickname, leave_id)
            if result:
                leave_reason = result['leave_reason']
                number_of_days_off = result['number_of_days_off']
                hr_nickname = modal_interaction.user.display_name
                await db.withdraw_leave(self.nickname, leave_id, cancelled_by=f"HR ({hr_nickname})", cancellation_reason=reason)
                if leave_reason:
                    await db.refund_leave_balance(self.user_id, leave_reason.lower(), number_of_days_off)
                await db.update_last_leave_date_after_withdrawal(self.nickname, self.user_id)
                await modal_interaction.response.send_message(f"Leave {leave_id} withdrawn.", ephemeral=True, delete_after=10)
                for item in self.children:
                    item.disabled = True

                embed = interaction.message.embeds[0] if interaction.message.embeds else None
                if embed:
                    embed.add_field(name="Cancelled By", value=f"HR ({hr_nickname})", inline=True)
                    embed.add_field(name="Reason", value=reason, inline=True)

                await interaction.message.edit(view=self, embed=embed)

                # Message user about the HR withdrawal
                try:
                    bot = self._bot or modal_interaction.client
                    res = await db.get_footer_text(self.nickname, leave_id)
                    if res and res.get('footer_text'):
                        await update_persistent_dm(bot, self.user_id, self.leave_details, 'final', res['footer_text'], status_msg=f"Your leave has been formally withdrawn by HR/Management.\nReason: {reason}", color=0xE74C3C)
                    else:
                        user = await bot.fetch_user(self.user_id)
                        await user.send(f"Your leave (ID: {leave_id}) has been formally withdrawn by HR/Management.\nReason: {reason}")
                except Exception as e:
                    logger.error(f"[ERR-LV-021] [Leave] Error updating DM on HR withdrawal: {e}")
            else:
                await modal_interaction.response.send_message(f"Leave {leave_id} not found or could not be withdrawn.", ephemeral=True, delete_after=10)

        await interaction.response.send_modal(ReasonModal("Withdraw Leave", "Reason for Withdrawal", hr_withdraw_callback))


# ─── HOD / HR approval view ───────────────────────────────────────────────────

class LeaveApprovalView(View):
    def __init__(self, user_id, leave_details, current_stage, nickname, bot_ref=None):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.leave_details = leave_details
        self.current_stage = current_stage
        self.nickname = nickname
        self._bot = bot_ref

    async def _is_withdrawal_requested(self):
        try:
            result = await db.get_pending_leave_status(self.nickname, self.leave_details['leave_id'])
            if not result:
                leave = await db.get_leave_full_details(self.nickname, self.leave_details['leave_id'])
                if leave and leave.get('leave_status') == 'Withdrawal Requested':
                    return True
            return False
        except Exception as e:
            logger.error(f"[ERR-LV-022] [Leave] Error checking withdrawal request status: {e}")
            return False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Validate interaction. Dispatching is handled by item callbacks, not here."""
        return True

    async def _ensure_buttons_attached(self, interaction: discord.Interaction):
        # Empty children and rebuild based on state
        self.clear_items()
        is_withdrawal = await self._is_withdrawal_requested()

        if is_withdrawal:
            self.add_item(Button(label="Requested to Withdraw", style=discord.ButtonStyle.danger, custom_id=f"hr_withdraw_{self.leave_details['leave_id']}"))
        else:
            self.add_item(Button(label="Accept", style=discord.ButtonStyle.success, custom_id=f"hr_accept_{self.leave_details['leave_id']}"))
            self.add_item(Button(label="Decline", style=discord.ButtonStyle.danger, custom_id=f"hr_decline_{self.leave_details['leave_id']}"))

        # Re-bind callbacks because dynamic buttons drop their decorators when manually added
        for item in self.children:
            if item.custom_id and item.custom_id.startswith('hr_withdraw_'):
                item.callback = self.handle_hr_withdrawal
            elif item.custom_id and item.custom_id.startswith('hr_accept_'):
                item.callback = self.handle_hr_accept_with_notes
            elif item.custom_id and item.custom_id.startswith('hr_decline_'):
                item.callback = self.handle_hr_decline

    async def handle_hr_accept(self, interaction: discord.Interaction):
        await self.handle_approval(interaction, True)

    async def handle_hr_accept_with_notes(self, interaction: discord.Interaction):
        """Opens a modal for optional notes before approving."""
        modal = ApproveWithNotesModal(self, interaction, interaction.user.display_name)
        await interaction.response.send_modal(modal)

    async def handle_hr_decline(self, interaction: discord.Interaction):
        modal = DeclineReasonModal(self.user_id, self.leave_details, self.current_stage, self.nickname, bot_ref=self._bot)
        await interaction.response.send_modal(modal)

    async def handle_hr_withdrawal(self, interaction: discord.Interaction):
        leave_id = self.leave_details['leave_id']
        bot = self._bot or interaction.client

        # Confirm withdrawal in DB
        await db.confirm_withdraw_leave(self.nickname, leave_id)

        # Re-fetch exact leave so we can decrement balance
        try:
            res = await db.get_leave_full_details(self.nickname, leave_id)
            if res:
                leave_reason = res.get('leave_reason')
                number_of_days_off = res.get('number_of_days_off')
                if number_of_days_off is not None and leave_reason:
                    await db.refund_leave_balance(self.user_id, leave_reason.lower(), number_of_days_off)
        except Exception as e:
            logger.error(f"[ERR-LV-023] [Leave] Error fetching withdrawn leave details: {e}")

        for item in self.children:
            item.disabled = True

        embed = interaction.message.embeds[0] if interaction.message.embeds else None
        if embed:
            for i, field in enumerate(embed.fields):
                if field.name == "Status":
                    embed.set_field_at(i, name="Status", value="Withdrawn by HR", inline=False)
                    break

        await interaction.message.edit(content="Leave Withdrawn", embed=embed, view=self)
        await interaction.response.send_message("Leave explicitly withdrawn.", ephemeral=True, delete_after=10)

        # Update persistent DM
        try:
            res = await db.get_footer_text(self.nickname, leave_id)
            if res and res.get('footer_text'):
                await update_persistent_dm(bot, self.user_id, self.leave_details, 'final', res['footer_text'], status_msg="Your leave has been formally withdrawn by HR/Management.", color=0xE74C3C)
        except Exception as e:
            logger.error(f"[ERR-LV-024] [Leave] Error updating DM after HR withdrawal: {e}")

    async def handle_approval(self, interaction: discord.Interaction, approved: bool):
        bot = self._bot or interaction.client
        try:
            await interaction.response.defer(ephemeral=True)
            if approved:
                self.leave_details['approved_by'] = interaction.user.display_name
                await db.update_approval(self.nickname, self.leave_details['leave_id'], interaction.user.display_name)
                embed = create_leave_embed(self.leave_details, self.user_id, self.nickname, self.current_stage)
                if 'Approved By' not in [f.name for f in embed.fields]:
                    embed.add_field(name="Approved By", value=interaction.user.display_name, inline=False)
                approval_notes = self.leave_details.get('approval_notes', '')
                if approval_notes:
                    if 'Approval Notes' not in [f.name for f in embed.fields]:
                        embed.add_field(name="Approval Notes", value=approval_notes, inline=False)

                if self.current_stage == 'first':
                    second_ch_id = cfg.APPROVAL_CHANNELS.get('hr')
                    second_ch_key = 'hr'
                    for role_name, role_id in cfg.DIRECT_SECOND_APPROVAL_ROLES.items():
                        if role_id in [r.id for r in interaction.user.roles]:
                            second_ch_id = cfg.APPROVAL_CHANNELS.get(role_name)
                            second_ch_key = role_name
                            break
                    second_ch = bot.get_channel(second_ch_id)
                    if not second_ch:
                        ch_name = cfg._APPROVAL_CHANNEL_NAMES.get(second_ch_key, "leave-hr")
                        guild = interaction.guild
                        category = discord.utils.get(guild.categories, name="Leave Applications") or discord.utils.get(guild.categories, name="Leave applications")
                        bot_role = guild.me.top_role
                        overwrites = {
                            guild.default_role: discord.PermissionOverwrite(read_messages=False),
                            bot_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                        }
                        second_ch = await guild.create_text_channel(ch_name, category=category, overwrites=overwrites)
                        cfg.APPROVAL_CHANNELS[second_ch_key] = second_ch.id
                        await discovery.upsert_channel(second_ch.id, second_ch.name, 'text', category.id if category else 0)
                        logging.getLogger("Concord").warning(f"[Leave] Auto-created missing approval channel #{ch_name}.")

                    next_view = LeaveApprovalView(self.user_id, self.leave_details, 'second', self.nickname, bot_ref=bot)
                    await next_view._ensure_buttons_attached(interaction)

                    msg = await second_ch.send(
                        embed=embed,
                        view=next_view,
                    )
                    # Carry forward the DM ID when moving to stage 2
                    existing_footer = interaction.message.embeds[0].footer.text if interaction.message.embeds else ""
                    dm_id_part = ""
                    if existing_footer and "DM ID: " in existing_footer:
                        dm_id_part = " | DM ID: " + existing_footer.split("DM ID: ")[1].split(" | ")[0].strip()
                    new_footer = f"Stage: second | User ID: {self.user_id} | Nickname: {self.nickname} | Channel ID: {second_ch_id} | Message ID: {msg.id}{dm_id_part}"
                    embed.set_footer(text=new_footer)
                    await msg.edit(embed=embed)
                    await db.update_footer_text(self.nickname, self.leave_details['leave_id'], new_footer)
                    await interaction.message.edit(
                        content="Leave Approved",
                        view=View().add_item(Button(label="Approved", style=discord.ButtonStyle.success, disabled=True)),
                    )
                    await _send_ephemeral(interaction, "Leave approved and sent to next stage.")
                    await update_persistent_dm(bot, self.user_id, self.leave_details, 'second', new_footer, status_msg="Recommended by HOD, pending HR approval.")

                elif self.current_stage == 'second':
                    # HR is the final approver — mark leave as fully approved
                    await db.confirm_leave_acceptance(
                        self.nickname, self.leave_details['leave_id'],
                        self.leave_details.get('leave_reason', 'N/A').lower(),
                        self.leave_details.get('number_of_days_off', 0.0),
                        self.leave_details.get('date_to', self.leave_details.get('date_from', 'N/A')), self.user_id,
                    )
                    # Carry forward the DM ID from the existing footer
                    existing_footer = interaction.message.embeds[0].footer.text if interaction.message.embeds else ""
                    dm_id_part = ""
                    if existing_footer and "DM ID: " in existing_footer:
                        dm_id_part = " | DM ID: " + existing_footer.split("DM ID: ")[1].split(" | ")[0].strip()
                    new_footer = f"Stage: final | User ID: {self.user_id} | Nickname: {self.nickname} | Message ID: {interaction.message.id}{dm_id_part}"
                    embed.set_footer(text=new_footer)
                    await db.update_footer_text(self.nickname, self.leave_details['leave_id'], new_footer)

                    await interaction.message.edit(
                        content="Leave Fully Approved by HR",
                        embed=embed,
                        view=View().add_item(Button(label="Approved", style=discord.ButtonStyle.success, disabled=True)),
                    )
                    await _send_ephemeral(interaction, "Leave approved and finalized.")
                    await update_persistent_dm(bot, self.user_id, self.leave_details, 'final', new_footer, status_msg="✅ Fully Approved by HR.", color=0x2ecc71)

            else:
                await _send_ephemeral(interaction, "Please use the Decline button to provide a reason.")

        except Exception as e:
            logger.exception(f"[ERR-LV-025] [Leave] handle_approval error: {e}")
            try:
                await _send_ephemeral(interaction, "Call [ERR-LV-026]: An error occurred while processing the approval.")
            except discord.errors.NotFound:
                pass


# ─── Approval / decline modals ────────────────────────────────────────────────

class ApproveWithNotesModal(Modal):
    def __init__(self, view_ref, interaction_ref, approved_by_name):
        super().__init__(title="Approve Leave Application")
        self._view = view_ref
        self._original_interaction = interaction_ref
        self._approved_by_name = approved_by_name
        self.add_item(TextInput(label="Notes (optional)", style=discord.TextStyle.paragraph, max_length=1024, placeholder="Any notes for the applicant or next approver...", required=False))

    async def on_submit(self, interaction: discord.Interaction):
        notes = self.children[0].value.strip() if self.children[0].value else ""
        if notes:
            self._view.leave_details['approval_notes'] = notes
        await self._view.handle_approval(interaction, True)


class DeclineReasonModal(Modal):
    def __init__(self, user_id, leave_details, current_stage, nickname, bot_ref=None):
        super().__init__(title="Reason for Decline")
        self.user_id = user_id
        self.leave_details = leave_details
        self.current_stage = current_stage
        self.nickname = nickname
        self._bot = bot_ref
        self.add_item(TextInput(label="Reason for Decline", style=discord.TextStyle.short, max_length=1024, placeholder="Enter the reason for decline"))
        self.add_item(TextInput(label="Notes (optional)", style=discord.TextStyle.paragraph, max_length=1024, placeholder="Any additional notes for the applicant...", required=False))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = self._bot or interaction.client
        try:
            reason = self.children[0].value.strip()
            notes = self.children[1].value.strip() if self.children[1].value else ""
            self.leave_details['reason_for_decline'] = reason
            embed = create_leave_embed(self.leave_details, self.user_id, self.nickname, self.current_stage)
            embed.add_field(name="Declined By", value=interaction.user.display_name, inline=False)
            embed.add_field(name="Reason for Decline", value=reason, inline=False)
            if notes:
                embed.add_field(name="Notes", value=notes, inline=False)

            await interaction.message.edit(
                content="Leave Declined",
                view=View().add_item(Button(label="Declined", style=discord.ButtonStyle.danger, disabled=True)),
            )
            await _send_ephemeral(interaction, "Leave declined.")

            footer = await db.get_footer_text(self.nickname, self.leave_details['leave_id'])
            footer_text_str = footer[0] if footer else ""

            notes_suffix = f"\nNotes: {notes}" if notes else ""
            if self.current_stage == 'first':
                await db.deny_leave(self.nickname, self.leave_details['leave_id'])
                await update_persistent_dm(bot, self.user_id, self.leave_details, 'final', footer_text_str, status_msg=f"Declined by HOD. Reason: {reason}{notes_suffix}", color=0xE74C3C)
            elif self.current_stage == 'second':
                # HR declined — mark leave denied and notify PA channel
                await db.deny_leave(self.nickname, self.leave_details['leave_id'])
                await update_persistent_dm(bot, self.user_id, self.leave_details, 'final', footer_text_str, status_msg=f"Declined by HR. Reason: {reason}{notes_suffix}", color=0xE74C3C)
                pa_channel = bot.get_channel(cfg.APPROVAL_CHANNELS['pa'])
                if pa_channel:
                    notification_embed = create_leave_embed(self.leave_details, self.user_id, self.nickname, self.current_stage)
                    notification_embed.color = 0xE74C3C
                    notification_embed.add_field(name="Declined By (HR)", value=interaction.user.display_name, inline=False)
                    notification_embed.add_field(name="Reason", value=reason, inline=False)
                    notification_embed.set_footer(text="This is a notification only. No action required.")
                    await pa_channel.send(content="📋 Leave request declined at HR level.", embed=notification_embed)

        except Exception as e:
            print(f"[Leave] DeclineReasonModal error: {e}")
            try:
                await _send_ephemeral(interaction, "Call [ERR-LV-027]: An error occurred while processing the decline.")
            except discord.errors.NotFound:
                pass


# ─── Application modals ───────────────────────────────────────────────────────

class WithdrawLeaveModal(Modal):
    def __init__(self):
        super().__init__(title="Withdraw Leave Application")
        self.add_item(discord.ui.TextInput(label="Leave ID", style=discord.TextStyle.short, max_length=10, placeholder="Enter Leave ID"))
        self.add_item(discord.ui.TextInput(label="Reason for Withdrawal", style=discord.TextStyle.paragraph, max_length=1024, placeholder="Required reason...", required=True))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            leave_id = int(self.children[0].value.strip())
            reason = self.children[1].value.strip()
            user_id = interaction.user.id
            nickname = interaction.user.display_name
            result = await db.get_leave_status(nickname, leave_id)
            if result:
                leave_reason = result['leave_reason']
                number_of_days_off = result['number_of_days_off']
                dynamic_result = await db.check_leave_owner(nickname)
                if dynamic_result and dynamic_result['user_id'] != user_id:
                    await interaction.response.send_message("You can only withdraw your own leave applications.", ephemeral=True, delete_after=10)
                await db.withdraw_leave(nickname, leave_id, cancelled_by=nickname, cancellation_reason=reason)
                await db.refund_leave_balance(user_id, leave_reason.lower(), number_of_days_off)
                await db.update_last_leave_date_after_withdrawal(nickname, user_id)
                await interaction.response.send_message(f"Leave {leave_id} has been withdrawn.\nReason: {reason}", ephemeral=True, delete_after=10)
            else:
                await interaction.response.send_message(f"Leave {leave_id} not found or not accepted.", ephemeral=True, delete_after=10)
        except ValueError:
            await interaction.response.send_message("Invalid Leave ID.", ephemeral=True, delete_after=10)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True, delete_after=10)


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
                await interaction.response.send_message("INVALID LEAVE REASON.", ephemeral=True, delete_after=10)
                return

            try:
                date_from, date_from_str = parse_date_flexible(date_from_str)
                date_to, date_to_str = parse_date_flexible(date_to_str)
            except ValueError as e:
                await interaction.response.send_message(f"INVALID DATE. {e}", ephemeral=True, delete_after=10)
                return

            if date_from > date_to:
                await interaction.response.send_message("START DATE CANNOT BE AFTER END DATE.", ephemeral=True, delete_after=10)
                return

            # Calculate days off excluding Sundays AND national holidays
            days_off = 0
            current_date = date_from
            while current_date <= date_to:
                date_check = current_date.strftime("%d-%m-%Y")
                is_hol = await db.is_holiday(date_check)
                if current_date.weekday() != 6 and not is_hol:  # Skip Sundays & holidays
                    days_off += 1
                current_date += timedelta(days=1)

            number_of_days_off = float(days_off)

            # Next working day (Resume Office On) — skip Sundays and holidays
            resume_date = date_to + timedelta(days=1)
            while True:
                resume_check = resume_date.strftime("%d-%m-%Y")
                is_resume_hol = await db.is_holiday(resume_check)
                if resume_date.weekday() != 6 and not is_resume_hol:
                    break
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
            await _send_ephemeral(interaction, f"FULL DAY LEAVE SUBMITTED. LEAVE ID: {leave_id}\nResume Date: {resume_office_on} ({number_of_days_off} day(s))")
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"AN ERROR OCCURRED: {e}", ephemeral=True, delete_after=10)
            else:
                await _send_ephemeral(interaction, f"Call [ERR-LV-028] AN ERROR OCCURRED: {e}")


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
                await interaction.response.send_message("INVALID LEAVE REASON.", ephemeral=True, delete_after=10)
                return
            try:
                _, date = parse_date_flexible(date)
            except ValueError as e:
                await interaction.response.send_message(f"INVALID DATE. {e}", ephemeral=True, delete_after=10)
                return
            if time_period not in ["FORENOON", "AFTERNOON"]:
                await interaction.response.send_message("INVALID TIME PERIOD.", ephemeral=True, delete_after=10)
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
            await _send_ephemeral(interaction, f"HALF DAY LEAVE SUBMITTED. LEAVE ID: {leave_id}")
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"AN ERROR OCCURRED: {e}", ephemeral=True, delete_after=10)
            else:
                await _send_ephemeral(interaction, f"Call [ERR-LV-029] AN ERROR OCCURRED: {e}")


class OffDutyLeaveModal(Modal):
    def __init__(self):
        super().__init__(title="OFF DUTY APPLICATION")
        self.add_item(TextInput(label="LEAVE REASON", style=discord.TextStyle.short, max_length=10, placeholder="CASUAL / SICK / C. OFF"))
        self.add_item(TextInput(label="DATE", style=discord.TextStyle.short, max_length=10, placeholder="DD-MM-YYYY  e.g. 27-03-2026"))
        self.add_item(TextInput(label="TIME FROM", style=discord.TextStyle.short, max_length=8, placeholder="HH:MM AM/PM  e.g. 09:30 AM"))
        self.add_item(TextInput(label="TIME TO", style=discord.TextStyle.short, max_length=8, placeholder="HH:MM AM/PM  e.g. 05:30 PM"))
        self.add_item(TextInput(label="CUMULATED HOURS", style=discord.TextStyle.short, max_length=10, placeholder="NO. OF HOURS"))

    async def on_submit(self, interaction: discord.Interaction):
        try:
            nickname = interaction.user.display_name
            user_id = interaction.user.id
            leave_reason = self.children[0].value.strip().upper()
            date = self.children[1].value.strip().upper()
            time_from = self.children[2].value.strip().upper()
            time_to = self.children[3].value.strip().upper()
            time_off = f"{time_from} TO {time_to}"
            cumulated_hours_str = self.children[4].value.strip()

            if leave_reason not in ["CASUAL", "SICK", "C. OFF"]:
                await interaction.response.send_message("INVALID LEAVE REASON.", ephemeral=True, delete_after=10)
                return
            try:
                _, date = parse_date_flexible(date)
            except ValueError as e:
                await interaction.response.send_message(f"INVALID DATE. {e}", ephemeral=True, delete_after=10)
                return
            try:
                _, time_from = parse_time_flexible(time_from)
                _, time_to = parse_time_flexible(time_to)
            except ValueError as e:
                await interaction.response.send_message(f"INVALID TIME. {e}", ephemeral=True, delete_after=10)
                return
            time_off = f"{time_from} TO {time_to}"
            try:
                cumulated_hours = float(re.findall(r'\d+\.?\d*', cumulated_hours_str)[0])
            except (ValueError, IndexError):
                await interaction.response.send_message("INVALID CUMULATED HOURS.", ephemeral=True, delete_after=10)
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
            await _send_ephemeral(interaction, f"OFF DUTY SUBMITTED. LEAVE ID: {leave_id}")
        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"AN ERROR OCCURRED: {e}", ephemeral=True, delete_after=10)
            else:
                await _send_ephemeral(interaction, f"Call [ERR-LV-030] AN ERROR OCCURRED: {e}")


# ─── Routing helpers ──────────────────────────────────────────────────────────

async def send_leave_application_to_approval_channel(interaction, leave_details, user_roles):
    first_ch_id = None
    for role_name, role_id in cfg.DEPARTMENT_ROLES.items():
        if role_id in user_roles:
            first_ch_id = cfg.APPROVAL_CHANNELS[role_name]
            break
    for role_name, role_id in cfg.DIRECT_SECOND_APPROVAL_ROLES.items():
        if role_id in user_roles:
            first_ch_id = None
            break

    approval_ch_id = first_ch_id if first_ch_id else cfg.APPROVAL_CHANNELS['hr']
    bot = interaction.client
    channel = bot.get_channel(approval_ch_id)
    if channel is None:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"Error: approval channel {approval_ch_id} not found.", ephemeral=True, delete_after=10)
        else:
            await _send_ephemeral(interaction, f"Call [ERR-LV-031] Error: approval channel {approval_ch_id} not found.")
        return

    # Fetch user's total leave history for display in approval embed
    try:
        user_data = await db.fetch_dynamic_user(interaction.user.id)
        if user_data:
            leave_details['total_sick_leave'] = user_data.get('total_sick_leave', 0) or 0
            leave_details['total_casual_leave'] = user_data.get('total_casual_leave', 0) or 0
            leave_details['total_c_off'] = user_data.get('total_c_off', 0) or 0
    except Exception:
        pass

    current_stage = 'first' if first_ch_id else 'hr'
    view = LeaveApprovalView(interaction.user.id, leave_details, current_stage, interaction.user.display_name, bot_ref=bot)
    await view._ensure_buttons_attached(interaction)
    embed = create_leave_embed(leave_details, interaction.user.id, interaction.user.display_name, current_stage)
    message = await channel.send(embed=embed, view=view)
    footer_text = f"Stage: {current_stage} | User ID: {interaction.user.id} | Nickname: {interaction.user.display_name} | Channel ID: {approval_ch_id} | Message ID: {message.id}"
    embed.set_footer(text=footer_text)
    await message.edit(embed=embed)
    await db.update_footer_text(interaction.user.display_name, leave_details['leave_id'], footer_text)

    # Send DM to the user with Leave ID and Date
    dm_msg_id = None
    try:
        user = await bot.fetch_user(interaction.user.id)
        date_display = leave_details.get('date_from', 'N/A')
        if leave_details.get('date_to'):
            date_display += f" TO {leave_details['date_to']}"
        dm_embed = discord.Embed(title="Leave Application Submitted", color=5810975)
        dm_embed.add_field(name="Leave ID", value=leave_details['leave_id'], inline=False)
        dm_embed.add_field(name="Date", value=date_display, inline=False)
        dm_embed.add_field(name="Status", value="Pending First Approval", inline=False)

        # Attach Cancel view for the first step
        dm_view = DMLeaveActionView(leave_details['leave_id'], 'first', bot_ref=bot)
        dm_message = await user.send(embed=dm_embed, view=dm_view)
        dm_msg_id = dm_message.id
    except discord.Forbidden:
        logger.warning(f"[ERR-LV-032] Could not send DM to user {interaction.user.display_name}")

    # Append the DM ID to the footer so we can edit it later
    if dm_msg_id:
        footer_text += f" | DM ID: {dm_msg_id}"
        embed.set_footer(text=footer_text)
        await message.edit(embed=embed)
        await db.update_footer_text(interaction.user.display_name, leave_details['leave_id'], footer_text)


async def update_persistent_dm(bot, user_id, leave_details, next_stage, footer_text, status_msg=None, color=None):
    """Edits the original direct message sent to the user, updating status and buttons."""
    try:
        # Extract DM ID from footer
        if not footer_text or "DM ID: " not in footer_text:
            logger.warning(f"[ERR-LV-033] [Leave] update_persistent_dm: no DM ID in footer for leave {leave_details.get('leave_id')}")
            return

        dm_id_str = footer_text.split("DM ID: ")[1].split(" | ")[0].strip()
        dm_id = int(dm_id_str)

        user = await bot.fetch_user(user_id)
        if not user.dm_channel:
            await user.create_dm()

        try:
            msg = await user.dm_channel.fetch_message(dm_id)
        except discord.NotFound:
            logger.warning(f"[ERR-LV-034] [Leave] Persistent DM {dm_id} not found for user {user_id}. They may have deleted it.")
            return

        date_display = leave_details.get('date_from', 'N/A')
        if leave_details.get('date_to'):
            date_display += f" TO {leave_details['date_to']}"

        # Stage label for the status field
        stage_labels = {
            'first':  'Pending HOD Approval',
            'second': 'Pending HR Approval',
            'final':  status_msg or 'Finalised',
        }
        status_text = status_msg or stage_labels.get(next_stage, next_stage.title())

        embed = discord.Embed(title="🌴 Leave Application Status", color=color or 5810975)
        embed.add_field(name="Leave ID",  value=leave_details['leave_id'], inline=True)
        embed.add_field(name="Date",      value=date_display,              inline=True)
        embed.add_field(name="\u200b",     value="\u200b",                   inline=True)  # spacer
        embed.add_field(name="Status",    value=status_text,               inline=False)

        # Button logic:
        # first / second → Cancel Leave (direct cancellation allowed)
        # final (HR approved) → Request Cancellation
        # any other final (declined / withdrawn) → no buttons
        if next_stage in ('first', 'second'):
            view = DMLeaveActionView(leave_details['leave_id'], next_stage, bot_ref=bot)
        elif next_stage == 'final' and color == 0x2ecc71:   # green = approved by HR
            view = DMLeaveActionView(leave_details['leave_id'], 'final', bot_ref=bot)
        else:
            view = None   # declined or withdrawn — no further actions

        await msg.edit(embed=embed, view=view)

    except Exception as e:
        logger.error(f"[ERR-LV-035] [Leave] Error updating persistent DM for {user_id}: {e}")

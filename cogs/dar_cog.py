"""
cogs/dar_cog.py — DAR (Daily Activity Report) Cog
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.
"""

import asyncio
import datetime
import logging
import os
import discord
from discord.ext import commands
from discord.ui import Button, View, Modal, TextInput

from Bots.utils.timezone import now_ist
from Bots.db_managers import discovery_db_manager as discovery

# Live config — populated by resolve_dar_config() on bot startup
DAR_SUBMITTED_ROLE_ID = 1281317724294877236
ON_LEAVE_ROLE_ID      = 1284784204403707914
PA_ROLE_ID            = 1281170902368784385
DAR_EXCLUDE_ROLE_ID   = 1282590818376482816

async def resolve_dar_config():
    """
    Queries discovery.db to resolve role IDs by name.
    Ensures the bot stays 'living' even after a DB reset.
    """
    global DAR_SUBMITTED_ROLE_ID, ON_LEAVE_ROLE_ID, PA_ROLE_ID, DAR_EXCLUDE_ROLE_ID
    
    logger = logging.getLogger("Concord")

    # Mapping of logical ID to role name in Discord
    mappings = {
        'DAR_SUBMITTED_ROLE_ID': 'DAR Submitted',
        'ON_LEAVE_ROLE_ID':      'On Leave',
        'PA_ROLE_ID':            'PA',
        'DAR_EXCLUDE_ROLE_ID':   'DAR Exclude',
    }

    for var_name, role_name in mappings.items():
        resolved = await discovery.get_role_id_by_name(role_name)
        if resolved:
            globals()[var_name] = resolved
            logger.info(f"[DAR Config] @{role_name} → {resolved}")

    logging.info("[DAR Config] Configuration resolved from discovery.db.")

# Linux-compatible log directory
DAR_LOG_DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'Database', 'DAR exports'))

# -------------------------------------------------------------------------
# Ephemeral helper
# -------------------------------------------------------------------------

async def _send_ephemeral(interaction: discord.Interaction, content: str, delay: int = 10) -> None:
    """Send an ephemeral response/followup and auto-delete it after `delay` seconds."""
    msg = None
    if not interaction.response.is_done():
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
# UI Components
# -------------------------------------------------------------------------

class DARSubmissionModal(Modal, title="Submit Daily Activity Report"):
    work_done = TextInput(
        label="Work Done Today",
        style=discord.TextStyle.paragraph,
        placeholder="Briefly describe what you worked on...",
        required=True,
        max_length=1500
    )
    issues = TextInput(
        label="Issues / Blockers (Optional)",
        style=discord.TextStyle.paragraph,
        placeholder="Any blockers hindering your progress?",
        required=False,
        max_length=1000
    )

    def __init__(self, bot_ref: commands.Bot):
        super().__init__()
        self.bot = bot_ref

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        role_ids = [r.id for r in user.roles]

        # 1. Validation Logic
        if DAR_SUBMITTED_ROLE_ID in role_ids:
            await _send_ephemeral(interaction, "❌ You have already submitted a D.A.R today.")
            return

        # 2. Extract DAR contents securely limit (Discord embed descript limit 4096)
        work_text = self.work_done.value.strip() or "None"
        issues_text = self.issues.value.strip() or "None"

        embed = discord.Embed(
            title=f"D.A.R | {user.display_name}",
            color=0x3498db,
            timestamp=datetime.datetime.now()
        )
        embed.set_author(name=user.display_name, icon_url=user.display_avatar.url if user.display_avatar else None)
        embed.add_field(name="Work Done", value=work_text[:1024], inline=False)
        embed.add_field(name="Issues/Blockers", value=issues_text[:1024], inline=False)

        # 3. Route to DAR-reports
        report_channel_id = await discovery.get_channel_id_by_name("dar-reports")
        if not report_channel_id:
            logger = logging.getLogger("Concord")
            logger.error("[ERR-DAR-001] [DAR] #dar-reports channel not found in database. Attempting fallback creation...")
            
            # Attempt auto-creation inside the Logs category if applicable
            try:
                guild = interaction.guild
                category = discord.utils.get(guild.categories, name="logs") or discord.utils.get(guild.categories, name="Logs")
                bot_role = guild.me.top_role
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    bot_role: discord.PermissionOverwrite(read_messages=True, send_messages=True)
                }
                new_ch = await guild.create_text_channel("dar-reports", category=category, overwrites=overwrites)
                report_channel_id = new_ch.id
                await discovery.upsert_channel(new_ch.id, new_ch.name, 'text', category.id if category else 0)
                logger.info("[DAR] Auto-created #dar-reports channel.")
            except Exception as e:
                logger.exception(f"[ERR-DAR-002] [DAR] Fatal fail creating #dar-reports: {e}")
                await _send_ephemeral(interaction, "❌ Call [ERR-DAR-012]: Destination `#dar-reports` channel could not be found or created.")
                return

        report_channel = self.bot.get_channel(report_channel_id)
        if not report_channel:
            await _send_ephemeral(interaction, "❌ Call [ERR-DAR-013]: Could not resolve `#dar-reports` object.")
            return

        try:
            await report_channel.send(embed=embed)
        except Exception as e:
            logging.getLogger("Concord").exception(f"[DAR] Failed to send report: {e}")
            await _send_ephemeral(interaction, "❌ Call [ERR-DAR-014]: Failed to push report to destination.")
            return

        # 4. Success — Assign Role
        try:
            role = discord.utils.get(interaction.guild.roles, id=DAR_SUBMITTED_ROLE_ID)
            if role:
                await user.add_roles(role)
            await _send_ephemeral(interaction, "✅ D.A.R submitted successfully.")
            logging.getLogger("Concord").info(f"[DAR] {user.display_name} submitted their DAR.")
        except Exception as e:
            logging.getLogger("Concord").exception(f"[DAR] Failed to assign DAR role to {user.display_name}: {e}")
            await _send_ephemeral(interaction, "✅ D.A.R submitted, but failed to assign the tracker role.")


class DARSetupView(View):
    def __init__(self, bot_ref: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot_ref

    @discord.ui.button(label="Submit Daily Activity Report", style=discord.ButtonStyle.primary, custom_id="dar_submit_button", emoji="📝")
    async def submit_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(DARSubmissionModal(self.bot))


class DARCog(commands.Cog, name="DAR"):
    """Assigns DAR Submitted role and sends reminders."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._last_reminder_hour = None
        self.logger = logging.getLogger("Concord")

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def cog_load(self):
        # Ensure discovery event exists
        if not hasattr(self.bot, 'discovery_complete'):
            self.bot.discovery_complete = asyncio.Event()

    @commands.Cog.listener()
    async def on_ready(self):
        # Wait for Discovery to populate the DB
        logging.getLogger("Concord").info("[DAR] Waiting for discovery_complete signal...")
        await self.bot.discovery_complete.wait()
        await resolve_dar_config()
        """Called automatically when the cog is loaded."""
        self.bot.add_view(DARSetupView(self.bot))
        asyncio.ensure_future(self.check_role_expiry())
        # Automatically ensure the UI exists in the channel instead of requiring a manual command
        self.bot.loop.create_task(self.ensure_dar_ui())

    # -------------------------------------------------------------------------
    # Auto-Initialization
    # -------------------------------------------------------------------------

    async def ensure_dar_ui(self):
        """Automatically checks `#daily-activity-report` and deploys the DAR UI if missing."""
        await self.bot.wait_until_ready()
        await asyncio.sleep(5) # Let Discovery cog finish its fast initial sweeps

        target_channel_id = await discovery.get_channel_id_by_name("daily-activity-report")
        if not target_channel_id:
            self.logger.warning("[ERR-DAR-003] [DAR] #daily-activity-report not found in discovery DB. UI cannot be deployed.")
            return
            
        target_channel = self.bot.get_channel(target_channel_id)
        if not target_channel:
            self.logger.warning("[ERR-DAR-004] [DAR] Could not resolve `#daily-activity-report` object.")
            return

        # Check if the panel is already there
        try:
            async for msg in target_channel.history(limit=10):
                if msg.author == self.bot.user and msg.embeds and "Daily Activity Report Submission" in msg.embeds[0].title:
                    self.logger.info("[DAR] DAR Panel already exists.")
                    return
        except discord.Forbidden:
            self.logger.error("[ERR-DAR-005] [DAR] Missing permissions to read/history in #daily-activy-report.")
            return
        except Exception as e:
            self.logger.error(f"[ERR-DAR-006] [DAR] Error checking history: {e}")
            return

        # Deploy it since it's missing
        embed = discord.Embed(
            title="📊 Daily Activity Report Submission",
            description="Please click the button below to submit your daily activity report. Include your primary tasks and any blockers you faced.\n\n*Note: Submissions are tracked and recorded automatically.*",
            color=0x2ecc71
        )
        
        try:
            await target_channel.purge(limit=10) # Sweep out any lingering garbage
            await target_channel.send(embed=embed, view=DARSetupView(self.bot))
            self.logger.info("[DAR] Automatically auto-deployed the DAR Panel.")
        except Exception as e:
            self.logger.error(f"[ERR-DAR-007] [DAR] Failed to deploy DAR UI: {e}")

    # -------------------------------------------------------------------------
    # Background loop
    # -------------------------------------------------------------------------

    async def check_role_expiry(self):
        """Periodically checks for role expiry and sends reminders."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = now_ist()  # IST-aware; replaces naive datetime.now()

            # Remove DAR Submitted role at 11:00 AM IST daily
            if now.hour == 11 and now.minute == 0:
                self.logger.info("[DAR] 11:00 AM IST — handling role removal.")
                await self.handle_role_removal()

            # Send DAR reminders every hour from 7 PM to 10 PM IST (except Sundays)
            if now.weekday() != 6 and 19 <= now.hour <= 22 and now.minute == 0:
                if self._last_reminder_hour != now.hour:
                    self.logger.info(f"[DAR] Sending reminders at {now.hour}:00 IST")
                    await self.send_dar_reminders()
                    self._last_reminder_hour = now.hour

            await asyncio.sleep(60)

    # -------------------------------------------------------------------------
    # Role management
    # -------------------------------------------------------------------------

    async def handle_role_removal(self):
        """Removes the DAR Submitted role from all members at 11:00 AM."""
        removed_members = []
        for member in self.bot.get_all_members():
            try:
                if DAR_SUBMITTED_ROLE_ID in [role.id for role in member.roles]:
                    role = discord.utils.get(member.guild.roles, id=DAR_SUBMITTED_ROLE_ID)
                    await member.remove_roles(role)
                    removed_members.append(member.name)
                    self.logger.info(f"[DAR] Removed role {role.name} from {member.name}")
                    await asyncio.sleep(0.05) # Yield to prevent blocking
            except discord.Forbidden:
                self.logger.error(f"[ERR-DAR-008] [DAR] Missing permissions to remove role from {member.name}")
            except Exception as e:
                self.logger.error(f"[ERR-DAR-009] [DAR] Error processing {member.name}: {e}")

        await self.log_dar_submissions(removed_members)

    async def log_dar_submissions(self, members: list):
        """Logs the list of members who had DAR Submitted removed to a file."""
        os.makedirs(DAR_LOG_DIRECTORY, exist_ok=True)
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        log_path = os.path.join(DAR_LOG_DIRECTORY, f"dar_submissions_{date_str}.txt")
        with open(log_path, "w") as f:
            f.write("DAR Submissions removed at 11:00 AM:\n")
            for member in members:
                f.write(f"{member}\n")
        self.logger.info(f"[DAR] Submissions logged to {log_path}")

    async def send_dar_reminders(self):
        """DMs all members who haven't submitted their DAR yet."""
        for member in self.bot.get_all_members():
            role_ids = [role.id for role in member.roles]
            if (
                member.id != self.bot.user.id
                and DAR_SUBMITTED_ROLE_ID not in role_ids
                and PA_ROLE_ID not in role_ids
                and ON_LEAVE_ROLE_ID not in role_ids
                and DAR_EXCLUDE_ROLE_ID not in role_ids
            ):
                try:
                    await member.send("Reminder: You haven't submitted your D.A.R yet.")
                    self.logger.info(f"[DAR] Sent reminder to {member.name}")
                    await asyncio.sleep(0.1) # Yield to prevent blocking
                except discord.Forbidden:
                    self.logger.warning(f"[ERR-DAR-010] [DAR] Cannot DM {member.name} (DMs disabled).")
                except Exception as e:
                    self.logger.error(f"[ERR-DAR-011] [DAR] Error DMing {member.name}: {e}")


async def setup(bot):
    await bot.add_cog(DARCog(bot))

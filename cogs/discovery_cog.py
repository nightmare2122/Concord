import discord
from discord.ext import commands
import logging
import asyncio

from Bots.db_managers import discovery_db_manager as db

logger = logging.getLogger("Concord")


class DiscoveryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bg_task = None
        self._sweep_task = None
        self._cleanup_task = None

    async def cog_load(self):
        self.bg_task = asyncio.create_task(db.db_worker())
        await db.initialize_discovery_db()
        # Initialize the global discovery event
        if not hasattr(self.bot, 'discovery_complete'):
            self.bot.discovery_complete = asyncio.Event()
        self.bot.discovery_complete.clear()

    async def cog_unload(self):
        for task in (self.bg_task, self._sweep_task, self._cleanup_task):
            if task:
                task.cancel()

    # ─── Initial Full Sweep ───────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_ready(self):
        logger.info("[Discovery] Starting initial server analysis...")
        for guild in self.bot.guilds:
            for category in guild.categories:
                await db.upsert_category(category.id, category.name)

            for channel in guild.channels:
                category_id = getattr(channel, 'category_id', None)
                await db.upsert_channel(channel.id, channel.name, str(channel.type), category_id)

            for role in guild.roles:
                await db.upsert_role(role.id, role.name, role.color, role.position)

            async for member in guild.fetch_members(limit=None):
                role_names = [r.name for r in member.roles if r.name != '@everyone']
                await db.upsert_member(member.id, member.name, member.display_name, member.joined_at, roles=role_names)
                await asyncio.sleep(0.1)  # Rate limit: 10 members/sec to avoid API limits

            for event in guild.scheduled_events:
                await db.upsert_scheduled_event(
                    event.id, event.name, event.description,
                    event.start_time, event.end_time, event.status.value
                )

        # Kick off async message sweeping so we don't block on_ready
        self._sweep_task = asyncio.create_task(self._sweep_messages())
        self._cleanup_task = asyncio.create_task(self._message_cleanup_engine())

        logger.info("[Discovery] Initial server discovery complete.")
        self.bot.discovery_complete.set()

    async def _sweep_messages(self):
        """Asynchronously sweep recent messages to populate the database without blocking."""
        logger.info("[Discovery] Starting background message sweep...")
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                try:
                    async for message in channel.history(limit=50):
                        await db.upsert_message(
                            message.id,
                            message.channel.id,
                            message.author.id,
                            message.content,
                            message.created_at
                        )
                except discord.Forbidden:
                    logger.debug(f"[Discovery] Missing read permissions for #{channel.name}")
                except Exception as e:
                    logger.error(f"[ERR-DSC-001] [Discovery] Error sweeping #{channel.name}: {e}")
        logger.info("[Discovery] Background message sweep complete.")

    async def _message_cleanup_engine(self):
        """Runs once daily to prune the messages table, keeping the 5000 most recent entries."""
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await asyncio.sleep(86400)  # 24 hours
            try:
                await db.cleanup_old_messages(keep=5000)
            except Exception as e:
                logger.error(f"[ERR-DSC-002] [Discovery] Message cleanup error: {e}")

    # ─── Category Events ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if isinstance(channel, discord.CategoryChannel):
            await db.upsert_category(channel.id, channel.name)
            logger.info(f"[Discovery] Category created: {channel.name} ({channel.id})")
        else:
            category_id = getattr(channel, 'category_id', None)
            await db.upsert_channel(channel.id, channel.name, str(channel.type), category_id)
            logger.info(f"[Discovery] Channel created: #{channel.name} ({channel.id})")

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if isinstance(after, discord.CategoryChannel):
            await db.upsert_category(after.id, after.name)
            if before.name != after.name:
                logger.info(f"[Discovery] Category renamed: {before.name} -> {after.name}")
        else:
            category_id = getattr(after, 'category_id', None)
            await db.upsert_channel(after.id, after.name, str(after.type), category_id)
            if before.name != after.name:
                logger.info(f"[Discovery] Channel renamed: #{before.name} -> #{after.name}")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if isinstance(channel, discord.CategoryChannel):
            await db.delete_category(channel.id)
            logger.info(f"[Discovery] Category deleted: {channel.name} ({channel.id})")
        else:
            await db.delete_channel(channel.id)
            logger.info(f"[Discovery] Channel deleted: #{channel.name} ({channel.id})")

    # ─── Role Events ──────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        await db.upsert_role(role.id, role.name, role.color, role.position)
        logger.info(f"[Discovery] Role created: @{role.name} ({role.id})")

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        await db.upsert_role(after.id, after.name, after.color, after.position)
        if before.name != after.name:
            logger.info(f"[Discovery] Role renamed: @{before.name} -> @{after.name}")

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        await db.delete_role(role.id)
        logger.info(f"[Discovery] Role deleted: @{role.name} ({role.id})")

    # ─── Member Events ────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member):
        await db.upsert_member(member.id, member.name, member.display_name, member.joined_at)
        logger.info(f"[Discovery] Member joined: {member.display_name} ({member.id})")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Detect role or profile changes
        roles_changed  = set(r.id for r in before.roles) != set(r.id for r in after.roles)
        profile_changed = before.display_name != after.display_name or before.name != after.name

        if roles_changed or profile_changed:
            role_names = [r.name for r in after.roles if r.name != '@everyone']
            await db.upsert_member(after.id, after.name, after.display_name, after.joined_at, roles=role_names)

        if roles_changed:
            added   = [r.name for r in after.roles  if r not in before.roles]
            removed = [r.name for r in before.roles if r not in after.roles]
            if added:
                logger.info(f"[Discovery] {after.display_name} gained roles: {', '.join(added)}")
            if removed:
                logger.info(f"[Discovery] {after.display_name} lost roles:  {', '.join(removed)}")

        if profile_changed and not roles_changed:
            logger.info(f"[Discovery] Member updated: {before.display_name} -> {after.display_name}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await db.delete_member(member.id)
        logger.info(f"[Discovery] Member left: {member.display_name} ({member.id})")

    # ─── Message Events ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None:
            return
        await db.upsert_message(
            message.id,
            message.channel.id,
            message.author.id,
            message.content,
            message.created_at
        )

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if payload.guild_id is None:
            return
        
        try:
            channel = self.bot.get_channel(payload.channel_id)
            if not channel:
                return
            
            # Using content if available in payload
            content = payload.data.get('content')
            if content is not None:
                # To accurately update we need the full message, but if only content changed:
                # Often it's safer to fetch the message
                try:
                    msg = await channel.fetch_message(payload.message_id)
                    await db.upsert_message(
                        msg.id,
                        msg.channel.id,
                        msg.author.id,
                        msg.content,
                        msg.created_at
                    )
                except discord.NotFound:
                    pass
        except Exception as e:
            logger.error(f"[ERR-DSC-002] [Discovery] Error tracking edited message: {e}")

    # ─── Scheduled Events ─────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event):
        await db.upsert_scheduled_event(
            event.id, event.name, event.description,
            event.start_time, event.end_time, event.status.value
        )
        logger.info(f"[Discovery] Scheduled Event created: {event.name}")

    @commands.Cog.listener()
    async def on_scheduled_event_update(self, before, after):
        await db.upsert_scheduled_event(
            after.id, after.name, after.description,
            after.start_time, after.end_time, after.status.value
        )
        logger.info(f"[Discovery] Scheduled Event updated: {after.name}")

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self, event):
        await db.delete_scheduled_event(event.id)
        logger.info(f"[Discovery] Scheduled Event deleted: {event.name}")

async def setup(bot):
    await bot.add_cog(DiscoveryCog(bot))

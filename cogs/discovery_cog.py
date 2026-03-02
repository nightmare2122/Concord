import discord
from discord.ext import commands
import logging
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Bots'))
from db_managers import discovery_db_manager as db

logger = logging.getLogger("Concord")


class DiscoveryCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bg_task = None

    async def cog_load(self):
        self.bg_task = self.bot.loop.create_task(db.db_worker())
        await db.initialize_discovery_db()

    async def cog_unload(self):
        if self.bg_task:
            self.bg_task.cancel()

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

        logger.info("[Discovery] Initial server discovery complete.")

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


async def setup(bot):
    await bot.add_cog(DiscoveryCog(bot))

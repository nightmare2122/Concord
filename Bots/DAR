# This bot functions to assign DAR Submitted role to the users and generate DAR reports.

import discord
from discord.ext import commands
import asyncio
import datetime
import logging
import os

# Setup logging
logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Global variable to track the last reminder hour
last_reminder_hour = None

bot = commands.Bot(command_prefix='!', intents=intents)

# Hardcoded sensitive data
TOKEN = 'MTI4NDc3OTA4MTc3MDIwNTI1Ng.GctRCw.Mt4NTUrm4m9PLHmqSGDL-6uVGQKaVNTxtIX6VI'

# Hardcoded IDs of the relevant roles
dar_submitted_role_id = 1281317724294877236
on_leave_role_id = 1284784204403707914
pa_role_id = 1281170902368784385

async def check_role_expiry():
    """Periodically checks for role expiry and reminders."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        now = datetime.datetime.now()
        logging.info(f"Current time: {now}")

        # Check if it's 11:00 AM
        if now.hour == 11 and now.minute == 0:
            logging.info("It's 11:00 AM, handling role removal.")
            await handle_role_removal()

        # Check for DAR submission reminders (every hour from 7 PM to 10 PM, except on Sundays)
        global last_reminder_hour
        if now.weekday() != 6 and 19 <= now.hour <= 22 and now.minute == 0:
            if last_reminder_hour != now.hour:
                logging.info(f"Sending DAR reminders at {now.hour}:00")
                await send_dar_reminders()
                last_reminder_hour = now.hour

        # Sleep for 60 seconds before checking again
        await asyncio.sleep(60)

async def handle_role_removal():
    """Handles the removal of roles at 11:00 AM."""
    target_role_id = dar_submitted_role_id
    removed_members = []
    for member in bot.get_all_members():
        try:
            if target_role_id in [role.id for role in member.roles]:
                role = discord.utils.get(member.guild.roles, id=target_role_id)
                await member.remove_roles(role)
                removed_members.append(member.name)
                logging.info(f"Removed role {role.name} from {member.name}")
        except discord.Forbidden:
            logging.error(f"Error removing role from {member.name}: Missing Permissions. Check role hierarchy.")
        except Exception as e:
            logging.error(f"An error occurred while processing {member.name}: {e}")
    
    # Log the removed members to a text file
    specific_log_directory = r'Z:\DAR exports'
    await log_dar_submissions(removed_members, specific_log_directory)

async def log_dar_submissions(members, log_directory):
    """Logs the DAR submissions to a text file."""
    os.makedirs(log_directory, exist_ok=True)
    log_file_path = os.path.join(log_directory, f'dar_submissions_{datetime.datetime.now().strftime("%Y-%m-%d")}.txt')
    
    with open(log_file_path, 'w') as log_file:
        log_file.write("DAR Submissions:\n")
        for member in members:
            log_file.write(f"{member}\n")
    
    logging.info(f"DAR submissions logged to {log_file_path}")

async def send_dar_reminders():
    """Sends DAR reminders to members."""
    for member in bot.get_all_members():
        if (
            member.id != bot.user.id and 
            dar_submitted_role_id not in [role.id for role in member.roles] and 
            pa_role_id not in [role.id for role in member.roles] and
            on_leave_role_id not in [role.id for role in member.roles] and
            1282590818376482816 not in [role.id for role in member.roles]  # Exclude users with the specified role ID
        ):
            try:
                await member.send("Reminder: You haven't submitted your D.A.R yet.")
                logging.info(f"Sent reminder to {member.name}")
                await asyncio.sleep(1)  # Respect rate limits
            except discord.Forbidden:
                logging.warning(f"Cannot send DM to {member.name}. DMs might be disabled or the user has blocked the bot.")
            except Exception as e:
                logging.error(f"An unexpected error occurred while sending a DM to {member.name}: {e}")

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    logging.info('------')
    bot.loop.create_task(check_role_expiry())

@bot.event
async def on_message(message):
    if message.channel.id == 1282571345850400768:
        if message.embeds:
            embed = message.embeds[0]
            author_name = embed.author.name
            guild = message.guild
            member = guild.get_member_named(author_name)
            if member:
                role = discord.utils.get(guild.roles, id=dar_submitted_role_id)
                if role:
                    await member.add_roles(role)
                    logging.info(f"Assigned role {role.name} to {author_name}")
                else:
                    logging.error(f"Role with ID {dar_submitted_role_id} not found in the guild.")
            else:
                logging.error(f"Member with name {author_name} not found in the guild.")

async def main():
    await bot.start(TOKEN)

if __name__ == '__main__':
    asyncio.run(main())

# Discord bot to track pending tasks and assign new ones..

import discord
from discord import ui
from discord.ext import commands
import asyncio
import sqlite3
import logging
import os
import difflib

# Function to find the closest match for a given name in the emp role
def find_closest_match(name, members):
    names = [member.display_name.lower() for member in members]
    closest_matches = difflib.get_close_matches(name.lower(), names, n=1, cutoff=0.6)
    if closest_matches:
        closest_name = closest_matches[0]
        for member in members:
            if member.display_name.lower() == closest_name:
                return member
    return None

# Initialize logging
logging.basicConfig(level=logging.DEBUG)

class CustomClient(commands.Bot):
    async def connect(self, *, reconnect=True):
        backoff = 1  # Initial backoff time in seconds
        while not self.is_closed():
            try:
                await super().connect(reconnect=reconnect)
                backoff = 1  # Reset backoff on successful connection
            except (OSError, discord.GatewayNotFound, discord.ConnectionClosed, discord.HTTPException) as exc:
                logging.error(f"Connection error: {exc}. Attempting to reconnect in {backoff} seconds...")
                if not reconnect:
                    await self.close()
                    if isinstance(exc, discord.ConnectionClosed):
                        raise
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)  # Exponential backoff with a maximum of 60 seconds
            except asyncio.TimeoutError:
                logging.error(f"Connection timed out. Attempting to reconnect in {backoff} seconds...")
                if not reconnect:
                    await self.close()
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)  # Exponential backoff with a maximum of 60 seconds

# Define intents
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# Initialize bot
bot = CustomClient(command_prefix="!", intents=intents)

COMMAND_CHANNEL_ID = 1293531912496746638

departments = {
            "Administration": 1281171713299714059,
            "Architects": 1281172225432752149,
            "CAD": 1281172603217645588,
            "Site": 1285183387258327050,
            "Interns": 1281195640109400085
        }

# Function to check and create the database file
def check_and_create_database():
    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER,
                assignees TEXT,
                details TEXT,
                deadline TEXT,
                temp_channel_link TEXT,
                assigner TEXT,
                status TEXT,
                title TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_tasks_channels (
                user_id INTEGER PRIMARY KEY,
                channel_id INTEGER,
                tasks TEXT,
                task_message_ids TEXT
            )
        ''')
        conn.commit()
        conn.close()
    else:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if the 'tasks' and 'task_message_ids' columns exist
        cursor.execute("PRAGMA table_info(pending_tasks_channels)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'tasks' not in columns:
            cursor.execute('''
                ALTER TABLE pending_tasks_channels ADD COLUMN tasks TEXT
            ''')
        if 'task_message_ids' not in columns:
            cursor.execute('''
                ALTER TABLE pending_tasks_channels ADD COLUMN task_message_ids TEXT
            ''')

        # Check if the 'title' column exists in the 'tasks' table
        cursor.execute("PRAGMA table_info(tasks)")
        columns = [column[1] for column in cursor.fetchall()]
        if 'title' not in columns:
            cursor.execute('''
                ALTER TABLE tasks ADD COLUMN title TEXT
            ''')
        
        conn.commit()
        conn.close()

# Database functions
async def store_task_in_database(task_data):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _store_task_in_database_sync, task_data)

async def retrieve_task_from_database(channel_id):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _retrieve_task_from_database_sync, channel_id)

async def update_task_in_database(task_data):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _update_task_in_database_sync, task_data)

async def retrieve_all_tasks_from_database():
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _retrieve_all_tasks_from_database_sync)

# Define the network path to the NAS
nas_path = r'Z:\Bot databases\Task'
db_path = os.path.join(nas_path, 'tasks.db')

def _store_task_in_database_sync(task_data):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            task_id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id TEXT,
            assignees TEXT,
            details TEXT,
            deadline TEXT,
            temp_channel_link TEXT,
            assigner TEXT,
            status TEXT,
            title TEXT
        )
    ''')
    cursor.execute('''
        INSERT INTO tasks (channel_id, assignees, details, deadline, temp_channel_link, assigner, status, title)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (task_data['channel_id'], ', '.join(task_data['assignees']), task_data['details'], task_data['deadline'], task_data['temp_channel_link'], task_data['assigner'], task_data['status'], task_data['title']))
    conn.commit()
    conn.close()

def _retrieve_task_from_database_sync(channel_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT assignees, details, deadline, temp_channel_link, assigner, status, title FROM tasks WHERE channel_id = ?', (channel_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            'channel_id': channel_id,
            'assignees': row[0].split(', '),
            'details': row[1],
            'deadline': row[2],
            'temp_channel_link': row[3],
            'assigner': row[4],
            'status': row[5],
            'title': row[6]  # Ensure title is included
        }
    return None

def _retrieve_all_tasks_from_database_sync():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT task_id, channel_id, assignees, details, deadline, temp_channel_link, assigner, status, title FROM tasks')
    rows = cursor.fetchall()
    conn.close()
    tasks = []
    for row in rows:
        tasks.append({
            'task_id': row[0],
            'channel_id': row[1],
            'assignees': row[2].split(', '),
            'details': row[3],
            'deadline': row[4],
            'temp_channel_link': row[5],
            'assigner': row[6],
            'status': row[7],
            'title': row[8]  # Ensure title is included
        })
    return tasks

def _update_task_in_database_sync(task_data):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE tasks
        SET assignees = ?, details = ?, deadline = ?, temp_channel_link = ?, assigner = ?, status = ?, title = ?
        WHERE channel_id = ?
    ''', (', '.join(task_data['assignees']), task_data['details'], task_data['deadline'], task_data['temp_channel_link'], task_data['assigner'], task_data['status'], task_data['title'], task_data['channel_id']))
    conn.commit()
    conn.close()

def _delete_task_from_database_sync(channel_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tasks WHERE channel_id = ?', (channel_id,))
    conn.commit()
    conn.close()

def store_pending_tasks_channel(user_id, channel_id, tasks=None, task_message_ids=None):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO pending_tasks_channels (user_id, channel_id, tasks, task_message_ids)
        VALUES (?, ?, ?, ?)
    ''', (user_id, channel_id, ','.join(tasks) if tasks else '', ','.join(task_message_ids) if task_message_ids else ''))
    conn.commit()
    conn.close()

def update_pending_tasks_channel(user_id, tasks, task_message_ids):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE pending_tasks_channels
        SET tasks = ?, task_message_ids = ?
        WHERE user_id = ?
    ''', (','.join(tasks), ','.join(task_message_ids), user_id))
    conn.commit()
    conn.close()

def retrieve_pending_tasks_channel(user_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('SELECT channel_id, tasks, task_message_ids FROM pending_tasks_channels WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return row[0], row[1].split(',') if row[1] else [], row[2].split(',') if row[2] else []
    return None, [], []

def _delete_pending_tasks_channel_from_database(user_id):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM pending_tasks_channels WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()

# Event handlers

@bot.event
async def on_disconnect():
    logging.warning("Bot has disconnected from Discord. Attempting to reconnect...")

@bot.event
async def on_resumed():
    logging.info("Bot has successfully reconnected to Discord.")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    
    # Check and create the database file if it doesn't exist
    check_and_create_database()
    
    command_channel = bot.get_channel(COMMAND_CHANNEL_ID)
    if command_channel:
        # Check if the command buttons already exist
        async for message in command_channel.history(limit=100):
            if message.author == bot.user and any(item.label in ["Assign Task", "View Tasks"] for item in message.components[0].children):
                print("Command buttons already exist in the command channel.")
                return
        
        # If command buttons do not exist, send them
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="Assign Task", style=discord.ButtonStyle.green, custom_id="assign_task_button"))
        view.add_item(discord.ui.Button(label="View Tasks", style=discord.ButtonStyle.primary, custom_id="view_tasks_button"))
        await command_channel.send("Command buttons:", view=view)

# Temp channel monitoring

async def monitor_task_assignment_channel(task_data, temp_channel, interaction):
    last_update_time = asyncio.get_event_loop().time()

    while True:
        await asyncio.sleep(5)  # Check every 5 seconds

        # Check if any new data has been entered in the task_data dictionary
        if task_data.get('details') or task_data.get('deadline'):
            last_update_time = asyncio.get_event_loop().time()

        # If no new data has been entered in the last 5 minutes, delete the channel
        if asyncio.get_event_loop().time() - last_update_time > 300:
            try:
                await temp_channel.delete()
                await interaction.followup.send("Task assignment channel deleted due to inactivity.", ephemeral=True)
            except discord.NotFound:
                print(f"Channel {temp_channel.id} not found for deletion.")
            break

@bot.event
async def on_interaction(interaction):
    if interaction.data.get('custom_id') == 'assign_task_button':
        await handle_assign_task(interaction)
    elif interaction.data.get('custom_id') == 'view_tasks_button':
        await handle_view_tasks_button(interaction)

async def handle_assign_task(interaction):
    try:
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        category = interaction.guild.get_channel(1299338707605651537)

        temp_channel = await interaction.guild.create_text_channel(
            f"task-assignment-{interaction.user.name}",
            overwrites=overwrites,
            category=category
        )

        temp_channel_url = temp_channel.jump_url

        await interaction.response.send_message(
            f"Task assignment process started. Please check the new channel: [Click here]({temp_channel_url})", 
            ephemeral=True
        )

        emp_role = interaction.guild.get_role(1290199089371287562)
        assignee_ids = []

        task_data = {
            'channel_id': temp_channel.id,
            'assignees': [],
            'details': '',
            'deadline': '',
            'temp_channel_link': temp_channel.jump_url,
            'assigner': interaction.user.display_name,
            'assigner_id': interaction.user.id,
            'assignee_ids': assignee_ids,
            'status': 'Pending',
            'title': ''  # Add title field
        }

        # Start monitoring the task assignment channel for inactivity
        bot.loop.create_task(monitor_task_assignment_channel(task_data, temp_channel, interaction))

        async def prompt_assignees():
            while True:
                await temp_channel.send("Enter the assignee names (separated by commas):")
                assignee_names_msg = await bot.wait_for('message', check=lambda m: m.author == interaction.user and m.channel == temp_channel)
                assignee_names = assignee_names_msg.content.split(',')

                assignees = []
                for name in assignee_names:
                    name = name.strip()
                    assignee = find_closest_match(name, emp_role.members)
                    if assignee:
                        assignees.append(assignee)
                        assignee_ids.append(str(assignee.id))
                    else:
                        await temp_channel.send(f"No match found for '{name}'. Please try again.")
                        break
                else:
                    assignee_names_str = ', '.join([assignee.display_name for assignee in assignees])
                    await temp_channel.send(f"Selected assignees: {assignee_names_str}")

                    view = ui.View(timeout=None)
                    retry_button = ui.Button(label="Retry Selection", style=discord.ButtonStyle.secondary)
                    confirm_button = ui.Button(label="Confirm Submission", style=discord.ButtonStyle.success)

                    async def retry_button_callback(interaction):
                        await interaction.response.defer()
                        assignee_ids.clear()
                        await prompt_assignees()

                    async def confirm_button_callback(interaction):
                        await interaction.response.defer()
                        await temp_channel.send("Please provide a concise task title:")
                        task_title_msg = await bot.wait_for('message', check=lambda m: m.author == interaction.user and m.channel == temp_channel)
                        task_title = task_title_msg.content
                        task_data['title'] = task_title  # Update task_data with the task title

                        await temp_channel.send("Now, provide the detailed task description:")
                        task_details_msg = await bot.wait_for('message', check=lambda m: m.author == interaction.user and m.channel == temp_channel)
                        task_details = task_details_msg.content
                        task_data['details'] = task_details  # Update task_data with new details

                        await temp_channel.send("Enter the due date and time (DD/MM/YYYY HH:MM AM/PM):")
                        due_date_msg = await bot.wait_for('message', check=lambda m: m.author == interaction.user and m.channel == temp_channel)
                        due_date = due_date_msg.content
                        task_data['deadline'] = due_date  # Update task_data with new deadline

                        await temp_channel.edit(name=f"task-{task_title.replace(' ', '-')}")

                        for assignee_id in assignee_ids:
                            assignee = interaction.guild.get_member(int(assignee_id))
                            await temp_channel.set_permissions(assignee, read_messages=True, send_messages=True)

                        task_data['assignees'] = [interaction.guild.get_member(int(assignee_id)).display_name for assignee_id in assignee_ids]

                        await prompt_deadline_confirmation(temp_channel, task_data, interaction.user.id, assignee_ids)

                    retry_button.callback = retry_button_callback
                    confirm_button.callback = confirm_button_callback

                    view.add_item(retry_button)
                    view.add_item(confirm_button)
                    await temp_channel.send("Confirm the assignees or retry selection:", view=view)
                    return

        await prompt_assignees()

    except Exception as e:
        await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)

async def handle_view_tasks_button(interaction):
    try:
        user_id = interaction.user.id
        user_nickname = interaction.user.display_name
        category = interaction.guild.get_channel(1299338707605651537)
        channel_id, sent_task_ids, task_message_ids = retrieve_pending_tasks_channel(user_id)

        if channel_id:
            existing_channel = bot.get_channel(channel_id)
            if existing_channel:
                await interaction.response.send_message("Tasks have been refreshed.", ephemeral=True)
            else:
                # If the channel doesn't exist anymore, remove it from the database
                _delete_pending_tasks_channel_from_database(user_id)
                channel_id = None

        if not channel_id:
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            }
            pending_tasks_channel = await interaction.guild.create_text_channel(f"pending-tasks-{user_nickname}", overwrites=overwrites, category=category)
            store_pending_tasks_channel(user_id, pending_tasks_channel.id)
            await interaction.response.send_message(f"Pending tasks channel created: {pending_tasks_channel.jump_url}", ephemeral=True)
        else:
            pending_tasks_channel = bot.get_channel(channel_id)

        tasks = await retrieve_all_tasks_from_database()
        user_tasks = [task for task in tasks if interaction.user.display_name in task['assignees'] or task['assigner'] == interaction.user.display_name]

        new_tasks_found = False

        for task in user_tasks:
            if str(task['task_id']) in sent_task_ids:
                continue  # Skip tasks that have already been sent

            new_tasks_found = True

            embed = discord.Embed(title="Pending Task", color=0x00ff00)
            channel = bot.get_channel(task['channel_id'])
            channel_name = channel.name if channel else f"Channel ID {task['channel_id']}"
            assignees = ', '.join(task['assignees'])
            embed.add_field(name=f"Task in {channel_name}", value=f"**Assignees:** {assignees}\n**Details:** {task['details']}\n**Deadline:** {task['deadline']}", inline=False)
            view = await handle_task_buttons(interaction, task)
            if view:
                message = await pending_tasks_channel.send(embed=embed, view=view)
            else:
                message = await pending_tasks_channel.send(embed=embed)

            # Track the sent task and its message ID
            sent_task_ids.append(str(task['task_id']))
            task_message_ids.append(str(message.id))
            update_pending_tasks_channel(user_id, sent_task_ids, task_message_ids)

        if not new_tasks_found:
            if not interaction.response.is_done():
                await interaction.response.send_message("No new tasks found.", ephemeral=True)
            else:
                await interaction.followup.send("No new tasks found.", ephemeral=True)

    except Exception as e:
        if not interaction.response.is_done():
            await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True)
        else:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

# Command handlers
@bot.command(name='view_tasks')
async def view_tasks(ctx):
    try:
        print("Command !view_tasks triggered")  # Debug statement
        tasks = await retrieve_all_tasks_from_database()
        print(f"Tasks retrieved: {tasks}")  # Debug statement

        if not tasks:
            await ctx.send("No pending tasks found.")
            return

        for task in tasks:
            embed = discord.Embed(title="Pending Task", color=0x00ff00)
            channel = bot.get_channel(task['channel_id'])
            channel_name = channel.name if channel else f"Channel ID {task['channel_id']}"
            assignees = ', '.join(task['assignees'])
            embed.add_field(name=f"Task in {channel_name}", value=f"**Assignees:** {assignees}\n**Details:** {task['details']}\n**Deadline:** {task['deadline']}", inline=False)
            view = await handle_task_buttons(ctx, task)
            if view:
                await ctx.send(embed=embed, view=view)
            else:
                await ctx.send(embed=embed)
    except Exception as e:
        print(f"Error occurred: {e}")  # Debug statement
        await ctx.send(f"An error occurred while retrieving tasks: {e}")

# Button handlers

async def handle_task_buttons(interaction, task):
    try:
        print(f"User: {interaction.user.display_name}, Assignees: {task['assignees']}, Assigner: {task['assigner']}")  # Debug statement

        if 'status' not in task:
            task['status'] = 'Pending'  # Default status if not present

        if interaction.user.display_name in task['assignees']:
            return await handle_assignee_buttons(interaction, task)
        elif interaction.user.display_name == task['assigner']:
            return await handle_assigner_buttons(interaction, task)
        else:
            return None
    except Exception as e:
        print(f"Error occurred in handle_task_buttons: {e}")
        return None

async def handle_assignee_buttons(interaction, task):
    view = ui.View(timeout=None)

    link_button = ui.Button(label="Task Link", style=discord.ButtonStyle.link, url=task['temp_channel_link'])

    view.add_item(link_button)

    modify_deadline_button = ui.Button(label="Modify Deadline", style=discord.ButtonStyle.secondary, custom_id=f"modify_deadline_{task['task_id']}")

    async def modify_deadline_button_callback(interaction):
        try:
            await interaction.response.defer()  # Acknowledge the interaction
            temp_channel = bot.get_channel(task['channel_id'])
            if temp_channel:
                await temp_channel.send("Please enter the new deadline (DD/MM/YYYY HH:MM AM/PM):")
                new_due_date_msg = await bot.wait_for('message', check=lambda m: m.author == interaction.user and m.channel == temp_channel)
                new_due_date = new_due_date_msg.content
                task['new_deadline'] = new_due_date
                task['assigner_id'] = interaction.guild.get_member_named(task['assigner']).id
                task['assignee_ids'] = [interaction.guild.get_member_named(assignee_name).id for assignee_name in task['assignees']]
                task['status'] = 'Pending'  # Ensure status is included
                await deadline_modification_prompt(temp_channel, task, task['assigner_id'], task['assignee_ids'])
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    modify_deadline_button.callback = modify_deadline_button_callback
    view.add_item(modify_deadline_button)

    mark_complete_button = ui.Button(label="Mark as Complete", style=discord.ButtonStyle.success, custom_id=f"mark_complete_{task['task_id']}")

    async def mark_complete_button_callback(interaction):
        try:
            await interaction.response.defer()  # Acknowledge the interaction
            task['status'] = 'Completed by Assignee'
            await update_task_in_database(task)
            await interaction.followup.send("Task marked as complete. The assigner will be notified.", ephemeral=True)

            # Update the assigner's view
            assigner_id = interaction.guild.get_member_named(task['assigner']).id
            await update_assigner_view(task, assigner_id, interaction)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    mark_complete_button.callback = mark_complete_button_callback
    view.add_item(mark_complete_button)

    return view

async def handle_assigner_buttons(interaction, task):
    view = ui.View(timeout=None)

    link_button = ui.Button(label="Task Link", style=discord.ButtonStyle.link, url=task['temp_channel_link'])
    complete_button = ui.Button(label="Task Completed", style=discord.ButtonStyle.danger if task['status'] != 'Completed by Assignee' else discord.ButtonStyle.success, custom_id=f"complete_task_{task['task_id']}")

    async def complete_button_callback(interaction):
        try:
            await interaction.response.defer()  # Acknowledge the interaction
            temp_channel = bot.get_channel(task['channel_id'])
            if temp_channel:
                await temp_channel.delete()
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _delete_task_from_database_sync, task['channel_id'])
            await interaction.message.delete()  # Delete the message with the task details
            await interaction.followup.send("Task completed and temporary channel deleted.", ephemeral=True)

            # Remove the task ID from the assigner's pending tasks channel
            user_id = interaction.user.id
            channel_id, sent_task_ids, task_message_ids = retrieve_pending_tasks_channel(user_id)
            if str(task['task_id']) in sent_task_ids:
                sent_task_ids.remove(str(task['task_id']))
                task_message_ids.remove(str(interaction.message.id))
                update_pending_tasks_channel(user_id, sent_task_ids, task_message_ids)

            # Remove the task ID from the assignees' pending tasks channels and their pending_tasks_channel table
            for assignee_name in task['assignees']:
                assignee = discord.utils.get(interaction.guild.members, display_name=assignee_name)
                if assignee:
                    assignee_channel_id, assignee_sent_task_ids, assignee_task_message_ids = retrieve_pending_tasks_channel(assignee.id)
                    if str(task['task_id']) in assignee_sent_task_ids:
                        # Find the message ID corresponding to the task ID
                        message_id_to_delete = None
                        for task_id, message_id in zip(assignee_sent_task_ids, assignee_task_message_ids):
                            if str(task['task_id']) == task_id:
                                message_id_to_delete = message_id
                                break

                        if message_id_to_delete:
                            assignee_sent_task_ids.remove(str(task['task_id']))
                            assignee_task_message_ids.remove(message_id_to_delete)
                            update_pending_tasks_channel(assignee.id, assignee_sent_task_ids, assignee_task_message_ids)

                            # Delete the task from the assignee's pending tasks channel
                            assignee_channel = bot.get_channel(assignee_channel_id)
                            if assignee_channel:
                                try:
                                    message = await assignee_channel.fetch_message(int(message_id_to_delete))
                                    await message.delete()
                                except discord.NotFound:
                                    print(f"Message with ID {message_id_to_delete} not found in channel {assignee_channel_id}")

        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    complete_button.callback = complete_button_callback

    view.add_item(link_button)
    view.add_item(complete_button)

    remind_button = ui.Button(label="Remind Assignee", style=discord.ButtonStyle.primary, custom_id=f"remind_task_{task['task_id']}")

    async def remind_button_callback(interaction):
        try:
            await interaction.response.defer()  # Acknowledge the interaction
            for assignee_name in task['assignees']:
                assignee = discord.utils.get(interaction.guild.members, display_name=assignee_name)
                if assignee:
                    await assignee.send(f"You have a pending task: {task['details']}\nDeadline: {task['deadline']}\nTemporary Channel: {task['temp_channel_link']}")
            await interaction.followup.send("Assignees reminded.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    remind_button.callback = remind_button_callback
    view.add_item(remind_button)

    return view

async def update_assigner_view(task, assigner_id, interaction):
    try:
        assigner_channel_id, assigner_sent_task_ids, assigner_task_message_ids = retrieve_pending_tasks_channel(str(assigner_id))
        if assigner_channel_id:
            assigner_channel = bot.get_channel(assigner_channel_id)
            if assigner_channel:
                for task_id, message_id in zip(assigner_sent_task_ids, assigner_task_message_ids):
                    if str(task['task_id']) == task_id:
                        message = await assigner_channel.fetch_message(int(message_id))
                        embed = discord.Embed(title="Pending Task", color=0x00ff00)
                        channel = bot.get_channel(task['channel_id'])
                        channel_name = channel.name if channel else f"Channel ID {task['channel_id']}"
                        assignees = ', '.join(task['assignees'])
                        embed.add_field(name=f"Task in {channel_name}", value=f"**Assignees:** {assignees}\n**Details:** {task['details']}\n**Deadline:** {task['deadline']}", inline=False)
                        view = await handle_assigner_buttons(interaction, task)
                        await message.edit(embed=embed, view=view)
                        break
    except Exception as e:
        print(f"An error occurred while updating the assigner's view: {e}")

#Task management and deadline confirmation

async def prompt_deadline_confirmation(channel, task_data, assigner_id, assignee_ids):
    embed = discord.Embed(title=task_data['title'], description=task_data['details'], color=0x00ff00)
    embed.add_field(name="Proposed Deadline", value=task_data.get('new_deadline', task_data['deadline']), inline=False)
    embed.set_footer(text="Please confirm or modify the deadline below.")

    confirm_button = ui.Button(label="Confirm Deadline", style=discord.ButtonStyle.success, custom_id="confirm_deadline_button")
    modify_button = ui.Button(label="Modify Deadline", style=discord.ButtonStyle.secondary, custom_id="modify_deadline_button")

    confirmed_users = set()

    async def confirm_button_callback(interaction):
        try:
            await interaction.response.defer()  # Acknowledge the interaction
            confirmed_users.add(interaction.user.id)

            if assigner_id in confirmed_users and all(int(assignee_id) in confirmed_users for assignee_id in assignee_ids):
                task_data['deadline'] = task_data.get('new_deadline', task_data['deadline'])
                task_data['status'] = 'Confirmed'  # Ensure status is included
                await store_task_in_database(task_data)  # Update the existing task in the database
                await interaction.followup.send("Deadline confirmed by both parties! Task details have been updated.", ephemeral=False)
            else:
                await interaction.followup.send("Deadline confirmed. Waiting for the other party to confirm.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    async def modify_button_callback(interaction):
        await interaction.response.send_message("Please enter the new deadline (DD/MM/YYYY HH:MM AM/PM):", ephemeral=True)
        new_due_date_msg = await bot.wait_for('message', check=lambda m: m.author == interaction.user and m.channel == channel)
        new_due_date = new_due_date_msg.content
        task_data['new_deadline'] = new_due_date
        confirmed_users.clear()
        embed.set_field_at(0, name="Proposed Deadline", value=new_due_date, inline=False)
        await channel.send("Deadline modified. Please confirm or modify the deadline below.", embed=embed, view=view)

    confirm_button.callback = confirm_button_callback
    modify_button.callback = modify_button_callback

    view = ui.View(timeout=None)
    view.add_item(confirm_button)
    view.add_item(modify_button)

    await channel.send(embed=embed, view=view)

async def deadline_modification_prompt(channel, task_data, assigner_id, assignee_ids):
    embed = discord.Embed(title=task_data['title'], description=task_data['details'], color=0x00ff00)
    embed.add_field(name="Proposed Deadline", value=task_data.get('new_deadline', task_data['deadline']), inline=False)
    embed.set_footer(text="Please confirm or modify the deadline below.")

    confirm_button = ui.Button(label="Confirm Deadline", style=discord.ButtonStyle.success, custom_id="confirm_deadline_button")
    modify_button = ui.Button(label="Modify Deadline", style=discord.ButtonStyle.secondary, custom_id="modify_deadline_button")

    confirmed_users = set()

    async def confirm_button_callback(interaction):
        try:
            await interaction.response.defer()  # Acknowledge the interaction
            confirmed_users.add(interaction.user.id)

            if assigner_id in confirmed_users and all(int(assignee_id) in confirmed_users for assignee_id in assignee_ids):
                task_data['deadline'] = task_data.get('new_deadline', task_data['deadline'])
                task_data['status'] = 'Confirmed'  # Ensure status is included
                await update_task_in_database(task_data)  # Update the existing task in the database

                # Edit the existing task message with the modified deadline
                await edit_task_message_with_modified_deadline(task_data, assigner_id, assignee_ids, interaction)

                await interaction.followup.send("Deadline confirmed by both parties! Task details have been updated.", ephemeral=False)
            else:
                await interaction.followup.send("Deadline confirmed. Waiting for the other party to confirm.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    async def modify_button_callback(interaction):
        try:
            await interaction.response.defer()  # Acknowledge the interaction
            await interaction.followup.send("Please enter the new deadline (DD/MM/YYYY HH:MM AM/PM):", ephemeral=True)
            new_due_date_msg = await bot.wait_for('message', check=lambda m: m.author == interaction.user and m.channel == channel)
            new_due_date = new_due_date_msg.content
            task_data['new_deadline'] = new_due_date
            confirmed_users.clear()
            embed.set_field_at(0, name="Proposed Deadline", value=new_due_date, inline=False)
            await channel.send("Deadline modified. Please confirm or modify the deadline below.", embed=embed, view=view)
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}", ephemeral=True)

    confirm_button.callback = confirm_button_callback
    modify_button.callback = modify_button_callback

    view = ui.View(timeout=None)
    view.add_item(confirm_button)
    view.add_item(modify_button)

    await channel.send(embed=embed, view=view)

async def edit_task_message_with_modified_deadline(task_data, assigner_id, assignee_ids, interaction):
    try:
        # Retrieve the pending tasks channels for both the assigner and the assignees
        assigner_channel_id, assigner_sent_task_ids, assigner_task_message_ids = retrieve_pending_tasks_channel(str(assigner_id))
        assignee_channels = [retrieve_pending_tasks_channel(str(assignee_id)) for assignee_id in assignee_ids]

        # Edit the task in the assigner's pending tasks channel
        if assigner_channel_id:
            assigner_channel = bot.get_channel(assigner_channel_id)
            if assigner_channel:
                for task_id, message_id in zip(assigner_sent_task_ids, assigner_task_message_ids):
                    if str(task_data['task_id']) == task_id:
                        message = await assigner_channel.fetch_message(int(message_id))
                        embed = discord.Embed(title=task_data['title'], color=0x00ff00)
                        channel = bot.get_channel(task_data['channel_id'])
                        channel_name = channel.name if channel else f"Channel ID {task_data['channel_id']}"
                        assignees = ', '.join(task_data['assignees'])
                        embed.add_field(name=f"Task in {channel_name}", value=f"**Assignees:** {assignees}\n**Details:** {task_data['details']}\n**Deadline:** {task_data['deadline']}", inline=False)
                        view = await handle_assigner_buttons(interaction, task_data)
                        await message.edit(embed=embed, view=view)
                        break

        # Edit the task in the assignees' pending tasks channels
        for assignee_channel_id, assignee_sent_task_ids, assignee_task_message_ids in assignee_channels:
            if assignee_channel_id:
                assignee_channel = bot.get_channel(assignee_channel_id)
                if assignee_channel:
                    for task_id, message_id in zip(assignee_sent_task_ids, assignee_task_message_ids):
                        if str(task_data['task_id']) == task_id:
                            message = await assignee_channel.fetch_message(int(message_id))
                            embed = discord.Embed(title=task_data['title'], color=0x00ff00)
                            channel = bot.get_channel(task_data['channel_id'])
                            channel_name = channel.name if channel else f"Channel ID {task_data['channel_id']}"
                            assignees = ', '.join(task_data['assignees'])
                            embed.add_field(name=f"Task in {channel_name}", value=f"**Assignees:** {assignees}\n**Details:** {task_data['details']}\n**Deadline:** {task_data['deadline']}", inline=False)
                            view = await handle_assignee_buttons(interaction, task_data)
                            await message.edit(embed=embed, view=view)
                            break

    except Exception as e:
        print(f"An error occurred while editing the task message with the modified deadline: {e}")

async def check_and_remove_invalid_tasks():
    while True:
        try:
            # Retrieve all tasks from the database
            tasks = await retrieve_all_tasks_from_database()
            task_ids_in_db = {str(task['task_id']) for task in tasks}

            # Retrieve all pending tasks channels
            conn = sqlite3.connect('tasks.db')
            cursor = conn.cursor()
            cursor.execute('SELECT user_id, tasks, task_message_ids FROM pending_tasks_channels')
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                user_id, tasks, task_message_ids = row
                tasks = tasks.split(',') if tasks else []
                task_message_ids = task_message_ids.split(',') if task_message_ids else []

                # Find tasks that are no longer in the database
                invalid_task_ids = [task_id for task_id in tasks if task_id not in task_ids_in_db]

                if invalid_task_ids:
                    # Remove invalid tasks from the user's pending tasks channel
                    channel_id, _, _ = retrieve_pending_tasks_channel(user_id)
                    if channel_id:
                        channel = bot.get_channel(channel_id)
                        if channel:
                            for task_id in invalid_task_ids:
                                if task_id in tasks:
                                    index = tasks.index(task_id)
                                    message_id = task_message_ids[index]
                                    try:
                                        message = await channel.fetch_message(int(message_id))
                                        await message.delete()
                                    except discord.NotFound:
                                        print(f"Message with ID {message_id} not found in channel {channel_id}")

                                    tasks.pop(index)
                                    task_message_ids.pop(index)

                    # Update the pending tasks channel in the database
                    update_pending_tasks_channel(user_id, tasks, task_message_ids)

        except Exception as e:
            print(f"An error occurred while checking and removing invalid tasks: {e}")

        await asyncio.sleep(60)  # Check every 60 seconds

# Run the bot
bot.run('MTI4NjMzMjU0ODg4NDA3MDQ3Mg.GkSxMK.-nkt8AJaxX-nwhQn4yGxvWo_qZPcR3UB0Xfn5A')

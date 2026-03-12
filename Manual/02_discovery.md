# 02 — Server Discovery System

## Purpose

The discovery system maintains an **always-current mirror** of the Discord server's structure inside `Database/discovery.db`. Other cogs (particularly `leave_cog.py`) query this database to resolve channel and role names to Discord IDs at runtime, eliminating hardcoded IDs.

---

## Files

| File | Role |
|---|---|
| `cogs/discovery_cog.py` | Discord event listeners that trigger DB updates |
| `Bots/db_managers/discovery_db_manager.py` | All SQLite logic for `discovery.db` |

---

## Database Schema — `discovery.db`

### `categories`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Discord category channel ID |
| `name` | TEXT | Category name |

### `channels`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Discord channel ID |
| `name` | TEXT | Channel name (e.g. `leave-application`) |
| `type` | TEXT | Channel type string (`text`, `voice`, etc.) |
| `category_id` | INTEGER FK | Parent category, nullable |

### `roles`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Discord role ID |
| `name` | TEXT | Role name (e.g. `emp`, `leave-hr`) |
| `color` | TEXT | Colour hex string |
| `position` | INTEGER | Role hierarchy position |

### `members`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Discord user ID |
| `name` | TEXT | Username |
| `display_name` | TEXT | Server nickname / display name |
| `joined_at` | TEXT | ISO timestamp of when they joined |
| `roles` | TEXT | JSON array of role name strings e.g. `["emp", "leave-hr"]` |

> **Note:** Roles are stored as a JSON array directly on the member row for simplicity. This avoids a join and supports fast LIKE-based lookups.

### `messages`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Discord message ID |
| `channel_id` | INTEGER FK | ID of the channel |
| `author_id` | INTEGER FK | ID of the author |
| `content` | TEXT | Raw string content |
| `created_at` | TEXT | ISO timestamp of the message UTC time |

### `scheduled_events`
| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Discord Event ID |
| `name` | TEXT | Event title |
| `description` | TEXT | Event string description |
| `start_time` | TEXT | ISO Event timestamp |
| `end_time` | TEXT | Nullable ISO Event end timestamp |
| `status` | INTEGER | Active vs Invalid enum status |

---

## Async Queue Architecture

`discovery_db_manager.py` uses a single-worker asyncio queue to serialise all SQLite writes:

```python
db_queue = asyncio.Queue()

async def db_worker():          # Runs as a background task
    while True:
        func, args, kwargs, future = await db_queue.get()
        result = func(*args, **kwargs)   # Synchronous SQLite call
        future.set_result(result)

async def db_execute(func, *args, **kwargs):
    future = asyncio.Future()
    await db_queue.put((func, args, kwargs, future))
    return await future          # Awaits the synchronous result
```

`db_worker()` is started in `DiscoveryCog.cog_load()` as a bot loop task. All public async functions (`upsert_member`, `upsert_channel`, etc.) wrap their synchronous counterparts through `db_execute`.

---

## Discovery Cog — Event Listeners

### `on_ready` (full sweep)
Runs once when the bot connects. Iterates all guild entities in order:
1. Categories → `upsert_category()`
2. Channels → `upsert_channel()`
3. Roles → `upsert_role()`
4. Members (via `fetch_members(limit=None)`) → `upsert_member()` **with roles**
5. Scheduled Events → `upsert_scheduled_event()`
6. **Background Sweeper**: Spawns an async queue `_sweep_messages()` which loops backwards through the top 50 messages of every text channel silently fetching missing cache data.

### Channel events
| Discord Event | Action |
|---|---|
| `on_guild_channel_create` | Upsert category or channel |
| `on_guild_channel_update` | Upsert with new name/category |
| `on_guild_channel_delete` | Delete from DB |

### Role events
| Discord Event | Action |
|---|---|
| `on_guild_role_create` | Upsert role |
| `on_guild_role_update` | Upsert with new name/color/position |
| `on_guild_role_delete` | Delete role |

### Member events
| Discord Event | Action |
|---|---|
| `on_member_join` | Upsert member (no roles yet) |
| `on_member_update` | If roles or display_name changed → upsert with current roles |
| `on_member_remove` | Delete member |

### Message & Event events
| Discord Event | Action |
|---|---|
| `on_message` | Upsert message payload |
| `on_raw_message_edit` | Fetch active message ID and upsert with new content |
| `on_raw_message_delete` | Delete message |
| `on_scheduled_event_*` | Create, update, or remove Event ID records |

---

## Key Query Functions

These are **synchronous** (not async) and safe to call directly from cog code:

```python
# Resolve names → IDs (used by leave_cog.py)
get_channel_id_by_name("leave-application")  # → int or None
get_role_id_by_name("emp")                   # → int or None

# Member role queries
get_member_roles(user_id)              # → ["emp", "leave-hr", ...]
member_has_role(user_id, "On Leave")   # → bool
get_members_with_role("On Leave")      # → [{"id":..., "display_name":..., ...}]

# Convenience status helpers
is_on_leave(user_id)        # → bool
has_submitted_dar(user_id)  # → bool
get_members_on_leave()      # → list of member dicts
get_members_dar_pending()   # → list of members who HAVEN'T submitted DAR
```

---

## How Other Cogs Use Discovery

`leave_cog.py` calls the query functions inside `resolve_leave_config()` at startup:

```python
SUBMIT_CHANNEL_ID  = discovery.get_channel_id_by_name('leave-application') or FALLBACK_ID
EMP_ROLE_ID        = discovery.get_role_id_by_name('emp')                  or FALLBACK_ID
APPROVAL_CHANNELS['hr'] = discovery.get_channel_id_by_name('leave-hr')    or FALLBACK_ID
```

This means channel renames in Discord are automatically picked up on the next bot restart without any code changes.

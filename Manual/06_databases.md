# 06 — Database Reference

## Databases

| File | Manager | Used By |
|---|---|---|
| `Database/discovery.db` | `discovery_db_manager.py` | Discovery cog, leave cog (config resolution) |
| `Database/leave.db` | `leave_db_manager.py` | Leave cog |
| `Database/task.db` | `task_db_manager.py` | Task cog |

All databases use **SQLite with WAL mode** (`PRAGMA journal_mode=WAL`) for concurrent reads.

All writes are serialised through an asyncio queue pattern (`db_execute`).

---

## `discovery.db` — Full Schema

### `categories`
```sql
CREATE TABLE categories (
    id   INTEGER PRIMARY KEY,  -- Discord category ID
    name TEXT
)
```

### `channels`
```sql
CREATE TABLE channels (
    id          INTEGER PRIMARY KEY,  -- Discord channel ID
    name        TEXT,
    type        TEXT,                 -- 'text', 'voice', 'forum', etc.
    category_id INTEGER,
    FOREIGN KEY (category_id) REFERENCES categories(id)
)
```

### `roles`
```sql
CREATE TABLE roles (
    id       INTEGER PRIMARY KEY,  -- Discord role ID
    name     TEXT,
    color    TEXT,                 -- Hex string e.g. '0x2ecc71'
    position INTEGER
)
```

### `members`
```sql
CREATE TABLE members (
    id           INTEGER PRIMARY KEY,  -- Discord user ID
    name         TEXT,                 -- Username (unique identifier)
    display_name TEXT,                 -- Server nickname
    joined_at    TEXT,                 -- ISO 8601 timestamp
    roles        TEXT DEFAULT '[]'     -- JSON array of role names
)
```

---

## `discovery_db_manager.py` — Full Function Reference

### Async write functions
```python
initialize_discovery_db()                     # Creates tables, runs migrations
upsert_category(id, name)
upsert_channel(id, name, type, category_id)
upsert_role(id, name, color, position)
upsert_member(id, name, display_name, joined_at, roles=None)
delete_category(id)
delete_channel(id)
delete_role(id)
delete_member(id)
```

### Synchronous query functions (safe to call from async code)
```python
get_channel_id_by_name(name)      # → int or None
get_role_id_by_name(name)         # → int or None
get_member_roles(member_id)       # → list[str]
member_has_role(member_id, name)  # → bool
get_members_with_role(role_name)  # → list[dict]
is_on_leave(member_id)            # → bool
has_submitted_dar(member_id)      # → bool
get_members_on_leave()            # → list[dict]
get_members_dar_pending()         # → list[dict]
```

---

## `leave.db` — Schema

Leave records are stored in **per-user tables** named after the member's sanitised display name (e.g. `john_doe`). Each table has the same structure:

```sql
CREATE TABLE {nickname} (
    leave_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    leave_type         TEXT,
    leave_reason       TEXT,
    date_from          TEXT,
    date_to            TEXT,
    number_of_days_off REAL,
    leave_status       TEXT,   -- See status values below
    approved_by        TEXT,
    footer_text        TEXT    -- Embed footer metadata for DM linkage
)
```

### Leave Status Values
| Value | Meaning |
|---|---|
| `PENDING` | Awaiting first approval |
| `Pending Second Approval` | HOD approved, waiting for HR |
| `Accepted` | HR-approved, fully active |
| `Denied` | Rejected at any stage |
| `Withdrawn` | Cancelled by employee (direct) or HR |
| `Withdrawn by HR` | Formally withdrawn by HR via `ApprovedActionsView` |
| `Withdrawal Requested` | Employee requested cancellation after HR approval |

---

## `leave_db_manager.py` — Full Function Reference

```python
# Submission
submit_leave_application(nickname, leave_details)   # → leave_id

# Approval lifecycle
confirm_leave_acceptance(nickname, leave_id, reason, days, end_date, user_id)
deny_leave(nickname, leave_id)
withdraw_leave(nickname, leave_id)
confirm_withdraw_leave(nickname, leave_id)          # HR-confirmed withdrawal
revert_cancellation_request(nickname, leave_id)     # Reverts to Accepted

# Cancellation request
request_withdraw_leave(nickname, leave_id)          # → 'Withdrawal Requested'

# Balance management
reduce_leave_balance(user_id, leave_reason, amount) # Deducts casual/sick balance
update_last_leave_date_after_withdrawal(nickname, user_id)

# Queries
get_leave_status(nickname, leave_id)        # → (reason, days_off) if Accepted
get_pending_leave_status(nickname, leave_id)# → (reason, days_off) if PENDING
get_leave_full_details(nickname, leave_id)  # → dict of all columns
get_footer_text(nickname, leave_id)         # → (footer_str,)
update_footer_text(nickname, leave_id, text)

# User queries
fetch_dynamic_user(user_id)                 # → dict {last_leave_taken, total_casual_leave, total_sick_leave}
```

---

## `task.db` — Schema Overview

Task records are managed by `task_db_manager.py`. Tasks are stored per-user similarly to leaves. Refer to `04_tasks.md` for the full breakdown.

---

## WAL Mode and Concurrency

All three databases:
- Use `PRAGMA journal_mode=WAL` — allows concurrent reads while a single write is in progress
- Set `timeout=5.0` on connection — prevents indefinite blocking if a write is contended
- Use `conn.row_factory = sqlite3.Row` — returns dict-like row objects

For `discovery.db`, all writes go through the shared `db_queue` asyncio worker.  
For `leave.db` and `task.db`, each async function creates its own connection and runs synchronous SQLite calls via `db_execute`.

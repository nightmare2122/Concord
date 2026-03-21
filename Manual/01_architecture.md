# 01 — Architecture Overview

## What is Concord?

Concord is a Discord bot built on **discord.py** that automates three operational workflows for a workspace:

1. **Leave Management** — submitting, approving, and tracking employee leave
2. **Task Management** — assigning and closing tasks through Discord private threads
3. **DAR (Daily Activity Report)** — tracking report submissions and sending reminders

---

## Directory Layout

```
Concord/
├── main.py                  # Bot entry point, cog loader, circuit breaker
├── run.sh                   # Shell launcher (activates venv, starts bot)
├── .env                     # Secret tokens + DB credentials (not committed)
├── .env.example             # Safe template committed to version control
├── requirements.txt         # Python dependencies
│
├── cogs/                    # Discord Cog modules (feature logic)
│   ├── leave_config.py      # Leave config globals + resolve_leave_config()
│   ├── leave_views.py       # All leave Discord UI (views, modals, embed helpers)
│   ├── leave_cog.py         # LeaveCog only (lifecycle, export_leave command)
│   ├── task_cog.py          # Task management (largest module)
│   ├── dar_cog.py           # DAR reporting and reminders
│   └── discovery_cog.py     # Server structure and message sync to PostgreSQL
│
├── Bots/
│   ├── config.py            # Hardcoded fallback IDs for all cogs
│   ├── utils/
│   │   └── timezone.py      # IST, now_ist(), flexible date/time parsers
│   └── db_managers/
│       ├── base_db.py       # ConnectionPool, get_conn/put_conn, db_execute, db_worker
│       ├── discovery_db_manager.py  # Discovery DB access layer
│       ├── leave_db_manager.py      # Leave DB access layer
│       └── task_db_manager.py       # Task DB access layer
│
├── Database/
│   └── DAR exports/         # Daily DAR compliance flat files (auto-created)
│
├── Logs/                    # Must exist before starting; concord_runtime.log rotates 10 MB × 5
├── Archives/                # Must exist before starting; finalized task thread archives
└── Manual/                  # This documentation folder
```

---

## Startup Sequence

```
run.sh
  └─ activates .venv
       └─ python3 main.py
            └─ ConcordBot.__init__()    # Sets intents (members + message_content)
                 └─ setup_hook()        # Loads cogs in order:
                      1. cogs.discovery_cog   ← MUST load first; sets bot.discovery_complete
                      2. cogs.task_cog
                      3. cogs.leave_cog
                      4. cogs.dar_cog
                           └─ Each cog's cog_load():
                                ├─ Starts db_worker() task
                                └─ Runs schema init (initialize_*_db)
                      └─ on_ready() fires for all cogs:
                           ├─ Discovery: full guild sweep → sets bot.discovery_complete
                           ├─ Task: awaits discovery_complete → resolve_task_config() → spawn engines
                           ├─ Leave: awaits discovery_complete → resolve_leave_config() → reattach views
                           └─ DAR: awaits bot.wait_until_ready() → starts check_role_expiry loop
```

**Critical ordering rule:** Every cog's `on_ready` must `await bot.discovery_complete.wait()` before calling its `resolve_*_config()` function. The discovery cog sets this event at the end of its initial sweep.

---

## Concurrency Model

All database operations use an **asyncio queue** pattern to prevent PostgreSQL connection contention:

```
async call  →  db_execute(fn)
                  └─ puts (fn, Future) onto db_queue
                       └─ db_worker() (background coroutine) pulls from queue
                            └─ runs fn synchronously using pool connection → resolves Future
```

- Each cog spawns one `db_worker()` task in `cog_load`; all share the single `db_queue` from `base_db`
- `ConnectionPool` (psycopg-pool) manages a global pool of PostgreSQL connections
- Always use `try/finally` with `get_conn()` / `put_conn()` — never `with get_conn() as conn:` (that leaks)
- `db_execute()` ensures sync DB closures are dispatched safely from async code

---

## Intents Required

| Intent | Why |
|---|---|
| `members` | Fetch member list, listen for join/leave/update events |
| `message_content` | Read message content for DAR channel detection |

---

## Environment Variables (`.env`)

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | — | Discord bot token — required |
| `DB_HOST` | — | PostgreSQL host |
| `DB_PORT` | — | PostgreSQL port |
| `DB_NAME` | — | PostgreSQL database name |
| `DB_USER` | — | PostgreSQL user |
| `DB_PASSWORD` | — | PostgreSQL password |
| `DB_POOL_MIN` | `2` | Minimum pool connections |
| `DB_POOL_MAX` | `20` | Maximum pool connections |
| `DB_POOL_TIMEOUT` | `30` | Pool acquire timeout (seconds) |
| `ARCHIVE_PATH` | — | Path for task archives |
| `DISABLE_TUI` | — | Set to `true` for plain stdout logging |

---

## Logging

Concord uses Python's `logging` module routed through `logging.getLogger("Concord")`. All cogs and modules use this same logger:

```python
logger = logging.getLogger("Concord")
```

Never call `logging.info()`, `logging.error()`, etc. directly — those bypass the TUI dashboard handler.

Log prefixes:
- `[Discovery]` — server structure events
- `[Leave]` — leave cog operations
- `[DAR]` — DAR reminders and role changes
- `[Task]` — task cog operations

Error code format: `[ERR-XXX-NNN]` where `XXX` is the cog code (`TSK`, `LV`, `DAR`, `DSC`, `COR`).

Log level is `INFO` by default; errors appear as `ERROR`. Runtime log: `Logs/concord_runtime.log` (rotates at 10 MB, 5 backups).

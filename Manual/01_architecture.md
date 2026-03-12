# 01 — Architecture Overview

## What is Concord?

Concord is a Discord bot built on **discord.py** that automates three operational workflows for a workspace:

1. **Leave Management** — submitting, approving, and tracking employee leave
2. **Task Management** — assigning and closing tasks through Discord
3. **DAR (Daily Activity Report)** — tracking report submissions and sending reminders

---

## Directory Layout

```
Concord/
├── main.py                  # Bot entry point, cog loader
├── run.sh                   # Shell launcher (activates venv, starts bot)
├── .env                     # Secret tokens (not committed)
├── requirements.txt         # Python dependencies
│
├── cogs/                    # Discord Cog modules (feature logic)
│   ├── leave_cog.py         # Leave management (largest module)
│   ├── task_cog.py          # Task management
│   ├── dar_cog.py           # DAR reporting and autonomous UI setup
│   └── discovery_cog.py     # Server structure and message sync to SQLite
│
├── Bots/
│   └── db_managers/
│       ├── discovery_db_manager.py  # discovery.db access layer
│       ├── leave_db_manager.py      # leave.db access layer
│       └── task_db_manager.py       # task.db access layer
│
└── Database/                # SQLite database files (auto-created)
    ├── discovery.db         # Server structure and message mirror
    ├── leave.db             # Per-user leave records
    └── task.db              # Task records
```

---

## Startup Sequence

```
run.sh
  └─ activates .venv
       └─ python3 main.py
            └─ ConcordBot.__init__()    # Sets intents (members + message_content)
                 └─ setup_hook()        # Loads all four cogs sequentially
                      ├─ cogs.task_cog
                      ├─ cogs.leave_cog
                      ├─ cogs.dar_cog
                      └─ cogs.discovery_cog
                           └─ on_ready()  # All cogs receive this event
                                └─ Discovery sweep → populates discovery.db channels, roles, and scheduled events
                                └─ Background Message Sweep → populates recent discord channel history asynchronously
                                └─ Leave cog resolves channel/role IDs
                                └─ DAR cog auto-deploys Submission UI to target channel
```

Each cog has a `cog_load()` coroutine that Discord calls immediately after the cog is added. The discovery cog uses this to start its async DB worker queue.

---

## Concurrency Model

All database operations use an **asyncio queue** pattern to prevent SQLite write conflicts:

```
async call  →  db_execute(fn, *args)
                  └─ puts (fn, args, Future) onto db_queue
                       └─ db_worker() (background task) pulls from queue
                            └─ runs fn synchronously → resolves Future
```

This ensures only one thread writes to the SQLite file at a time, keeping WAL-mode (`PRAGMA journal_mode=WAL`) reads concurrent while serialising writes.

---

## Intents Required

| Intent | Why |
|---|---|
| `members` | Fetch member list, listen for join/leave/update events |
| `message_content` | Read message content for DAR channel detection |

---

## Environment Variables (`.env`)

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Discord bot token — required to connect |

---

## Logging

Concord uses Python's `logging` module with a **Rich** terminal handler for coloured, formatted output. All log lines are prefixed with a module tag:

- `[Discovery]` — server structure events
- `[Leave]` — leave cog operations
- `[DAR]` — DAR reminders and role changes
- `[Task]` — task cog operations

Log level is `INFO` by default; errors appear as `ERROR`.

# 🤖 Concord Unified Engine
*Intelligent Architecture for Workspace Automation & Workflow Optimization*

![Python](https://img.shields.io/badge/Python-3.14+-blue.svg)
![Architecture](https://img.shields.io/badge/Architecture-Cog--Based-orange)
![Discovery](https://img.shields.io/badge/Discovery-Dynamic-success)
![Database](https://img.shields.io/badge/Database-PostgreSQL-blue)
![License](https://img.shields.io/badge/license-Proprietary-red)

---

## 📌 Overview
**Concord Unified Engine** is a modular suite of automation tools designed to manage office workflows directly within Discord.

By consolidating multiple specialized services into a single, high-performance bot architecture, Concord automates **employee leave tracking**, **task management**, and **Daily Activity Reporting (DAR)** with near-zero friction.

---

## ⚙️ Core Architecture
The project is built on a **Unified Cog System** using **discord.py**:

### 🧠 System Modules (`/cogs/`)
| Module | Function |
|---|---|
| `discovery_cog.py` | **Dynamic Discovery**: Real-time mirroring of Discord server structure and message history to PostgreSQL. |
| `leave_config.py` | **Leave Config**: All leave channel/role globals and `resolve_leave_config()` startup resolution. |
| `leave_views.py` | **Leave UI**: All Discord views, modals, and embed helpers for the leave pipeline. |
| `leave_cog.py` | **Leave Pipeline**: Cog lifecycle, 2-stage approval workflow (HOD → HR), persistent DM tracking. |
| `task_cog.py` | **Task Management**: Assignment, private threads, prioritization, and full lifecycle tracking. |
| `dar_cog.py` | **Compliance Enforcement**: DAR channel monitoring, role-reset (11:00 AM IST), and automated evening reminders. |

---

## 🛰️ The Discovery System
Concord features a **Self-Healing Configuration** model. It eliminates hardcoded Discord IDs by maintaining a live mirror of categories, channels, roles, scheduled events, and messages in PostgreSQL.

- **Runtime ID Resolution**: Channel renames or role adjustments in Discord are detected at startup.
- **Dynamic Config**: Modules like `leave_config.py` resolve their operational channels (e.g., `leave-hr`, `leave-pa`) from the database at startup.
- **In-Memory Cache**: Resolved IDs are cached in-process for zero-latency hot-path lookups.

---

## 🚀 Quick Start (Linux)
To set up the environment, install dependencies, and start the engine with a single command:

1. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env and set BOT_TOKEN, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
   ```

2. **Launch the Engine**:
   ```bash
   chmod +x run.sh
   ./run.sh
   ```
*The script automatically generates a real-time split-screen Dashboard in your terminal to view separated Cog logs cleanly without any clutter!*

---

## 📚 Documentation
For a deep dive into every specific module, database schema, and implementation history, please refer to the **[Manual/](./Manual/README.md)** folder:

- **[01 Architecture Overview](./Manual/01_architecture.md)**: Startup sequences and directory structure.
- **[02 Discovery Deep-Dive](./Manual/02_discovery.md)**: How the dynamic server mirror works.
- **[03 Leave System](./Manual/03_leave.md)**: Details of the approval and cancellation logic.
- **[04 Task System](./Manual/04_tasks.md)**: Task lifecycle, private threads, and sync engines.
- **[05 DAR System](./Manual/05_DAR.md)**: Daily Activity Report enforcement.
- **[06 Database Reference](./Manual/06_databases.md)**: Every table, schema, and API function.
- **[07 Configuration](./Manual/07_configuration.md)**: Environment variables and channel/role resolution.
- **[WALKTHROUGH.md](./Manual/WALKTHROUGH.md)**: A chronological log of every feature implementation.

---

## 🏗️ Technical Standards
- **Asynchronous Data Layer**: All PostgreSQL writes are serialized through a background `db_worker` queue (`db_execute`) to prevent concurrency conflicts. Each cog owns one `db_worker` task; all share a single `db_queue`.
- **Connection Pooling**: `psycopg-pool` connection pool (`ConnectionPool`) shared across all cogs. Always use `try/finally` with `get_conn()` / `put_conn()` — never use `with get_conn()` (leaks the connection).
- **Persistence**: Leave and task views (buttons/modals) are reconstructed from database-stored metadata to survive bot restarts. `bot.add_view()` is called for all persistent views in `on_ready`.
- **Timezone**: All timestamps use IST (UTC+5:30) via `Bots/utils/timezone.py`. Discord embed `timestamp` fields use UTC as required by Discord.
- **UX Polish**: Consistent 10-second auto-deletion for ephemeral messages to keep Discord channels clean.
- **Circuit Breaker**: 10 unhandled errors within 5 minutes triggers a pause to prevent error cascades.

---

## 🤝 Contributions
This project is **private and proprietary**. Access and modification are restricted to authorized personnel.

---

## 📄 License
This software is **Commercial/Proprietary**.
Copyright (c) 2026 Concord Desk. All rights reserved.
Unauthorized use, copying, modification, or distribution is strictly prohibited.

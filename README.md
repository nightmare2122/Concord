# 🤖 Concord Unified Engine  
*Intelligent Architecture for Workspace Automation & Workflow Optimization*  

![Python](https://img.shields.io/badge/Python-3.14+-blue.svg)  
![Architecture](https://img.shields.io/badge/Architecture-Cog--Based-orange)  
![Discovery](https://img.shields.io/badge/Discovery-Dynamic-success)
![Database](https://img.shields.io/badge/Database-SQLite%20%7C%20WAL-green)  
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
| `discovery_cog.py` | **Dynamic Discovery**: Real-time mirroring of Discord server structure and Message History to local DB. |
| `leave_cog.py` | **Leave Pipeline**: 2-stage approval workflow (HOD → HR) with persistent DM status tracking. |
| `task_cog.py` | **Task Management**: Assignment, prioritization, and lifecycle tracking. |
| `dar_cog.py` | **Compliance Enforcement**: DAR auto-panel deployment, Modal submission tracking, role-reset (11:00 AM), and automated reminders. |

---

## 🛰️ The Discovery System  
Concord features a **Self-Healing Configuration** model. It eliminates hardcoded Discord IDs by maintaining a live mirror of categories, channels, roles, scheduled events, and messages in `Database/discovery.db`.  

- **Runtime ID Resolution**: Channel renames or role adjustments in Discord are detected instantly.
- **Dynamic Config**: Modules like `leave_cog` resolve their operational channels (e.g., `leave-hr`, `leave-pa`) from the database at startup.
- **Auto-Deployment**: The bot actively queries the database on startup to identify missing operational channels (e.g. DAR tracking) and automatically injects UI forms into the Discord server if they were purged.

---

## 🚀 Quick Start (Linux)
To set up the environment, install dependencies, and start the engine with a single command:

1. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env and add your BOT_TOKEN
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
- **[06 Database Reference](./Manual/06_databases.md)**: Every table, schema, and API function.
- **[WALKTHROUGH.md](./Manual/WALKTHROUGH.md)**: A chronological log of every feature implementation.

---

## 🏗️ Technical Standards
- **Asynchronous Data Layer**: All SQLite writes are serialized through a background worker queue (`db_execute`) to prevent concurrency locks.
- **Persistence**: Leave views (buttons/modals) are reconstructed with metadata from database footers to survive bot restarts.
- **UX Polish**: Consistent 10-second auto-deletion for ephemeral messages to keep Discord channels clean.
- **CI/CD Ready**: Integrated with a Flask-based webhook listener for zero-downtime deployment.

---

## 🤝 Contributions  
This project is **private and proprietary**. Access and modification are restricted to authorized personnel.  

---

## 📄 License
This software is **Commercial/Proprietary**.  
Copyright (c) 2026 Concord Desk. All rights reserved.  
Unauthorized use, copying, modification, or distribution is strictly prohibited.

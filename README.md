# 🤖 Concord Desk  
*A lightweight CRM & workflow automation system inside Discord*  

![Python](https://img.shields.io/badge/Python-3.14+-blue.svg)  
![AWS](https://img.shields.io/badge/AWS-Lambda%20%7C%20RDS%20%7C%20EC2-orange)  
![Testing](https://img.shields.io/badge/Testing-Pytest%20%7C%20AsyncMock-success)
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Webhooks%20%7C%20CodePipeline-green)  
![License](https://img.shields.io/badge/license-MIT-lightgrey)  

---

## 📌 Overview  
**Concord Desk** is a highly modular suite of custom **Discord bots** designed as a mini-CRM for office workflows.  
The system automates **task management, leave tracking, and reporting** while ensuring seamless updates through a custom **CI/CD pipeline** backed by strictly isolated database testing architecture.  

The project is now evolving into a **cloud-native architecture** with **AWS Lambda, RDS, and CloudWatch**, combining automation with scalability and reliability.  

---

## ⚙️ Bots Included  
- **Task Bot (`Task.py`)** → Assigning, tracking, and managing tasks
- **Leave Bot (`Leave.py`)** → Managing employee leaves (supports full-day, half-day, and off-duty)
- **DAR Bot (`DAR.py`)** → Data automation & reporting *(Legacy)*

### 🏗️ Architecture & Database Modularity
To ensure 100% uptime and prevent "Database is locked" concurrency errors during peak Discord usage, the application enforces a strict **Controller-Service Model**:
- All raw SQLite queries and database connection handlers have been abstracted out of the Discord UI layer into robust managers: **`db_manager.py`** and **`leave_db_manager.py`**.
- These managers utilize `PRAGMA journal_mode=WAL;` and explicitly isolated `with get_db_conn() as conn:` context handlers to guarantee thread-safe reading and writing during asynchronous UI interactions.
- Timeouts and queue loops automatically manage high-volume events (like multiple employees submitting a leave simultaneously).

---

## 🧪 Testing & Reliability Framework
Concord Desk ships with a comprehensive Continuous Integration testing suite (`/tests/`) built on `pytest` and `pytest-asyncio`. The testing architecture guarantees that no regression bugs are pushed to production.

#### 1. Database Isolation Testing
All tests execute against explicitly patched, auto-generated `:memory:` or temporary disk databases.
- `test_db.py` and `test_leave_db.py` inject temporary environments into the data layer and run purely synchronous evaluations of the queue mathematics (e.g., ensuring `total_sick_leave` is accurately decremented).

#### 2. Async UI Mocking
Because standard Discord bot `client.run()` invocations indefinitely block unit-test runners, the application utilizes `unittest.mock.AsyncMock`.
- `test_bot.py` and `test_leave_bot.py` comprehensively simulate Discord interactions, User Modals, and Button payloads to verify expected Bot Followups and Ephemeral responses—without ever requiring a live internet connection or risking a timeout.

---

## 🚀 Features  
- Developed with **Python 3.14** within heavily optimized `.venv` virtual environments.
- **Strict Linting**: Configured with explicit `.pyre_configuration` and VSCode Workspace settings to ensure clean IDE resolution.
- **SQLite databases** acting as resilient caching layers (migration to **AWS RDS** in progress).
- **Automated deployment pipeline**:  
  - GitHub → Webhook (Flask + ngrok) → Host PC  
  - Auto-pulls code on commit  
  - Restarts bots with near-zero downtime  
- **NAS integration** for on-site secure centralized storage & remote dynamic table access (`/Database/`).
- **Cloud-native migration** utilizing AWS services.

---

## 🌩️ Cloud Migration (Ongoing)  
The project is transitioning into AWS for scalability:  

- **AWS Lambda** → Serverless execution of bots  
- **AWS RDS** → Persistent relational data storage  
- **AWS IAM** → Fine-grained security & access control  
- **AWS CloudWatch** → Monitoring, metrics & logs  
- **AWS EC2** → Compute resources for extended use cases  
- **AWS S3** → Storage for backups/logs  
- **AWS CodePipeline** → CI/CD for continuous integration & deployment  
- **Terraform (IaC)** → Automated infrastructure provisioning  

---

## 🛠️ Tech Stack  
- **Languages**: Python 3, SQL  
- **Libraries**: Boto3, Flask, Discord.py, Pytest, Pytest-Asyncio 
- **Databases**: SQLite (local with Write-Ahead Logging), AWS RDS (cloud)  
- **CI/CD**: GitHub Webhooks, ngrok (migration to AWS CodePipeline planned)  
- **Cloud & IaC**: AWS Lambda, RDS, IAM, EC2, CloudWatch, Terraform  
- **Storage**: Unix Local NAS `/home/am.k/Concord/Database/`, AWS S3  

---

## 🔄 Workflow  
1. Developer edits logic locally and verifies logic executing `pytest tests/ -v`.
2. Developer pushes changes to the **`main` branch** on GitHub.
3. **Webhook (Flask + ngrok)** notifies the host server.
4. Host server:  
   - Pulls the latest code.
   - Restarts bots automatically.  
5. (Planned) Migration to **AWS CodePipeline + Lambda** for full automation.  

---

## 📈 Skills & Concepts  
- Python **scripting & automation**  
- Building **CI/CD pipelines** (GitHub → Host → AWS)  
- **Database design & management** (SQLite → RDS)
- **Asynchronous Unit Testing (Pytest-Asyncio)**
- **Infrastructure as Code (Terraform)**  
- **Monitoring & reliability** (CloudWatch, restart scripts)  
- **DevOps practices** (Git, containerization, system automation)  
- **Cloud migration strategy**  

---

## 📚 Roadmap  
- [x] Build Python bots with databases  
- [x] Implement GitHub webhook + Flask CI/CD  
- [x] Automate deployment & restarts
- [x] Abstract all databases into isolated modular Service layers (`db_manager.py`).
- [x] Build synchronous and AsyncMock `pytest` validation suites.
- [ ] Migrate databases to **AWS RDS**  
- [ ] Deploy bots on **AWS Lambda**  
- [ ] Replace ngrok with **AWS CodePipeline**  
- [ ] Add **monitoring & alerting** with CloudWatch  
- [ ] Containerize with **Docker** & explore **ECS/EKS**  

---

## 🧩 Future Vision  
Concord Desk aims to become a **Discord-native CRM system**, integrating:  
- Task management  
- Leave approvals  
- Automated reporting  
- Cloud-native scalability (AWS)  
- Zero-downtime continuous deployment  

---

## 🤝 Contributions  
Pull requests are welcome! For major changes, please open an issue first to discuss what you’d like to change. 
When making backend PRs, ensure you execute `pytest tests/ -v` and maintain the isolated dummy-database structure intact.

---

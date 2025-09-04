# 🤖 Concord Desk  
*A lightweight CRM & workflow automation system inside Discord*  

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)  
![AWS](https://img.shields.io/badge/AWS-Lambda%20%7C%20RDS%20%7C%20EC2-orange)  
![CI/CD](https://img.shields.io/badge/CI%2FCD-GitHub%20Webhooks%20%7C%20CodePipeline-green)  
![License](https://img.shields.io/badge/license-MIT-lightgrey)  

---

## 📌 Overview  
**Concord Desk** is a suite of custom **Discord bots** designed as a mini-CRM for office workflows.  
The system automates **task management, leave tracking, and reporting** while ensuring seamless updates through a custom **CI/CD pipeline**.  

The project is now evolving into a **cloud-native architecture** with **AWS Lambda, RDS, and CloudWatch**, combining automation with scalability and reliability.  

---

## ⚙️ Bots Included  
- **DAR Bot (`DAR.py`)** → Data automation & reporting  
- **Task Bot (`task.py`)** → Assigning, tracking, and managing tasks  
- **Leave Bot (`leave.py`)** → Managing employee leaves (supports full-day & half-day)  

Each bot is backed by its **own database** for modularity and easy maintenance.  

---

## 🚀 Features  
- Developed with **Python 3** for flexibility and simplicity  
- **SQLite databases** for each bot (migration to **AWS RDS** in progress)  
- **Automated deployment pipeline**:  
  - GitHub → Webhook (Flask + ngrok) → Host PC  
  - Auto-pulls code on commit  
  - Restarts bots with near-zero downtime  
- **NAS integration** for on site secure and centralized storage & remote access  
- **Deployment scripts** for monitoring, restarts, and task automation  
- **Cloud-native migration** using AWS services  

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
- **Libraries**: Boto3, Flask, Discord.py  
- **Databases**: SQLite (local), AWS RDS (cloud)  
- **CI/CD**: GitHub Webhooks, ngrok (migration to AWS CodePipeline planned)  
- **Cloud & IaC**: AWS Lambda, RDS, IAM, EC2, CloudWatch, Terraform  
- **Storage**: NAS, AWS S3  

---

## 🔄 Workflow  
1. Developer pushes changes to the **`main` branch** on GitHub  
2. **Webhook (Flask + ngrok)** notifies the host server  
3. Host server:  
   - Pulls the latest code  
   - Restarts bots automatically  
4. (Planned) Migration to **AWS CodePipeline + Lambda** for full automation  

---

## 📈 Skills & Concepts Demonstrated  
- Python **scripting & automation**  
- Building **CI/CD pipelines** (GitHub → Host → AWS)  
- **Database design & management** (SQLite → RDS)  
- **Infrastructure as Code (Terraform)**  
- **Monitoring & reliability** (CloudWatch, restart scripts)  
- **DevOps practices** (Git, containerization, system automation)  
- **Cloud migration strategy**  

---

## 📚 Roadmap  
- [x] Build Python bots with databases  
- [x] Implement GitHub webhook + Flask CI/CD  
- [x] Automate deployment & restarts  
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

---

## 📜 License  
This project is licensed under the MIT License.  

---

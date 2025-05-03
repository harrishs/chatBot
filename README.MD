# ChatBot

A multi-tenant SaaS platform for creating AI-powered chatbots that sync with Jira and Confluence data. Built with Django (backend), React + Vite (frontend), and PostgreSQL.

## 🛠 Tech Stack

- Django + DRF (API backend)
- React + Vite (frontend UI)
- PostgreSQL (local and remote)
- Docker + Docker Compose (for unified development)

## 🚀 Getting Started

1. Copy `.env.example` to `.env` and fill in secrets
2. Run: `docker-compose up --build`
3. Visit:
   - Backend: `http://localhost:8000`
   - Frontend: `http://localhost:5173`

## 📦 Features

- Company-specific chatbot instances
- Jira + Confluence sync support
- Feedback logging on chatbot responses
- Multi-tenant architecture

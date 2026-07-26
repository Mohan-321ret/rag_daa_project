# 🎓 FinalYear Project

> **Phase 1 – AI-Powered Full-Stack Application**

A research/final-year project stack combining **FastAPI**, **LangChain**, **Sentence Transformers**, **FAISS**, **Neo4j**, **PostgreSQL**, and a **React + Vite** frontend — all orchestrated with **Docker Compose**.

---

## 📁 Project Structure

```
Finalyear_Project/
├── backend/          # Python FastAPI + AI services
├── frontend/         # React + Vite SPA
├── docs/             # Postman collection
├── docker-compose.yml
└── .gitignore
```

---

## 🚀 Quick Start

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- [Git](https://git-scm.com/)
- (Optional) [Ollama](https://ollama.com/) installed locally for GPU acceleration

### 1. Clone & Configure

```bash
git clone <your-repo-url> Finalyear_Project
cd Finalyear_Project
```

Copy the environment files and fill in your values:
```bash
copy backend\.env.example backend\.env
copy frontend\.env.example frontend\.env
```

### 2. Start All Services

```bash
docker-compose up --build
```

| Service     | URL                          |
|-------------|------------------------------|
| Backend API | http://localhost:8000/docs   |
| Frontend    | http://localhost:3000        |
| Neo4j Browser | http://localhost:7474      |
| Ollama      | http://localhost:11434       |
| PostgreSQL  | localhost:5432               |

### 3. Pull an LLM Model (Ollama)

After containers are up, pull a model:
```bash
docker exec -it fyp_ollama ollama pull llama3
```

---

## 🛠️ Development (without Docker)

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env         # Edit as needed
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
copy .env.example .env         # Edit as needed
npm run dev                    # Starts on http://localhost:3000
```

---

## 🔧 Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | `ollama` \| `openai` \| `groq` | `ollama` |
| `OLLAMA_MODEL` | Model name for Ollama | `llama3` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `GROQ_API_KEY` | Groq API key | — |
| `DATABASE_URL` | PostgreSQL connection string | see `.env.example` |
| `NEO4J_URI` | Neo4j Bolt URI | `bolt://neo4j:7687` |
| `EMBEDDING_MODEL` | Sentence Transformers model | `all-MiniLM-L6-v2` |

---

## 📮 Postman

Import `docs/api_collection.json` into Postman to get pre-built requests for all endpoints.

---

## 🗺️ Roadmap

- [x] **Phase 1** – Environment setup (FastAPI, React, PostgreSQL, FAISS, Neo4j, Ollama)
- [ ] **Phase 2** – Milvus migration, authentication, core AI pipeline
- [ ] **Phase 3** – Knowledge graph enrichment, RAG pipeline
- [ ] **Phase 4** – Evaluation, optimization, deployment

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, Uvicorn |
| AI/LLM | LangChain, Ollama, OpenAI, Groq |
| Embeddings | Sentence Transformers, HuggingFace |
| Vector DB | FAISS → Milvus (Phase 2) |
| Graph DB | Neo4j 5 |
| Relational DB | PostgreSQL 15 |
| Frontend | React, Vite, Axios |
| DevOps | Docker, Docker Compose, GitHub |
| Testing | Postman |

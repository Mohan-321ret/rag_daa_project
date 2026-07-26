/**
 * Axios API client pointing to the FastAPI backend.
 * Base URL is read from the Vite env variable VITE_API_URL.
 */
import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1",
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// ── Request interceptor (attach auth token if present) ──────────────────────
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem("token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// ── Response interceptor (global error handling) ─────────────────────────────
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("token");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export default api;

// ── Typed helpers ─────────────────────────────────────────────────────────────

/** Check backend health */
export const healthCheck = () => api.get("/health");

/** Send a prompt to the LLM */
export const generateLLM = (prompt) => api.post("/llm/generate", { prompt });

/** Embed a piece of text */
export const embedText = (text) => api.post("/embeddings/embed", { text });

/** Add a document to the vector store */
export const addDocument = (text, metadata = {}) =>
  api.post("/vectors/add", { text, metadata });

/** Semantic search */
export const searchDocuments = (query, top_k = 5) =>
  api.post("/vectors/search", { query, top_k });

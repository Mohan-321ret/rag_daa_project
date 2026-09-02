# DAA-RAG Enterprise Platform

Enterprise Dynamic Adaptive Retrieval-Augmented Generation Platform — Full Frontend

## Tech Stack

- **Next.js 14** (App Router)
- **React 18** + **TypeScript**
- **Tailwind CSS** + custom design system
- **Framer Motion** — animations
- **Recharts** — data visualization
- **Zustand** — state management
- **React Query** — data fetching
- **React Hook Form** + **Zod** — forms & validation
- **React Dropzone** — file uploads
- **next-themes** — dark/light mode

## Setup

```bash
# 1. Install dependencies
npm install

# 2. Start development server
npm run dev

# 3. Open browser
http://localhost:3000
```

The app redirects to `/dashboard` by default. Login page is at `/login`.

## Pages

| Route | Page |
|-------|------|
| `/login` | Authentication |
| `/dashboard` | Enterprise Overview |
| `/ingestion` | Knowledge Ingestion |
| `/processing` | Document Processing |
| `/evolution` | Knowledge Evolution |
| `/repository` | Knowledge Repository |
| `/query-intelligence` | Query Intelligence |
| `/retrieval` | Adaptive Retrieval |
| `/context-fusion` | Context Fusion |
| `/llm` | Enterprise LLM Chat |
| `/verification` | Evidence Verification |
| `/learning` | Continuous Learning |
| `/security` | Security & Governance |
| `/monitor` | System Monitor |
| `/query-history` | Query History |
| `/settings` | Settings |
| `/documents` | Document Details |

## Architecture

```
src/
├── app/                    # Next.js App Router pages
│   ├── (auth)/             # Auth routes (login)
│   └── (dashboard)/        # Protected dashboard routes
├── components/
│   ├── layout/             # Sidebar, Navbar, DashboardLayout
│   └── shared/             # Reusable UI components
├── data/                   # Mock data
├── lib/                    # Utilities
├── store/                  # Zustand state
└── types/                  # TypeScript interfaces
```

## Design System

- **Dark mode default** with light mode support
- Glassmorphism cards with `bg-white/[0.03]` + `border-white/[0.07]`
- Gradient accents: blue → violet → cyan
- Smooth Framer Motion animations throughout
- Responsive layout with collapsible sidebar

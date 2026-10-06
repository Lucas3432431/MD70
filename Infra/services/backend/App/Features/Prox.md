# MD70 - Arquitetura & Guia de Engenharia (v3.4)

## O que é MD70?

**MD70** é uma IA conversacional que permite gerenciar marketing e produzir criativos em escala. Funciona como um **copilot assistivo** que automatiza o cadastro, vence a síndrome da folha em branco e escala a produção de conteúdo com controle detalhado.

---

## 🏗️ Pilares da Arquitetura (Frontend & Infra)

O sistema é orquestrado via Docker (`.\MD70\App\mvp\docker-compose.yml`) e focado em resiliência de estado.

### 1. Organização de Pastas (Caminhos Relativos)
A partir da raiz (`.\MD70\App\mvp\`):
- **`./services/frontend`**: React + TS (Vite) + Tailwind + Shadcn UI.
- **`./services/backend`**: FastAPI (Python). O "cérebro" e motor de sincronização.
- **`./services/gateways`**: Nginx/Gateway (Portas 8080/8443).
- **`./services/backend/App/Features`**: Módulos de negócio (Auth, Chat, Llm, Tools).

### 2. Gestão de Estado & Polling
- **Estado via URL (`?panel=`)**: A URL é a "Fonte da Verdade" para o layout (Documentos, Calendário, Tasks).
- **Motor de Polling (`useJobPolling`)**: Controla a flag `isJobActive` e sincroniza o estado final via `getChat`.

---

## 🔐 Autenticação & Segurança

Gerenciado pelo `AuthService` com foco em persistência e revogação de sessões.

### 1. Mecanismo de Token (JWT)
- **Access Token**: 1h de duração.
- **Refresh Token**: 7 dias de duração.
- **Segurança**: Hashes de tokens salvos no DB para validação ativa.

### 2. Provedores
- **E-mail/Senha**: `bcrypt` encryption.
- **Google OAuth**: Login nativo integrado via Google Console.

---

## 🧠 Engine de IA & Processamento

O `MessageProcessor.py` coordena o fluxo entre o usuário e os modelos de linguagem.

### 1. Modelos e Fallback
- **Padrão**: **DeepSeek** (`deepseek-chat`) e **OpenAI**.
- **Enterprise**: **Vertex AI** (Google Cloud Console).
- **Vision & Imagem**: Utiliza **Ngrok** para exposição de assets locais para IAs de visão e produção de imagens.

### 2. System Prompt Estruturado (JSON Context)
O contexto é injetado como um **JSON consolidado** no System Prompt:
- **`system_prompt`**: Persona do agente.
- **`tools_instructions`**: Manual de ferramentas.
- **`user_info`**: Contexto do cliente (RAG de documentos).
- **`calendar`**: Dados de agendamento.

---

## 📊 Estrutura de Dados & Stack (Crunch)

O MD70 utiliza uma arquitetura de banco de dados híbrida para performance máxima.

### 1. Armazenamento (Dual-Layer)
- **Cloud DB (Principal)**: **Supabase** (PostgreSQL) hospedado em **Google Cloud Server**.
- **Local DB (Latência Zero)**: **SQLite3** no backend para operações de leitura e escrita imediatas.
- **Sync Engine**: Toda operação de escrita (`POST`, `PUT`, `PATCH`, `DELETE`) no SQLite é enfileirada para sincronização assíncrona com o Supabase.

### 2. Mensageria e Filas (Redis)
- **Redis**: Atua como o sistema de filas e workers central.
- **Isolamento**: Garante o isolamento de processamento de chats, execução de ferramentas (`Tools`) e sincronização de banco de dados (`DB Sync`).

---

## 🌐 Ecossistema & Integrações

- **IA**: DeepSeek, OpenAI e Vertex AI.
- **Auth**: Google Console (OAuth2).
- **Pagamentos**: **Stripe** integration.
- **Infra**: Google Cloud (Server) + Supabase (DB).
- **Tunneling**: **Ngrok** (essencial para Vision IAs acessarem assets temporários).

---

## 🎨 Frontend UI Library

O frontend é uma SPA moderna focada em UX fluida.
- **Core**: React 18 + TypeScript + Vite.
- **Styling**: **Tailwind CSS** com animações (`tailwindcss-animate`).
- **UI Components**: **Shadcn UI** (baseado em Radix UI primitives).
- **Icons**: Lucide React.
- **Data Fetching**: TanStack Query (React Query) v5.
- **Forms**: React Hook Form + Zod.

---

## 🚀 Operação & Qualidade (Fail-Fast)

### 1. AppSetup: O Gardião de Boot
O sistema executa testes obrigatórios antes de iniciar (`Hard-Stop` se falhar):
- **Infra**: Valida conectividade com **Redis**, **Supabase** e **Ngrok**.
- **Código**: `Pip Check` (valida requirements.txt).
- **Dados**: `Schema Startup` (migrações e injeções iniciais no SQLite/Supabase).
- **Config**: Validação de variáveis críticas no `.env`.

### 2. Estratégia de Testes (ZERA Global Skills)
- **`skill-diagnostic-n-debugging`**: Para análise de logs e bugs.
- **`skill-open-ticket`**: Para novas propostas técnicas.

---
**Última atualização:** 2026-04-14
**Version:** 3.4 (Hybrid DB, Redis Workers, Vertex AI & Frontend Stack)
---

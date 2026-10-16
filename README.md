# Gemini Web2API (Multi-Account Pool Edition)

An enhanced fork of [Sophomoresty/gemini-web2api](https://github.com/Sophomoresty/gemini-web2api) tailored for **Enterprise & Autonomous AI Agents (Hermes, CrewAI, AutoGen, LiteLLM)** with native support for **Multi-Account Cookie Pooling, Least-Recently-Used (LRU) Load Balancing, Persistent Session Keep-Alive, Web UI Management, and Full OpenAI-Compatible Tool Calling**.

---

## 🌟 What's New in This Fork

1. **Multi-Account Cookie Pool (SQLite Backend)**:
   - Connect multiple Google Gemini accounts under a single endpoint.
   - Label and name each account by email for seamless identification.
   - Intelligent *Least-Recently-Used (LRU)* or Round-Robin request load balancing.
   - Automatic failover: accounts encountering rate limits or quota errors are temporarily bypassed in favor of active accounts.

2. **Autonomous Keep-Alive Daemon (Prevents Cookie Expiration)**:
   - A built-in background daemon touches the Google Gemini session endpoint every **30 minutes** using dynamic `SAPISIDHASH` authorization headers.
   - Automatically catches and rotates fresh `__Secure-1PSIDTS` and `__Secure-3PSIDTS` authentication cookies to keep sessions continuously active.

3. **Modern Web UI Dashboard (ThoughtStream Editorial Design)**:
   - Clean, brutalist web interface (0px border-radius, warm neutral palette, instant Dark/Light mode toggle).
   - Protected by **Master Admin Password** (`ADMIN_PASSWORD`).
   - One-click **Update Cookie** action to refresh expired accounts without losing historical tracking.
   - Real-time account status indicators, last-used timestamps, and keep-alive health logs.

4. **Agentic Tool Calling (OpenAI Specification)**:
   - Native multi-pattern function calling parser (`tool_calls` and `finish_reason: "tool_calls"`).
   - Supports multi-turn agent execution loops (`user` -> `assistant tool_calls` -> `tool result` -> `assistant final response`).
   - Full support for both Server-Sent Events (SSE) Streaming (`stream: true`) and standard blocking responses.

---

## 🔒 Security Best Practices

1. **Cookie Confidentiality**:
   - Google authentication cookies grant access to the corresponding Google account session.
   - The SQLite database `gemini_pool.db` is stored inside the `./data` directory with strict directory permissions (`chmod 700`).
   - Always configure a strong, unique `ADMIN_PASSWORD` in your environment before deploying.
2. **Credential Sanitization**:
   - The repository includes a preconfigured `.gitignore` to ensure `cookie.txt`, SQLite databases (`*.db`), and local configuration files are never committed to version control.

---

## 📋 User Guide: How to Retrieve Your Google Gemini Cookies

End users do not need access to the server or command line. Simply open the Web UI and paste your cookies into the dashboard.

### Quick Steps to Extract Cookies (10 Seconds):

#### Option 1: Browser DevTools Network Tab (No Extensions Needed)
1. Open your browser and navigate to [https://gemini.google.com](https://gemini.google.com). Ensure you are logged in.
2. Press **F12** (or right-click anywhere and select **Inspect**) -> switch to the **Network** tab.
3. In the filter/search box, type `StreamGenerate` or `batchexecute`.
4. Send any short message in Gemini (e.g., type `hello`).
5. Click on the corresponding request in the Network list.
6. In the right panel, open the **Headers** tab and scroll down to the **Request Headers** section.
7. Locate the **`Cookie:`** line, right-click its value -> select **Copy value**.
8. Open the Gemini Pool Gateway Web UI, click **+ Add Cookie Account**, and paste into **Paste Raw Cookie String**.

#### Option 2: Browser Extension "Cookie-Editor"
1. Install the **Cookie-Editor** extension for Chrome or Firefox.
2. Open [https://gemini.google.com](https://gemini.google.com).
3. Click the Cookie-Editor icon in your toolbar -> click **Export** at the bottom -> select **Header String**.
4. Paste the copied string directly into the Web UI.

> **Auth User Index Note**:
> - Default / Primary account profile: `auth_user: 0`
> - If you use multiple Google profiles in the same browser (`gemini.google.com/u/1/app`): enter `auth_user: 1`.

---

## ⚡ One-Liner Quick Run (No Clone / No Build Needed)

Run instantly without cloning the repo:

```bash
docker run -d \
  --name gemini-web-pool \
  --restart unless-stopped \
  -p 8095:8095 \
  -v $(pwd)/data:/app/data \
  -e ADMIN_PASSWORD=ChangeMeWithStrongPassword \
  ghcr.io/swavehz/gemini-web2api:latest
```

---

## 🚀 Deployment (Docker Compose)

### 1. `docker-compose.yml`
```yaml
services:
  gemini-web-pool:
    image: ghcr.io/swavehz/gemini-web2api:latest
    container_name: gemini-web-pool
    restart: unless-stopped
    ports:
      - "0.0.0.0:8095:8095"
    volumes:
      - ./data:/app/data
    environment:
      - PORT=8095
      - HOST=0.0.0.0
      - GEMINI_POOL_DB=/app/data/gemini_pool.db
      - ADMIN_PASSWORD=ChangeMeWithStrongPassword
```

### 2. Build & Start
```bash
docker compose up -d
```

### 3. Open the Dashboard
Navigate to `http://localhost:8095` in your browser, enter your `ADMIN_PASSWORD`, and begin adding accounts to the pool.

---

## 🔌 Client Integration Example (OpenAI Python SDK)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8095/v1",
    api_key="ChangeMeWithStrongPassword" # or your configured Bearer token
)

response = client.chat.completions.create(
    model="gemini-4-argon",
    messages=[{"role": "user", "content": "Hello Gemini!"}],
    stream=False
)
print(response.choices[0].message.content)
```

---

## 📄 License
MIT License - Continuing the original open-source work by Sophomoresty.

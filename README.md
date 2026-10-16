# Gemini Web2API (Multi-Account Pool Edition)

Fork yang disempurnakan dari [Sophomoresty/gemini-web2api](https://github.com/Sophomoresty/gemini-web2api) untuk kebutuhan **Enterprise & Autonomous AI Agents (Hermes, CrewAI, AutoGen, LiteLLM)** dengan dukungan **Multi-Account Cookie Pool, Least-Recently-Used (LRU) Load Balancing, Persistent Session Keep-Alive, dan Web UI Manajemen Akun**.

---

## 🌟 Fitur Baru pada Fork Ini

1. **Multi-Account Cookie Pool (SQLite)**:
   - Tambahkan banyak akun Google Gemini dalam satu instance.
   - Penamaan akun dengan format email & label kustom untuk memudahkan identifikasi.
   - Rotasi otomatis *Least-Recently-Used (LRU)* atau Round-Robin di setiap request.
   - Otomatis melewati (failover) akun yang terkena limit/error ke akun aktif berikutnya.

2. **Autonomous Keep-Alive Daemon (Mencegah Cookie Mati)**:
   - Daemon background otomatis mengirim probe setiap **30 menit** ke endpoint Google dengan header signature `SAPISIDHASH`.
   - Mengambil rotasi token `__Secure-1PSIDTS` dan `__Secure-3PSIDTS` baru secara berkala sehingga session login tetap hidup tanpa perlu copy-paste cookie berulang kali.

3. **Web UI Manajemen Akun (ThoughtStream Design System)**:
   - Antarmuka web mandiri yang bersih, tanpa border-radius (0px), palet warm neutral/charcoal, serta dukungan Dark/Light mode instan.
   - Dilindungi **Master Password Admin** (`ADMIN_PASSWORD`).
   - Formulir tambah akun & fitur **Update Cookie** untuk memperbarui cookie akun kapan saja tanpa menghapus history.
   - Monitoring live status akun, timestamp terakhir digunakan (*Last Used*), dan timestamp keep-alive.

4. **Full Agentic Tool Calling (OpenAI Specification)**:
   - Parsing otomatis parameter fungsi / function call (`tool_calls` dan `finish_reason: "tool_calls"`).
   - Mendukung loop multi-turn percakapan agent (`user` -> `assistant tool_calls` -> `tool result` -> `assistant answer`).
   - Mendukung SSE Streaming (`stream: true`) maupun standard non-streaming.

---

## 🔒 Panduan Keamanan (Security First)

1. **JANGAN Expose Port Backend ke Internet Publik**:
   - Di `docker-compose.yml`, container dibatasi hanya mengikat localhost (`127.0.0.1`), subnet Docker bridge (`172.17.0.1`), atau reverse proxy.
   - Jika ingin diakses melalui domain publik, wajib menggunakan Reverse Proxy (Nginx / Cloudflare Tunnel) dengan proteksi SSL dan autentikasi.
2. **Kerahasiaan Cookie**:
   - Cookie Google menyimpan akses penuh ke akun Google Anda. Database `gemini_pool.db` disimpan di direktori `./data` dengan permission ketat (`chmod 700`).
   - Selalu atur `ADMIN_PASSWORD` yang kuat di environment variable sebelum menjalankan container.
3. **Penyaringan Kredensial**:
   - Jangan pernah melakukan commit file `cookie.txt`, `gemini_pool.db`, atau kredensial rahasia ke repositori Git.

---

## 📋 Panduan untuk User: Cara Mengambil Cookie dari Google Gemini

User tidak perlu mengedit file konfigurasi di server. Cukup buka Web UI dan masukkan cookie melalui form.

### Langkah Cepat Mengambil Cookie (10 Detik):

#### Cara 1: Menggunakan DevTools Network (Tanpa Install Ekstensi)
1. Buka browser dan buka [https://gemini.google.com](https://gemini.google.com). Pastikan Anda sudah login.
2. Tekan tombol **F12** (atau klik kanan -> **Inspect**) -> pilih tab **Network**.
3. Di kotak filter/search tab Network, ketik `StreamGenerate` atau `batchexecute`.
4. Kirim chat apa saja di Gemini (misal ketik `halo`).
5. Klik baris request yang muncul di tab Network.
6. Buka tab **Headers** di panel kanan, scroll ke bawah ke bagian **Request Headers**.
7. Cari baris **`Cookie:`**, klik kanan pada teks nilainya -> pilih **Copy value**.
8. Buka Web UI Gemini Pool Gateway, klik **+ Add Cookie Account**, lalu paste ke kolom **Paste Raw Cookie String**.

#### Cara 2: Menggunakan Ekstensi Browser "Cookie-Editor"
1. Pasang ekstensi **Cookie-Editor** di Chrome / Firefox.
2. Buka tab [https://gemini.google.com](https://gemini.google.com).
3. Klik ikon Cookie-Editor di browser -> klik tombol **Export** -> pilih **Header String**.
4. Paste string tersebut langsung ke Web UI.

> **Catatan Auth User Index**:
> - Akun profil pertama (default): `auth_user: 0`
> - Jika menggunakan fitur switch account Google di satu browser (`gemini.google.com/u/1/app`): isi `auth_user: 1`.

---

## 🚀 Cara Menjalankan dengan Docker Compose

### 1. Konfigurasi `docker-compose.yml`
```yaml
services:
  gemini-web-pool:
    build: .
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
      - ADMIN_PASSWORD=GantiDenganPasswordKuatAnda
```

### 2. Build & Jalankan
```bash
docker compose up -d --build
```

### 3. Akses Dashboard
Buka `http://localhost:8095` di browser Anda, masukkan `ADMIN_PASSWORD`, dan mulai tambahkan akun.

---

## 🔌 Contoh Integrasi Client (OpenAI SDK / LiteLLM / Hermes Agent)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8095/v1",
    api_key="GantiDenganPasswordKuatAnda" # atau Bearer token Anda
)

response = client.chat.completions.create(
    model="gemini-4-argon",
    messages=[{"role": "user", "content": "Halo Gemini!"}],
    stream=False
)
print(response.choices[0].message.content)
```

---

## 📄 Lisensi
MIT License - Melanjutkan lisensi proyek asli oleh Sophomoresty.

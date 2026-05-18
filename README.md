# Macro Tracker Bot 🤖🥗

Personal Telegram bot untuk tracking makronutrisi harian. Analisis makanan via foto atau teks menggunakan GPT-4o-mini vision dengan estimasi setara ahli gizi klinis.

## Fitur

- 📸 **Foto → Analisis otomatis** — kirim foto makanan, langsung dapat estimasi kalori, protein, karbo, lemak, serat
- 📝 **Teks → Estimasi manual** — deskripsikan makanan, AI akan menghitung
- 📊 **Daily tracking** — rekap total harian vs. target
- 📅 **Riwayat 7 hari** — pantau konsistensi mingguan
- 🎯 **Custom target** — set target kalori & makro sesuai kebutuhan
- 🔒 **Single-user** — hanya kamu yang bisa menggunakan bot ini

---

## Setup & Instalasi

### 1. Clone & Install

```bash
git clone <repo-url>
cd macro-bot
pip install -r requirements.txt
```

### 2. Konfigurasi Environment

```bash
cp .env.example .env
```

Edit `.env` dan isi semua variabel:

| Variable | Cara Mendapatkan |
|---|---|
| `OPENAI_API_KEY` | https://platform.openai.com/api-keys |
| `TELEGRAM_BOT_TOKEN` | Chat @BotFather di Telegram → `/newbot` |
| `TELEGRAM_WEBHOOK_SECRET` | Generate: `python -c "import secrets; print(secrets.token_hex(16))"` |
| `MY_TELEGRAM_USER_ID` | Chat @userinfobot di Telegram → lihat `Id:` |
| `RAILWAY_PUBLIC_URL` | Isi setelah deploy (lihat langkah deploy) |

### 3. Jalankan Lokal (opsional, untuk testing)

> Untuk mode webhook lokal, gunakan [ngrok](https://ngrok.com):
> ```bash
> ngrok http 8000
> # Salin URL https dari ngrok → isi ke RAILWAY_PUBLIC_URL di .env
> uvicorn main:app --host 0.0.0.0 --port 8000 --reload
> ```

---

## Deploy ke Railway

### Langkah-langkah:

**1. Push ke GitHub**
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin <github-repo-url>
git push -u origin main
```

**2. Buat project di Railway**
- Buka https://railway.app → **New Project** → **Deploy from GitHub repo**
- Pilih repo ini

**3. Set Environment Variables**
- Di Railway dashboard → tab **Variables**
- Tambahkan semua variabel dari `.env.example` (kecuali `RAILWAY_PUBLIC_URL`)
- Railway akan set `PORT` secara otomatis

**4. Deploy & Dapatkan URL**
- Setelah deploy berhasil → tab **Settings** → **Domains** → **Generate Domain**
- Salin URL (contoh: `https://macro-bot-xxx.up.railway.app`)

**5. Set RAILWAY_PUBLIC_URL**
- Tambahkan variabel `RAILWAY_PUBLIC_URL` = URL yang baru disalin
- Railway akan otomatis restart → webhook terdaftar ke Telegram

**6. Test**
- Buka Telegram → cari bot kamu → kirim `/start`
- Cek health: `GET https://macro-bot-xxx.up.railway.app/health`

---

## Cara Pakai

### Commands

| Command | Fungsi |
|---|---|
| `/start` atau `/help` | Tampilkan menu |
| `/total` | Rekap makro hari ini |
| `/history` | Riwayat 7 hari terakhir |
| `/delete` | Hapus entry terakhir |
| `/reset` | Hapus semua entry hari ini (konfirmasi dulu) |
| `/target` | Lihat target harian |
| `/target 2200 160 220 70` | Set target baru (kalori protein karbo lemak) |

### Shortcut Tanpa Slash

Ketik langsung: `total`, `rekap`, `history`, `riwayat`, `hapus`, `help`, `bantuan`

### Kirim Makanan

**Via foto:**
- Kirim foto makanan (caption opsional untuk konteks)

**Via teks:**
- Ketik nama makanan: `nasi goreng ayam 1 porsi + es teh manis`

---

## Arsitektur

```
main.py          FastAPI + lifespan + webhook endpoint
bot.py           PTB Application singleton + handler registration
commands.py      Semua command & message handlers + formatter
ai_analyzer.py   GPT-4o-mini vision/text analysis
database.py      SQLAlchemy async models + CRUD
config.py        pydantic-settings + timezone constant
```

**Database:** SQLite (`macro_bot.db`) via aiosqlite — Railway volume persist data selama service aktif.

**Timezone:** Semua data disimpan UTC, ditampilkan dalam WITA (Asia/Makassar, UTC+8).

---

## Catatan Teknis

- Bot berjalan via **webhook**, bukan polling — lebih efisien untuk Railway
- Proses AI di-offload via `asyncio.create_task()` agar webhook response <1s
- Deduplikasi via `update_id` UNIQUE — aman dari Telegram double-send
- Gambar diproses **in-memory**, tidak disimpan ke disk

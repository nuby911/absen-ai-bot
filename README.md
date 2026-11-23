# SmartSchool AI — Sistem Presensi Wajah Kiosk & Chatbot WhatsApp Orang Tua

Sistem informasi presensi sekolah terpadu berbasis **Face Recognition + Liveness Detection (kedipan mata)** dan **Asisten AI WhatsApp Orang Tua**. Proyek ini dibangun sebagai monorepo yang terdiri dari layanan **Backend API (FastAPI)**, **Web Admin Dashboard (Next.js)**, dan **Mobile App Guru & Mode Kiosk (Flutter)**.

---

## 1. Arsitektur Monorepo

```text
smart-school-attendance/
├── backend/                 # FastAPI, SQLAlchemy Async, Face Engine, WAHA & Gemini Chatbot
│   ├── app/
│   │   ├── main.py          # Entrypoint FastAPI + static /uploads
│   │   ├── config.py        # Konfigurasi environment (pydantic-settings)
│   │   ├── models.py        # 12 tabel ORM (users, classes, parents, students, schedules,
│   │   │                    #   face_embeddings, attendance_sessions, attendances,
│   │   │                    #   leave_requests, face_recognition_logs, chatbot_logs, system_settings)
│   │   ├── routers/         # auth, admin, attendance, leaves, webhook
│   │   ├── providers/       # FaceEngine (InsightFace/auto), WhatsApp (WAHA/mock), LLM (Gemini/fallback)
│   │   ├── services/        # Orkestrator Chatbot & evaluasi metrik
│   │   └── seed.py          # Seeder data demo idempoten
│   └── tests/               # Pytest suite
├── web_admin/               # Next.js 16 + Tailwind CSS v4 (Dashboard Admin, Dataset Wajah, Evaluasi)
│   └── src/app/
│       ├── page.tsx         # Ringkasan & manajemen kelas/guru/jadwal
│       ├── login/           # Login Admin
│       ├── students/        # CRUD Siswa & Orang Tua
│       ├── faces/           # Registrasi Dataset Wajah (maks. 5 slot foto/siswa)
│       └── evaluation/      # Confusion Matrix FAR/FRR, Latency, Chatbot Logs & Ekspor CSV
├── mobile_guru/             # Flutter 3 (Android/iOS) — Aplikasi Guru & Mode Kiosk Hands-Free
│   ├── lib/
│   │   ├── core/            # Theme, Formatters WIB, ApiClient (Dio + SecureStorage)
│   │   ├── models/          # Data models sesuai skema backend
│   │   ├── services/        # BlinkLivenessDetector (open -> closed -> open + cooldown 2.5 dtk)
│   │   ├── widgets/         # KioskPinSheet (modal PIN 4–6 digit)
│   │   └── screens/         # Login, Home, SessionDetail, KioskScanner, LeaveVerification
│   └── test/                # Unit & widget tests (liveness, kiosk PIN lock, leave verification)
├── docker-compose.yml       # Orkestrasi PostgreSQL 16 + WAHA + FastAPI Backend
└── .env.example             # Template variabel lingkungan
```

### Alur Kerja Utama
1. **Admin (`web_admin`)** mengelola data guru, kelas, siswa, orang tua, jadwal pelajaran, serta mendaftarkan hingga 5 foto dataset wajah per siswa (`/faces`).
2. **Guru (`mobile_guru`)** login, mengatur PIN Kiosk (4–6 digit), membuka sesi presensi kelas/gerbang, dan mengaktifkan **Mode Kiosk Hands-Free** yang terkunci dengan `PopScope(canPop: false)`.
3. **Siswa** menghadap kamera depan Kiosk dan berkedip sekali (`BlinkLivenessDetector` memvalidasi anti-spoofing foto statis). Foto dikirim ke `POST /api/v1/attendance/scan`, dicatat sebagai `Hadir`/`Terlambat`, dan memicu notifikasi WhatsApp otomatis ke orang tua melalui WAHA.
4. **Orang Tua** berinteraksi dengan **Chatbot AI WhatsApp** (`POST /api/v1/webhook/whatsapp`) untuk menanyakan kehadiran hari ini, melihat jadwal pelajaran, atau mengajukan izin/sakit beserta lampiran surat dokter.
5. **Guru** memverifikasi izin masuk pada tab **Verifikasi Izin** (`PATCH /api/v1/leave-requests/{id}/verify`) yang langsung menyinkronkan data sesi dan mengirim konfirmasi WhatsApp ke orang tua.

---

## 2. Prasyarat Sistem

- **Docker & Docker Compose** (untuk menjalankan PostgreSQL, WAHA, dan Backend secara terisolasi)
- **Python 3.10+** & **`uv`** (opsional jika menjalankan backend secara lokal tanpa Docker)
- **Node.js 20+** & **npm** (untuk Web Admin Next.js)
- **Flutter SDK 3.x** & Android Studio / Emulator / Perangkat Android fisik (untuk Mobile App Guru)

---

## 3. Menjalankan Backend + PostgreSQL + WAHA via Docker Compose

1. Salin berkas template environment di root repositori:
   ```bash
   cp .env.example .env
   ```
   *(Di PowerShell Windows: `Copy-Item .env.example .env`)*

2. Sesuaikan variabel pada `.env` jika diperlukan:
   - `WHATSAPP_PROVIDER_MODE=mock` (ubah ke `waha` jika sudah menghubungkan sesi WhatsApp QR di WAHA)
   - `WAHA_WEBHOOK_SECRET=` (opsional namun direkomendasikan di produksi; jika diisi, setiap request `POST /api/v1/webhook/whatsapp` wajib menyertakan header `X-Webhook-Secret` yang cocok)
   - `LLM_PROVIDER_MODE=fallback` (ubah ke `gemini` dan isi `GEMINI_API_KEY` untuk respons LLM Gemini aktif)
   - `FACE_SIMILARITY_THRESHOLD=0.55`
   - `FACE_ENGINE_MODE=auto` *(untuk pengujian ilmiah/produksi dengan model ONNX InsightFace asli, pasang ekstra ML dan set `FACE_ENGINE_MODE=insightface` — lihat catatan di bawah)*

3. Jalankan seluruh service Docker (`postgres`, `waha`, `backend`):
   ```bash
   docker compose up --build -d
   ```
   Layanan akan aktif pada port lokal:
   - **Backend FastAPI**: `http://localhost:8000` (Swagger UI: `http://localhost:8000/docs`, Health: `http://localhost:8000/health`)
   - **PostgreSQL 16**: `localhost:5432` (database: `smart_school_attendance`)
   - **WAHA WhatsApp Gateway**: `http://localhost:3000`

4. *(Alternatif tanpa Docker)* Menjalankan backend secara lokal dengan SQLite/PostgreSQL:
   - **Mode pengembangan/demo ringan** (menggunakan `DeterministicFaceEngine` tanpa bobot ONNX):
     ```bash
     cd backend
     uv sync
     uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
     ```
   - **Mode InsightFace asli (wajib untuk evaluasi FAR/FRR ilmiah & produksi):**
     Pasang dependensi opsional grup `ml` (`insightface` + `onnxruntime`) dan tetapkan `FACE_ENGINE_MODE=insightface` agar backend benar-benar memakai model pengenalan wajah InsightFace (`buffalo_l`), bukan jatuh kembali (*fallback*) ke `DeterministicFaceEngine`:
     ```bash
     cd backend
     uv sync --extra ml
     FACE_ENGINE_MODE=insightface uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
     ```
     *(Di PowerShell Windows: `$env:FACE_ENGINE_MODE="insightface"; uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`)*

---

## 4. Mengisi Data Demo (`python -m app.seed`)

Seeder bersifat **idempoten** (aman dijalankan berulang kali tanpa menduplikasi data).

- **Jika Backend berjalan via Docker Compose:**
  ```bash
  docker compose exec backend python -m app.seed
  ```
- **Jika Backend berjalan secara lokal di folder `backend/`:**
  ```bash
  cd backend
  uv run python -m app.seed
  ```

### Daftar Akun Demo & Kredensial Default

| Peran | Nama | Email | NIP | Kata Sandi | PIN Kiosk |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Admin** | Admin Sekolah | `admin@sekolah.sch.id` | `198001012010011001` | `admin123` | - |
| **Guru** | Ibu Sari Wulandari, S.Pd | `sari.wulandari@sekolah.sch.id` | `198901012015032001` | `guru123` | `1234` |
| **Guru** | Bapak Budi Hartono, M.Pd | `budi.hartono@sekolah.sch.id` | `198504122012011002` | `guru123` | `1234` |
| **Guru** | Ibu Dewi Anggraini, S.Pd | `dewi.anggraini@sekolah.sch.id` | `199008202016032003` | `guru123` | `1234` |
| **Guru** | Bapak Dwi Handoko, M.T.I | `dwi.handoko@sekolah.sch.id` | `198711052014021004` | `guru123` | `1234` |

Data demo yang ikut dibuat oleh seeder:
- 4 kelas (`XI IPA 1`, `XI IPA 2`, `XI IPS 1`, `XII IPA 1`) dan 8 siswa beserta akun orang tua.
- Sampel embedding wajah awal untuk 5 siswa kelas `XI IPA 1`.
- 1 sesi presensi aktif hari ini (`XI IPA 1 — Pemrograman Mobile`) beserta catatan hadir/terlambat awal.
- 2 pengajuan izin menunggu verifikasi (`Septi Cahyaningtias` - Sakit, `Ahmad Fauzi` - Izin).
- 8 log evaluasi pengenalan wajah (`TP`, `FP`, `FN`, `TN`) dan 4 log interaksi chatbot untuk halaman Evaluasi.

---

## 5. Menjalankan Web Admin (Next.js)

1. Masuk ke folder `web_admin` dan salin konfigurasi environment:
   ```bash
   cd web_admin
   cp .env.local.example .env.local
   ```
   Pastikan `NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`.

2. Pasang dependensi dan jalankan server pengembangan:
   ```bash
   npm install
   npm run dev
   ```
   > **Catatan Port:** Jika service **WAHA** sedang aktif pada port `3000` di Docker Compose, jalankan Next.js pada port `3001`:
   > ```bash
   > npm run dev -- -p 3001
   > ```

3. Buka browser ke `http://localhost:3000` (atau `http://localhost:3001`) lalu login menggunakan akun demo Admin (`admin@sekolah.sch.id` / `admin123`).

---

## 6. Menjalankan Mobile App Guru (Flutter)

1. Masuk ke folder `mobile_guru` dan ambil paket Flutter:
   ```bash
   cd mobile_guru
   flutter pub get
   ```

2. Jalankan aplikasi dengan parameter `--dart-define=API_BASE_URL` sesuai perangkat target:
   - **Android Emulator** (mengakses localhost host machine melalui `10.0.2.2`):
     ```bash
     flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1
     ```
   - **Perangkat Android Fisik** (dalam satu jaringan Wi-Fi dengan laptop/server):
     ```bash
     flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000/api/v1
     ```
     *(Ganti `192.168.1.10` dengan IP lokal laptop Anda. Alamat server juga dapat diubah langsung saat runtime melalui tombol **Server** di layar Login atau kartu **Konfigurasi Server API** pada tab **Profil & PIN**).*

3. Masuk menggunakan akun demo Guru (`sari.wulandari@sekolah.sch.id` / `guru123`, PIN Kiosk `1234`, atau tekan tombol **"Isi Akun Demo Ibu Sari"** di layar Login).

---

## 7. Pengambilan Data Confusion Matrix (FAR/FRR) & Latency untuk Bab Pengujian Laporan

Sistem menyediakan instrumen evaluasi ilmiah bawaan pada tabel `face_recognition_logs` dan `chatbot_logs` yang terhubung ke halaman **Evaluasi & Laporan** di Web Admin (`/evaluation`).

### Prasyarat Engine Pengenalan Wajah untuk Pengujian Ilmiah
> **Penting:** Secara bawaan, `uv sync` tidak memasang paket ML (`insightface` dan `onnxruntime`), sehingga `FACE_ENGINE_MODE=auto` akan otomatis jatuh kembali ke `DeterministicFaceEngine` (hanya untuk pengujian unit/demo offline). Sebelum mengambil data Confusion Matrix (**FAR/FRR**) dan latensi untuk bab pengujian laporan, pastikan Anda memasang ekstra ML dan mengunci mode InsightFace asli:
> ```bash
> cd backend
> uv sync --extra ml
> ```
> Lalu atur `FACE_ENGINE_MODE=insightface` pada berkas `.env` (atau environment variable server) agar evaluasi benar-benar mengukur performa model **InsightFace** (`buffalo_l` ONNX), bukan `DeterministicFaceEngine`.

### Langkah Pengambilan Data Pengujian Pengenalan Wajah
1. **Jalankan skenario uji Kiosk** (melalui Mode Kiosk Flutter atau endpoint `POST /api/v1/attendance/scan`), termasuk variasi kondisi pencahayaan/kacamata dan sampel uji **impostor** (wajah tidak terdaftar / foto cetak). Opsional: kirim parameter form `condition_note` (mis. `pencahayaan_redup`, `kacamata`, `jarak_1m`).
2. **Beri label ground-truth pada log hasil scan** melalui halaman Web Admin **`/evaluation`** (tombol **Beri Label** pada tabel *Log Pengenalan Wajah*) atau API `POST /api/v1/evaluation/face-logs/{log_id}/label`:
   - Pilih siswa sebenarnya (`actual_student_id`) untuk sampel siswa terdaftar -> sistem mengklasifikasikan otomatis ke **TP** (cocok & benar), **FP** (cocok ke siswa yang salah), atau **FN** (tidak dikenali).
   - Tandai sebagai **Impostor** (`is_impostor: true`) untuk penguji non-siswa -> sistem mengklasifikasikan ke **FP** (lolos sebagai siswa) atau **TN** (ditolak dengan benar).
3. **Atur Threshold Cosine Similarity** (`0.30` – `0.85`, default `0.55`) langsung dari slider di halaman `/evaluation` (`PUT /api/v1/settings/face-threshold`) untuk menguji kurva perbandingan **FAR vs FRR** pada berbagai nilai ambang batas.
4. **Catat Metrik Evaluasi** yang dihitung otomatis oleh `GET /api/v1/evaluation/metrics`:
   - **Confusion Matrix**: `TP`, `FP`, `FN`, `TN`
   - **Accuracy**: `(TP + TN) / (TP + FP + FN + TN) × 100%`
   - **False Acceptance Rate (FAR)**: `FP / (FP + TN) × 100%`
   - **False Rejection Rate (FRR)**: `FN / (FN + TP) × 100%`
   - **Rata-rata Latency Scan**: `avg_scan_latency_ms` (ms)
   - **Metrik Chatbot AI**: `total_messages`, `in_domain_rate`, `fallback_rate`, dan `avg_latency_ms`
5. **Ekspor Rekap Presensi CSV** untuk lampiran laporan menggunakan tombol **Ekspor CSV** pada halaman `/evaluation` atau langsung melalui endpoint `GET /api/v1/reports/attendance.csv` (menghasilkan berkas `rekap-absensi.csv` berformat UTF-8).

---

## 8. Pengujian Otomatis (Verification Commands)

- **Backend (Pytest):**
  ```bash
  cd backend
  uv run pytest
  ```
- **Web Admin (TypeScript, ESLint, Production Build):**
  ```bash
  cd web_admin
  npx tsc --noEmit && npm run lint && npm run build
  ```
- **Mobile Guru (Flutter Analyzer & Widget/Unit Tests):**
  ```bash
  cd mobile_guru
  flutter analyze
  flutter test
  ```

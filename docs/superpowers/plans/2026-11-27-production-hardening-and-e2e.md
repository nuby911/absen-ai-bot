# SmartSchool AI Production Hardening & E2E Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate latent production blockers across the FastAPI backend, Docker/Next.js deployment stack, and Android release configuration, and verify every end-to-end write flow before release.

**Architecture:** Harden each layer independently without breaking existing dev/test ergonomics: (1) fix dialect-aware SQL schema sync and writable InsightFace cache paths in `backend/`, (2) add opt-in ML containerization and standalone `web_admin` containerization to `docker-compose.yml`, (3) support externalized `key.properties` Android release signing in `mobile_guru/`, and (4) run an automated full-stack write-flow E2E verification across live services.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (SQLite/PostgreSQL), InsightFace + ONNXRuntime, Next.js 16 (standalone), Flutter 3.47 + Gradle Kotlin DSL, Docker Compose, Playwright.

**Spec:** `D:\Project\smart-school-attendance\PRODUCTION_CHECKLIST.pdf` (derived from codebase audit of `backend/`, `web_admin/`, and `mobile_guru/`).

## Global Constraints

- Preserve all existing passing tests (`backend`: 62 passed, `mobile_guru`: 40 passed) and existing API contracts (`/health` must continue returning `{"status": "ok"}`).
- Keep default local dev startup fast: SQLite zero-config dev mode and `FACE_ENGINE_MODE=auto` fallback must continue working without requiring InsightFace wheels or Android release keystores to be present locally.
- Never commit `.jks`, `.keystore`, `key.properties`, `.env`, or dummy E2E test records into Git or `smart_school.db`.
- All user-facing error messages and UI text remain in clear, polite Indonesian.

## Review Focus

- `sync_schema_columns` on PostgreSQL (`dialect.name == "postgresql"`): boolean scalar defaults (`True`/`False`) must compile to `DEFAULT TRUE` / `DEFAULT FALSE`, NOT `DEFAULT 1` (which fails on PostgreSQL).
- `InsightFaceEngine` inside non-root Docker container (`appuser` created with `--no-create-home`): `FaceAnalysis` must receive a writable `root` directory (`INSIGHTFACE_HOME`) instead of falling back to unwritable `~/.insightface`.
- Docker `web_admin` build-time env: `NEXT_PUBLIC_API_URL` must be injected as a Docker `ARG`/`ENV` before `next build`, and `next.config.ts` must keep `cacheComponents`/`partialPrefetching` disabled.
- `mobile_guru` release build without `key.properties`: `android/app/build.gradle.kts` must still allow local debug/CI builds cleanly while using `release` signing whenever `android/key.properties` exists.
- E2E write verification must clean up all created records (teachers, students, parents, faces, leaves, sessions) so `smart_school.db` returns to clean demo state.

---

### Task 1: Fix Dialect-Aware Schema Sync, Writable `insightface_home`, and DB Readiness Endpoint (`backend`)

**Files:**
- Modify: `backend/app/database.py:22-62`
- Modify: `backend/app/config.py:29-43`
- Modify: `backend/app/providers/face_engine.py:235-324`
- Modify: `backend/app/main.py:121-124`
- Test: `backend/tests/test_database_sync.py` (Create)

**Interfaces:**
- Consumes: `Settings` (`backend/app/config.py`), `Base` (`backend/app/database.py`).
- Produces:
  - `format_column_default_sql(column: Column[Any], dialect_name: str) -> str`
  - `Settings.insightface_home: str` (default `""`, meaning `<upload_dir>/.insightface` or env `INSIGHTFACE_HOME`)
  - `InsightFaceEngine(..., root_dir: str | None = None)`
  - `GET /health/ready` returning `{"status": "ok", "database": "ok"}` (or HTTP 503 on DB error).

- [ ] **Step 1: Write failing tests in `backend/tests/test_database_sync.py`**

```python
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Boolean, Column, MetaData, String, Table, create_engine
from sqlalchemy.dialects import postgresql

from app.config import Settings
from app.database import format_column_default_sql, sync_schema_columns
from app.main import create_app
from app.providers.face_engine import InsightFaceEngine, create_face_engine


def test_format_boolean_default_for_postgresql_and_sqlite() -> None:
    meta = MetaData()
    tbl = Table(
        "sample",
        meta,
        Column("is_active", Boolean, nullable=False, default=True),
        Column("is_impostor", Boolean, nullable=True, default=False),
        Column("note", String(50), nullable=True),
    )
    assert format_column_default_sql(tbl.c.is_active, "postgresql") == " DEFAULT TRUE"
    assert format_column_default_sql(tbl.c.is_impostor, "postgresql") == " DEFAULT FALSE"
    assert format_column_default_sql(tbl.c.is_active, "sqlite") == " DEFAULT 1"
    assert format_column_default_sql(tbl.c.is_impostor, "sqlite") == " DEFAULT 0"
    assert format_column_default_sql(tbl.c.note, "postgresql") == ""


def test_sync_schema_columns_adds_missing_columns_in_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, "
            "email VARCHAR(255) NOT NULL, password_hash TEXT NOT NULL, role VARCHAR(20) NOT NULL, "
            "nip VARCHAR(50), kiosk_pin_hash TEXT, created_at DATETIME NOT NULL)"
        )
        sync_schema_columns(conn)
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()]
        assert "is_active" in cols
    engine.dispose()


def test_create_face_engine_passes_insightface_home(tmp_path) -> None:
    cfg = Settings(face_engine_mode="insightface", insightface_home=str(tmp_path / "models"))
    engine = create_face_engine(cfg)
    assert isinstance(engine, InsightFaceEngine)
    assert engine.root_dir == str(tmp_path / "models")


@pytest.mark.asyncio
async def test_health_ready_endpoint_returns_database_ok(tmp_path) -> None:
    db_path = tmp_path / "ready_test.db"
    cfg = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        upload_dir=str(tmp_path / "uploads"),
        face_engine_mode="deterministic",
        whatsapp_provider_mode="mock",
        llm_provider_mode="fallback",
    )
    app = create_app(settings=cfg)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get("/health/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd D:\Project\smart-school-attendance\backend; uv run pytest tests/test_database_sync.py -v`
Expected: FAIL (`ImportError: cannot import name 'format_column_default_sql'`).

- [ ] **Step 3: Implement `format_column_default_sql`, `insightface_home`, and `/health/ready`**

1. In `backend/app/database.py`, extract `format_column_default_sql(column: Any, dialect_name: str) -> str` with properly parenthesized ternary logic:
   - `if isinstance(val, bool): val_str = ("1" if val else "0") if dialect_name == "sqlite" else ("TRUE" if val else "FALSE")`
   - Escape single quotes in string scalar defaults (`val.replace("'", "''")`).
   - Call `format_column_default_sql(column, dialect_name)` from `sync_schema_columns`.
2. In `backend/app/config.py`, add `insightface_home: str = ""` to `Settings`.
3. In `backend/app/providers/face_engine.py`:
   - Add `root_dir: str | None = None` to `InsightFaceEngine.__init__`.
   - In `InsightFaceEngine._get_app()`, if `self.root_dir` is non-empty, `Path(self.root_dir).mkdir(parents=True, exist_ok=True)` and pass `root=self.root_dir` to `FaceAnalysis(...)`.
   - In `create_face_engine(settings: Settings)`, resolve `root_dir = settings.insightface_home.strip() or str(Path(settings.upload_dir) / ".insightface")` and pass it to `InsightFaceEngine(root_dir=root_dir)`.
4. In `backend/app/main.py`, add `@app.get("/health/ready")` that executes `SELECT 1` via `get_db` and returns `{"status": "ok", "database": "ok"}` (or `HTTPException(503)` if DB unreachable).

- [ ] **Step 4: Run new tests + full backend pytest suite**

Run: `cd D:\Project\smart-school-attendance\backend; uv run pytest -v`
Expected: PASS (66 passed, 0 failures).

- [ ] **Step 5: Commit Task 1**

```bash
git add backend/app/database.py backend/app/config.py backend/app/providers/face_engine.py backend/app/main.py backend/tests/test_database_sync.py
git commit -m "fix(backend): fix PostgreSQL boolean schema sync, InsightFace root dir, and add /health/ready"
```

---

### Task 2: Production Dockerfiles (Backend ML Option + Web Admin Standalone) & Compose Stack

**Files:**
- Modify: `backend/Dockerfile:1-36`
- Modify: `web_admin/next.config.ts:1-17`
- Create: `web_admin/.dockerignore`
- Create: `web_admin/Dockerfile`
- Modify: `docker-compose.yml:1-68`
- Modify: `.env.example:14-31`

**Interfaces:**
- Consumes: `Settings.insightface_home` (`INSIGHTFACE_HOME`), `NEXT_PUBLIC_API_URL`.
- Produces: Multi-stage `backend/Dockerfile` (`ARG INSTALL_ML=false`), `web_admin/Dockerfile` (`output: "standalone"`), and updated `docker-compose.yml` including `web_admin`.

- [ ] **Step 1: Add `output: "standalone"` to `web_admin/next.config.ts` and verify `npm run build`**

Edit `web_admin/next.config.ts` to add `output: "standalone",` inside `nextConfig`, then run `cd D:\Project\smart-school-attendance\web_admin; npm run build` and check `.next/standalone/server.js` exists.

- [ ] **Step 2: Create `web_admin/.dockerignore` and `web_admin/Dockerfile`**

- `web_admin/.dockerignore`: ignore `node_modules`, `.next`, `.env*.local`, `npm-debug.log*`.
- `web_admin/Dockerfile`:
  - Stage 1 (`deps` on `node:22-alpine`): `npm ci`.
  - Stage 2 (`builder` on `node:22-alpine`): `ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1`, `ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL`, `npm run build`.
  - Stage 3 (`runner` on `node:22-alpine`): non-root user `nextjs`, copy `.next/standalone`, `.next/static`, `EXPOSE 3001`, `ENV PORT=3001 HOSTNAME=0.0.0.0`, `CMD ["node", "server.js"]`.

- [ ] **Step 3: Update `backend/Dockerfile`, `docker-compose.yml`, and `.env.example`**

- In `backend/Dockerfile`:
  - Add `ARG INSTALL_ML=false`.
  - Install build/runtime deps cleanly when `INSTALL_ML=true` (`build-essential` in builder for `insightface` Cython wheels if needed; `libgl1`, `libglib2.0-0`, `libgomp1` in runtime; `uv sync --frozen --no-dev --no-install-project --extra ml` when `INSTALL_ML=true` else `--no-dev`).
  - Create `/app/.insightface` owned by `appuser:appgroup` and set `ENV INSIGHTFACE_HOME=/app/.insightface`.
- In `docker-compose.yml`:
  - Add `build.args.INSTALL_ML: ${INSTALL_ML:-false}` and `INSIGHTFACE_HOME: /app/.insightface` on `backend`, plus `insightface_models:/app/.insightface` volume.
  - Add `web_admin` service (`build: ./web_admin` with `NEXT_PUBLIC_API_URL`), port `127.0.0.1:3001:3001`, `depends_on: backend`.
- In `.env.example`: document `INSTALL_ML=false` and `INSIGHTFACE_HOME=/app/.insightface`.

- [ ] **Step 4: Validate Compose & Next.js Build**

Run:
- `cd D:\Project\smart-school-attendance\web_admin; npm run build; npx tsc --noEmit; npm run lint`
- `cd D:\Project\smart-school-attendance; docker compose config -q`
Expected: Exit code 0 on all commands.

- [ ] **Step 5: Commit Task 2**

```bash
git add backend/Dockerfile web_admin/next.config.ts web_admin/.dockerignore web_admin/Dockerfile docker-compose.yml .env.example
git commit -m "chore(docker): add standalone web_admin container and opt-in InsightFace ML backend build"
```

---

### Task 3: Externalize Android Release Signing Configuration (`mobile_guru`)

**Files:**
- Modify: `.gitignore:21-44`
- Create: `mobile_guru/android/key.properties.example`
- Modify: `mobile_guru/android/app/build.gradle.kts:1-49`

**Interfaces:**
- Consumes: Optional `mobile_guru/android/key.properties` (`storePassword`, `keyPassword`, `keyAlias`, `storeFile`).
- Produces: Safe release signing when `key.properties` is present; safe fallback to debug signing when absent; strict `.gitignore` protection for `key.properties`, `*.jks`, and `*.keystore`.

- [ ] **Step 1: Protect signing secrets in `.gitignore`**

Append `key.properties`, `*.jks`, and `*.keystore` to `.gitignore` under `# Secrets & local runtime data`.

- [ ] **Step 2: Create `mobile_guru/android/key.properties.example`**

```properties
storePassword=CHANGE_ME
keyPassword=CHANGE_ME
keyAlias=smartschool-release
storeFile=../smartschool-release.jks
```

- [ ] **Step 3: Update `mobile_guru/android/app/build.gradle.kts` to load `key.properties` safely**

Import `java.io.FileInputStream` and `java.util.Properties`, load `rootProject.file("key.properties")` if `exists()`, create `signingConfigs.create("release")` when `keystorePropertiesFile.exists()`, and set `buildTypes.release.signingConfig = if (hasReleaseKeystore) signingConfigs.getByName("release") else signingConfigs.getByName("debug")`.

- [ ] **Step 4: Verify Flutter analyze, unit tests, and Android build**

Run:
- `cd D:\Project\smart-school-attendance\mobile_guru; flutter analyze; flutter test; flutter build apk --debug`
Expected: `No issues found!`, `All tests passed!`, `Built build\app\outputs\flutter-apk\app-debug.apk`.

- [ ] **Step 5: Commit Task 3**

```bash
git add .gitignore mobile_guru/android/key.properties.example mobile_guru/android/app/build.gradle.kts
git commit -m "chore(mobile-guru): support externalized Android key.properties release signing"
```

---

### Task 4: UI/UX Polish, Figma Design Consistency & Simple Indonesian Copy (`web_admin` + `mobile_guru`)

**Files:**
- Modify: `web_admin/src/components/Sidebar.tsx:24-49`
- Modify: `web_admin/src/app/(admin)/page.tsx`
- Modify: `web_admin/src/app/(admin)/students/page.tsx`
- Modify: `web_admin/src/app/(admin)/faces/page.tsx`
- Modify: `web_admin/src/app/(admin)/evaluation/page.tsx`
- Modify: `web_admin/src/components/evaluation/ChatbotLogDetailModal.tsx`
- Modify: `web_admin/src/components/evaluation/ChatbotSimulatorModal.tsx`
- Modify: `web_admin/src/components/evaluation/FaceLogLabelModal.tsx`
- Modify: `web_admin/src/components/faces/WebcamCaptureModal.tsx`
- Verify: `mobile_guru/lib/core/theme.dart`, `mobile_guru/lib/screens/*.dart`

**Interfaces:**
- Aligns rendered `web_admin` and `mobile_guru` styling with the 11-screen Figma design tokens (`#1D4ED8` primary, `#0F172A` dark slate, `#F8FAFC` surface background, `#0B1120` dark Kiosk canvas, `#38BDF8` cyan frame, `#10B981`/`#F59E0B`/`#EF4444` semantic badges).
- Replaces technical jargon on every menu, section title, metric card, and button in `web_admin` with plain, everyday Indonesian labels:
  - Sidebar (`Sidebar.tsx`):
    - `"Dashboard Ringkasan"` / `"Ringkasan operasional"` → `"Beranda"` / `"Ringkasan hari ini"`
    - `"Data Siswa & Master"` / `"Siswa, Ortu, Kelas, Jadwal & Guru"` → `"Data Sekolah"` / `"Siswa, Ortu, Kelas, Guru & Jadwal"`
    - `"Dataset Wajah Siswa"` / `"Registrasi 5-slot biometrik"` → `"Foto Wajah Siswa"` / `"Upload & atur foto wajah (maks 5)"`
    - `"Laporan & Evaluasi FAR/FRR"` / `"Confusion Matrix & Chatbot"` → `"Laporan & Akurasi"` / `"Rekap absen, ketepatan wajah & WA"`
  - Dashboard (`page.tsx`):
    - `"KESIAPAN DATASET WAJAH"` → `"SIAP ABSEN WAJAH"`, `"AKURASI BIOMETRIK"` → `"KETEPATAN KENAL WAJAH"`
    - `"Threshold Cosine Similarity"` → `"Tingkat Ketelitian Wajah"`, `"Registrasi Wajah"` → `"Atur Foto Wajah"`, `"Evaluasi FAR/FRR"` → `"Lihat Laporan"`
    - `"Kelola Data Master (...)"` → `"Kelola Siswa, Guru & Kelas"`
  - Faces (`faces/page.tsx` & `WebcamCaptureModal.tsx`):
    - `"Ambil via Webcam"` → `"Foto Pakai Kamera"`, `"Upload File Foto"` → `"Pilih File Foto"`, `"Skor Kualitas AI"` → `"Kualitas Foto"`, `"512-d vector"` → `"Siap pakai"`, `"Status Biometrik InsightFace 512-d"` → `"Panduan Foto Wajah"`
  - Evaluation (`evaluation/page.tsx` & evaluation modals):
    - `"Simulator Chatbot WA"` / `"Simulator Uji Chatbot WhatsApp (Dry-Run)"` → `"Tes Bot WhatsApp"`
    - `"In-Domain"` → `"Topik Sekolah"`, `"Out-of-Domain"` → `"Di Luar Topik"`, `"AVG WA CHATBOT LATENCY"` → `"KECEPATAN BALAS WA"`
    - `"FACE RECOGNITION ACCURACY"` → `"KETEPATAN KENAL WAJAH"`, `"FAR (...)"` → `"SALAH KENALI ORANG (FAR)"`, `"FRR (...)"` → `"GAGAL KENALI SISWA (FRR)"`
    - `"Confusion Matrix Pengenalan Wajah"` → `"Hasil Uji Ketepatan Wajah"`, `"Slider Threshold Cosine Similarity"` → `"Atur Tingkat Ketelitian Wajah"`
    - `"Ground Truth"` → `"Orang Sebenarnya"`, `"Similarity / Thr"` → `"Skor / Batas"`, `"Liveness"` → `"Kedip Mata"`, `"Edit Label"` → `"Koreksi"`
    - `"Impostor / Non-Siswa"` → `"Orang Lain / Bukan Siswa"` (inside `FaceLogLabelModal.tsx`)

- [ ] **Step 1: Simplify menu, feature, and button copy across `web_admin` to everyday Indonesian**

Update `Sidebar.tsx`, `page.tsx`, `students/page.tsx`, `faces/page.tsx`, `evaluation/page.tsx`, `WebcamCaptureModal.tsx`, `ChatbotSimulatorModal.tsx`, `ChatbotLogDetailModal.tsx`, and `FaceLogLabelModal.tsx` using the exact plain-language mapping above (keeping all API contracts, `id`s, and data logic untouched).

- [ ] **Step 2: Fix 5-slot face card alignment, evaluation table wrapping & mobile table responsiveness**

- In `faces/page.tsx` (`FaceSlotCard`), use `whitespace-nowrap` on `"Kualitas Foto"` + score, and `flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5` on `"Siap pakai"` + compact WIB timestamp so narrow 5-column cards never split awkwardly mid-token.
- In `evaluation/page.tsx`, add `whitespace-nowrap` to `Skor / Batas`, `Latency`, and `Koreksi` cells so every table row stays cleanly single-line.
- In `page.tsx`, add `whitespace-nowrap` on `Ringkasan Kehadiran Kelas Hari Ini` table headers and cells inside `overflow-x-auto -mx-2 px-2 sm:mx-0 sm:px-0` so column labels never clip mid-letter on 390px mobile viewports.

- [ ] **Step 3: Audit `mobile_guru` screen themes & button clarity against Figma (`k5s10kfg`)**

Check `mobile_guru/lib/screens/*.dart` and `mobile_guru/lib/core/theme.dart` to confirm palette, layout padding, and user-facing labels match Figma and contain no technical jargon (`flutter test` assertions remain passing).

- [ ] **Step 4: Re-verify `web_admin` build/lint, `mobile_guru` tests, and clean up leftover demo DB record**

1. Remove any non-seed test record (e.g., temporary student `alexcc` from prior manual tests) or re-verify clean `seed.py` state in `smart_school.db`.
2. Run `cd D:\Project\smart-school-attendance\web_admin; npx tsc --noEmit; npm run lint; npm run build`.
3. Run `cd D:\Project\smart-school-attendance\mobile_guru; flutter analyze; flutter test`.
Expected: All checks exit 0 with zero errors.

- [ ] **Step 5: Commit Task 4**

```bash
git add web_admin/src/
git commit -m "fix(ui): simplify feature/button copy to plain Indonesian and polish responsive alignment"
```

---

### Task 5: Full Live Write-Flow & Visual E2E Verification (`web_admin` + `backend`)

**Files:**
- Run verification script (scratch, non-committed) against live `http://localhost:8000` and `http://localhost:3001`

**Interfaces:**
- Exercises: Admin login, Teacher CRUD (`POST/DELETE /api/v1/teachers`), Student + inline Parent WA CRUD (`POST/PUT/DELETE /api/v1/students`), Face upload (`POST /api/v1/students/{id}/faces`), Chatbot leave & attendance webhook (`POST /api/v1/webhook/whatsapp`), Teacher leave verification (`PATCH /api/v1/leave-requests/{id}/verify`), and Attendance session open/scan/close lifecycle.

- [ ] **Step 1: Execute Playwright + API Write-Flow & Visual Audit Script with Cleanup**

Write and run a Python Playwright + `httpx` E2E verification script (stored in scratch directory) that:
1. Logs into Web Admin (`http://localhost:3001/login`) as `admin@sekolah.sch.id`.
2. Creates a temporary Teacher in `Guru` tab via the live UI, verifies it appears in the list, and deletes it via the UI/API.
3. Opens `Tambah Siswa`, toggles inline new parent input, creates a temporary Student + inline Parent WA, verifies it appears in `/students` table, then cleans up both Student and temporary Parent.
4. Verifies `/`, `/students`, `/faces`, and `/evaluation` across desktop (`1440x900`) and mobile (`390x844`) viewports produce 0 console errors, 0 page errors, 0 failed HTTP >= 400 requests, 0 broken images, and 0 horizontal layout overflow.
5. Re-verifies screenshots visually after Task 4 UI polish and confirms `smart_school.db` returns to clean demo state after teardown.

- [ ] **Step 2: Fix any issues surfaced by E2E run (if found)**

If any UI/API bug surfaces during the write-flow test, patch it cleanly, re-run the affected test suite + E2E check, and commit the fix.

- [ ] **Step 3: Sync Final Commits to GitHub**

Run: `cd D:\Project\smart-school-attendance; git status; git push origin main`
Expected: Working tree clean, `main` synced with `origin/main`.

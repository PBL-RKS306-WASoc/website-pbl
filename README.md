# BERNIAGA — Web E-commerce PBL RKS-306

Web e-commerce (Flask + MySQL) sebagai **objek yang dilindungi SOC** (Wazuh, TheHive/Cortex, dll.). Aplikasi menghasilkan log JSON terstruktur untuk 3 use case deteksi dan menyediakan API internal untuk Active Response.

> Repo: `PBL-RKS306-WASoc/website-pbl`. Dokumen lain: [PRD.md](PRD.md), [database.md](database.md).

## Stack

Flask, Flask-SQLAlchemy, Flask-Login, Flask-WTF (CSRF), Flask-Migrate, Argon2 (password), MySQL/MariaDB (PyMySQL), python-magic (validasi file), Bootstrap 5.3.3 (CDN).

## Fitur

| Peran | Fitur |
|---|---|
| Customer | Register/login/logout, profil (ubah nama dan email), cari & filter produk, cart, checkout, riwayat pesanan, upload bukti bayar |
| Admin | Dashboard, CRUD produk/kategori, approval bukti bayar, laporan transaksi + export CSV, pembatalan pesanan, manajemen pengguna |
| SOC | API internal pembatasan/pelepasan akun, log JSON, FIM pada folder bukti bayar |
| Belum | Review produk |

## Struktur (blueprint)

`auth`, `catalog`, `admin`, `cart`, `orders`, `admin_payments`, `admin_reports`, `admin_users`, `soc_api`

## Setup lokal (Windows)

```powershell
git clone https://github.com/PBL-RKS306-WASoc/website-pbl.git
cd website-pbl
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # isi nilai, JANGAN di-commit
flask db upgrade
flask db current            # pastikan head
flask create-admin
flask run                   # http://127.0.0.1:5000
```

Prasyarat: Python 3, MySQL/MariaDB, libmagic (dependensi `python-magic`).

## Konfigurasi (`.env`)

| Variabel | Keterangan |
|---|---|
| `SECRET_KEY` | Acak dan panjang; beda tiap lingkungan |
| `DATABASE_URL` | `mysql+pymysql://user:pass@host/db`; pakai user DB hak minimal, bukan root |
| `COOKIE_SECURE` | `0` untuk HTTP lokal, `1` di produksi (TLS) |
| `SOC_API_TOKEN` | Bearer token API SOC. Kosong = API gagal tertutup. Buat: `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| `SOC_API_ALLOWED_IPS` | Allowlist IP (default `127.0.0.1`); isi IP host Wazuh |

Nama variabel `SOC_API_*` lain: lihat `.env.example` dan `app/config.py`.

## Perintah CLI

| Perintah | Fungsi |
|---|---|
| `flask db upgrade` | Terapkan migrasi |
| `flask create-admin` | Buat akun admin |
| `flask admin_reports expire-orders` | Batalkan pesanan `pending_payment` kedaluwarsa dan kembalikan stok (jadwalkan via cron/Task Scheduler) |

## Integrasi SOC

- **Log:** `logs/app.log` (JSON, rotasi 5 MB x 5, timestamp WIB). Field: `timestamp`, `level`, `event`, `user_id`/`username`, `src_ip`, `method`, `path`, `session_id`.
- **FIM:** `uploads/payment_proofs/`
- **API (Bearer token + allowlist IP):**
  - `POST /internal/v1/accounts/restrict`
  - `POST /internal/v1/accounts/release`
  - `GET /internal/v1/accounts/<username>`
- `src_ip` memakai `X-Forwarded-For` (ProxyFix `x_for=1`); aplikasi harus hanya menerima trafik dari NGINX dan NGINX harus menimpa header itu.

| Use case | Event utama |
|---|---|
| Manipulasi harga (T1565.002) | `cart.price_mismatch`, `checkout.price_mismatch`, `checkout.total_mismatch` |
| Credential stuffing (T1110.004) | `auth.login_failed/success/blocked`, `auth.session_revoked` |
| Web shell (T1505.003) | `upload.rejected`, `upload.proof_saved` |

## Keamanan

Argon2, CSRF di semua form (kecuali API SOC), harga dihitung server, anti-IDOR, upload whitelist JPG/PNG + magic bytes + nama UUID + izin 0640, export CSV menetralkan formula injection, `SELECT ... FOR UPDATE` pada pembayaran/pembatalan.

**Sengaja lemah untuk pengujian SOC:** tanpa rate limit login; file polyglot lolos agar ditangkap FIM.

## Produksi

Flask dev server tidak untuk produksi. Gunakan Gunicorn di belakang NGINX (TLS), `COOKIE_SECURE=1`, user DB khusus, jadwalkan `expire-orders`.

## Catatan serah terima

Hapus akun/data uji dan file polyglot, rotasi semua kredensial, pindai repo dari rahasia (repo berstatus Public).
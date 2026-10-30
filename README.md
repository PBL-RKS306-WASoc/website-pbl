# BERNIAGA — Web E-commerce PBL RKS-306

## Ulasan produk

Customer yang sudah login dapat memberi satu ulasan per produk yang pernah dibeli pada pesanan berstatus `paid`. Rating wajib bernilai 1-5; komentar bersifat opsional dan maksimal 1000 karakter. Terapkan migrasi database dengan `flask db upgrade`.

## Pembayaran Midtrans Sandbox

Midtrans Snap merupakan metode tambahan; pembayaran transfer manual dan persetujuan admin tetap tersedia. Atur `MIDTRANS_SERVER_KEY` dan `MIDTRANS_CLIENT_KEY` pada `.env`, dengan `MIDTRANS_IS_PRODUCTION=0` untuk Sandbox. Jika server key kosong, tombol dan endpoint Midtrans nonaktif.

Setelah menambahkan atau mengubah model, buat dan terapkan migrasi:

```powershell
flask --app wsgi db migrate -m "order_midtrans"
flask --app wsgi db upgrade
```

Jalankan pengujian tanpa kredensial Midtrans asli:

```powershell
pytest tests/test_midtrans.py -q
```

Untuk mengecek penolakan signature secara manual (dengan server key uji nonkosong, bukan key asli):

```powershell
curl.exe -i -X POST http://127.0.0.1:5000/midtrans/notify `
  -H "Content-Type: application/json" `
  -d '{"order_id":"BRN-1-1234567890","status_code":"200","gross_amount":"125000.00","signature_key":"invalid"}'
```

Webhook tersebut harus memberi HTTP 403 dan mencatat `midtrans.signature_invalid`.

Untuk pengujian lokal melalui Midtrans Sandbox, jalankan aplikasi (misalnya pada port 5000), lalu buka tunnel publik menggunakan `ngrok http 5000` atau `cloudflared tunnel --url http://localhost:5000`. Atur URL notifikasi Sandbox ke `https://<alamat-tunnel>/midtrans/notify`. Login sebagai customer, buat pesanan, pilih **Bayar dengan Midtrans**, lalu selesaikan transaksi menggunakan simulator/metode pembayaran Sandbox Midtrans. Status pesanan hanya diperbarui setelah webhook terverifikasi diterima; callback browser sekadar memuat ulang halaman.

## Profil customer

Customer yang sudah login dapat mengubah nama lengkap dan email serta mengunggah avatar JPG/PNG melalui menu **Profil**. Berkas avatar divalidasi sebagai gambar, disimpan dengan nama acak di folder `uploads/avatars`, dan dibatasi hingga 2 MB serta 4096 x 4096 piksel.
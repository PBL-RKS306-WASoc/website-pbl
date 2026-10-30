# BERNIAGA — Web E-commerce PBL RKS-306

## Ulasan produk

Customer yang sudah login dapat memberi satu ulasan per produk yang pernah dibeli pada pesanan berstatus `paid`. Rating wajib bernilai 1-5; komentar bersifat opsional dan maksimal 1000 karakter. Terapkan migrasi database dengan `flask db upgrade`.

## Profil customer

Customer yang sudah login dapat mengubah nama lengkap dan email serta mengunggah avatar JPG/PNG melalui menu **Profil**. Berkas avatar divalidasi sebagai gambar, disimpan dengan nama acak di folder `uploads/avatars`, dan dibatasi hingga 2 MB serta 4096 x 4096 piksel.

## Konfigurasi API SOC

API internal SOC dinonaktifkan jika `SOC_API_TOKEN` kosong. Atur token dan `SOC_API_ALLOWED_IPS` (daftar IP dipisahkan koma) pada `.env`; `SOC_API_DEFAULT_MINUTES` dan `SOC_API_MAX_MINUTES` mengatur durasi pembatasan akun. Nama konfigurasi durasi menggunakan `MINUTES`, sesuai dengan yang dipakai endpoint SOC.
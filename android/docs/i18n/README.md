# Catatan i18n - pola WhatsVault

Dokumen ini mencatat konvensi lokalisasi yang **diadopsi dari**
`/home/mrksvt/Documents/Coding/Android/WhatsVault` (diverifikasi 2026-10-28), lalu
disesuaikan untuk Reels Downloader Android.

## 1. Temuan di WhatsVault

| Temuan | Bukti |
|---|---|
| Default bahasa Inggris di `app/src/main/res/values/strings.xml` | 734 entri `<string>` |
| Terjemahan per bahasa di `values-<kode>/strings.xml` | `ar, de, es, fr, id, in, it, pt, ru, tr, zh` (534-544 entri masing-masing) |
| **Ada duplikat `values-in`** | kode locale lama untuk Indonesia; Android modern memakai `id` |
| `app_name` tidak diterjemahkan | `<string name="app_name" translatable="false">WhatsVault</string>` |
| `crowdin.yml` di root project | `source: "**/values/strings.xml"`, `translation: "**/values-%two_letters_code%/%original_file_name%"`, mapping `he: "iw"` |
| Tidak ada `locales_config.xml` / `generateLocaleConfig` | locale murni dari folder `values-*` |
| Tidak ada metadata Play/fastlane | rilis APK langsung, catatan rilis di `changelog.txt` (gaya `[ADDED]/[IMPROVED]/[FIXED]/[NOTE]`) |
| `.gitignore` mengabaikan `local.properties`, `key.jks`, `key_base64.txt`, `*.log` | signing key tidak masuk repo |

## 2. Konvensi yang dipakai Reels Downloader

```text
android/app/src/main/
├── res/values/strings.xml           # Inggris (source of truth)
├── res/values-id/strings.xml        # Indonesia (TIDAK values-in)
└── java/dev/mrksvt/reelsdownloader/ # semua teks lewat stringResource()
```

Aturan:

1. **Tidak ada string hard-code** di Compose; semua lewat `stringResource(R.string.x)`.
2. `app_name` → `translatable="false"`.
3. Format argumen **bernomor**: `%1$s`, `%1$d%%` - bukan `%s`, agar terjemahan bebas
   mengubah urutan.
4. Emoji (🎬 🎵 ✅ ⚠️ 📏 ⏱️ 🔒 🔍 ❌ 📡 ⚙️) **disalin apa adanya** ke terjemahan.
5. Nama brand platform (Instagram/Facebook/YouTube) **tidak diterjemahkan**.
6. Teks error disamakan dengan `app/services/errors.py` bot agar satu istilah.
7. Jangan menambah `values-in`; jangan menambah `values-rID`.
8. `androidResources { generateLocaleConfig = true }` di `build.gradle.kts`
   (supaya picker bahasa per-app muncul di Settings Android 13+).
9. `android/crowdin.yml` dibuat dengan isi yang sama seperti WhatsVault agar alur
   Crowdin nanti tidak perlu konvensi baru.

## 3. Lokasi sumber string yang sudah disiapkan

| File | Dipakai untuk |
|---|---|
| `android/docs/i18n/strings-en.xml` | → `res/values/strings.xml` |
| `android/docs/i18n/strings-id.xml` | → `res/values-id/strings.xml` |

Keduanya sudah memuat ~85 entri awal untuk semua layar (Home, job status, history,
notifikasi, error, settings, izin, share sheet). WP-A12 akan memindahkannya ke
`android/app/src/main/res/values*/`, lalu `lint --check MissingTranslation` harus 0.

## 4. Bahasa tambahan (belum diputuskan)

Kandidat dari daftar WhatsVault: `ar, de, es, fr, it, pt, ru, tr, zh`.
Rekomendasi: **tunggu sampai UI stabil**, lalu tambahkan sekaligus, supaya tidak
menerjemahkan string yang masih berubah. String yang ditandai
`translatable="false"` tidak ikut.

## 5. Verifikasi

```bash
# dari direktori android/
./gradlew :app:lintDebug   # MissingTranslation + HardcodedText harus 0
# cek tidak ada values-in yang tidak sengaja dibuat
ls app/src/main/res | grep -E 'values(-in)?$'
# pastikan semua string source ada di terjemahan
diff <(grep -o 'name="[^"]*"' app/src/main/res/values/strings.xml | sort) \
     <(grep -o 'name="[^"]*"' app/src/main/res/values-id/strings.xml | sort)
```

## 6. Rilis (bukan Play Store)

Karena distribusi lewat **GitHub Releases**, tidak ada folder `fastlane/` atau
"whatsnew" per 500 karakter. Catatan rilis memakai satu `RELEASE-NOTES.md`
bergaya `changelog.txt` WhatsVault.

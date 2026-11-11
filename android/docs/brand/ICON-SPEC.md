# ICON SPEC - Reels Downloader Android

Sumber aset: **`ReelsDownloader.png`** di akar repo.
Dianalisis 2026-10-28: 500×500 px, PNG **RGBA**, latar **transparan penuh**
(alpha 0 di sudut; artwork opaque mulai ~1% dari tepi; bentuk rounded-square
mengisi hampir seluruh kanvas).

Dirujuk dari `android/docs/PRD-ANDROID.md` §8 dan `android/docs/PLAN-ANDROID.md` WP-A2/A12.

---

## 1. Kenapa perlu konversi (walau sudah transparan)

- Launcher butuh 5 densitas raster, bukan satu PNG 500 px.
- Android 8+ memakai **adaptive icon** (foreground + background) dengan **safe zone
  66 dp** dari kanvas 108 dp. Artwork full-bleed ~98% akan terpotong mask OEM.
- Android 13+ memakai **monochrome** layer untuk themed icons (Material You).
- Android 12+ splash screen memerlukan `windowSplashScreenAnimatedIcon` terpisah.

Karena aset **sudah transparan**, tidak perlu membuat background putih atau
memotong background. Yang perlu: **scaling dengan inset** dan turunan per densitas.

---

## 2. Aset keluaran

| File | Ukuran | Isi |
|---|---|---|
| `res/mipmap-anydpi-v26/ic_launcher.xml` | - | adaptive: foreground + `@color/ic_launcher_background` |
| `res/mipmap-anydpi-v26/ic_launcher_round.xml` | - | varian round |
| `res/drawable-nodpi/ic_launcher_foreground.webp` | 432×432 | artwork discale ke ±66 dp (61% kanvas) supaya aman di semua mask |
| `res/drawable-nodpi/ic_launcher_monochrome.webp` | 432×432 | silhouette putih, transparan |
| `res/values/colors.xml` → `ic_launcher_background` | - | warna latar adaptif |
| `res/mipmap-{m,h,xh,xxh,xxxh}dpi/ic_launcher.webp` | 48/72/96/144/192 | legacy API 26-27 (full-bleed, tanpa inset) |
| `res/drawable-nodpi/ic_splash_logo.webp` | 288×288 | Splash API 31+ |

Warna latar adaptif: sampel dari aset itu sendiri - rata-rata pixel opaque di
ring terluar (mis. sekitar `#0A1C44`, dominan navy gelap dengan aksen biru/merah
muda). Alternatif aman: pakai `#000000` transparan (artwork menutupi hampir
seluruh kanvas sehingga latar nyaris tidak terlihat).

---

## 3. Prosedur konversi (dijalankan di WP-A2)

```bash
cd android/app/src/main/res
mkdir -p drawable-nodpi mipmap-mdpi mipmap-hdpi mipmap-xhdpi mipmap-xxhdpi mipmap-xxxhdpi

python3 - <<'PY'
from PIL import Image

SRC = "../../../../../../ReelsDownloader.png"   # path ke akar repo saat dijalankan
im = Image.open(SRC).convert("RGBA")

def with_inset(img, canvas_px, content_ratio):
    """Taruh artwork di tengah kanvas dengan inset (safe zone adaptive icon)."""
    side = int(canvas_px * content_ratio)
    art = img.resize((side, side), Image.LANCZOS)
    out = Image.new("RGBA", (canvas_px, canvas_px), (0, 0, 0, 0))
    off = (canvas_px - side) // 2
    out.paste(art, (off, off), art)
    return out

# 1) Foreground adaptive (safe zone 66/108 = 61%)
with_inset(im, 432, 0.61).save("drawable-nodpi/ic_launcher_foreground.webp", "WEBP", lossless=True)

# 2) Splash
with_inset(im, 288, 0.80).save("drawable-nodpi/ic_splash_logo.webp", "WEBP", lossless=True)

# 3) Legacy mipmap (full-bleed, tanpa inset)
for name, px in {"mdpi":48,"hdpi":72,"xhdpi":96,"xxhdpi":144,"xxxhdpi":192}.items():
    im.resize((px, px), Image.LANCZOS).save(f"mipmap-{name}/ic_launcher.webp", "WEBP", lossless=True)

# 4) Monochrome: silhouette putih dari alpha artwork
alpha = im.split()[-1]
white = Image.new("RGBA", im.size, (255, 255, 255, 0))
white.putalpha(alpha)
with_inset(white, 432, 0.61).save("drawable-nodpi/ic_launcher_monochrome.webp", "WEBP", lossless=True)
PY
```

Catatan monochrome: karena artwork opaque hampir penuh, silhouette dari alpha akan
berbentuk **rounded square putih polos** dan kehilangan detail ikon. Dua opsi:

- **Opsi A (rekomendasi):** monochrome diganti glyph Material `smart_display` atau
  `download` (putih di atas transparan) - hasil themed icon tetap terbaca di 24 dp.
- **Opsi B:** ambil luminance artwork (bukan alpha) dengan threshold, sehingga
  detail terang menjadi putih. Harus diverifikasi visual di wallpaper gelap.

---

## 4. Ikon UI (dalam app)

Material Symbols dari https://fonts.google.com/icons:

`download`, `movie`, `music_note`, `history`, `settings`, `link`, `check_circle`,
`error`, `cancel`, `share`, `play_arrow`, `delete`, `open_in_new`, `content_paste`.

Cara impor: `Android Studio → File → New → Vector Asset → Clip Art` (atau unduh
SVG dari Google Fonts lalu SVG → XML converter). Ukuran 24 dp, tint dari
`MaterialTheme.colorScheme.onSurface`.

---

## 5. Aturan pakai

- Jangan memotong/menggeser artwork; tepi aset sudah rapi dan transparan.
- Latar adaptif **bukan putih murni** (bisa terlihat kotak putih di launcher gelap).
- Ikon UI memakai Material Symbols, bukan bitmap launcher.
- Ukuran minimum ikon aksi 24 dp; `contentDescription` wajib untuk ikon yang bisa
  di-tap.

---

## 6. Verifikasi (gerbang WP-A2)

- [ ] Adaptive icon benar di mask bulat, squircle, teardrop (API 33 emulator).
- [ ] Themed icon (Android 13+) muncul di Settings → Wallpaper & style.
- [ ] Tidak ada potongan tepi artwork di mask apa pun (cek safe zone 66 dp).
- [ ] `mipmap-*/ic_launcher.webp` ada untuk API 26-27.
- [ ] Splash API 31+ memakai aset yang sama, tidak terlihat dobel.
- [ ] Semua file ≤ 100 KB (WebP lossless 432 px) supaya APK tetap ≤ 60 MB.

---

## 7. Lokalisasi (pola WhatsVault)

Meski tidak berupa gambar, aturan teks ikut dijaga di sini karena menyentuh
label ikon aksi:

| Aturan | Detail |
|---|---|
| Sumber | `res/values/strings.xml` (Inggris) |
| Indonesia | `res/values-id/strings.xml` (bukan `values-in`) |
| Nama app | `app_name` diberi `translatable="false"` |
| `contentDescription` | Semua lewat `stringResource(R.string.…)` |
| Format | `%1$s` bernomor, agar urutan argumen aman saat diterjemahkan |
| Crowdin | `android/crowdin.yml`, pola `**/values/strings.xml` → `values-%two_letters_code%`, mapping `he → iw` |

---

## 8. Rilis GitHub (bukan Play Store)

Tidak perlu ikon store 512×512 / fitur grafik. Yang dipakai di halaman Release:

| Artefak | Nama |
|---|---|
| APK | `ReelsDownloader-<version>-arm64-v8a-release.apk` |
| Notes | `RELEASE-NOTES.md` |

Format notes mengikuti gaya `changelog.txt` WhatsVault: `[ADDED]` / `[IMPROVED]` /
`[FIXED]` / `[NOTE]`.

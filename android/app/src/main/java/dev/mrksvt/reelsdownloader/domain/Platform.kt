package dev.mrksvt.reelsdownloader.domain

import androidx.annotation.StringRes
import dev.mrksvt.reelsdownloader.R

/**
 * Platform sumber yang didukung (FR-103).
 *
 * Nama platform sengaja TIDAK diterjemahkan (lihat docs/i18n/README.md).
 */
enum class Platform(val id: String, @param:StringRes val labelRes: Int) {
    INSTAGRAM("instagram", R.string.platform_instagram),
    FACEBOOK("facebook", R.string.platform_facebook),
    YOUTUBE("youtube", R.string.platform_youtube);

    companion object {
        fun fromId(value: String?): Platform? = entries.firstOrNull { it.id == value }
    }
}

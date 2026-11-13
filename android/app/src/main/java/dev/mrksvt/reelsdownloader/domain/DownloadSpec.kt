package dev.mrksvt.reelsdownloader.domain

import androidx.annotation.StringRes
import dev.mrksvt.reelsdownloader.R

/** Jenis hasil unduhan (FR-104, FR-105). */
enum class ResultType {
    VIDEO,
    AUDIO;

    companion object {
        fun fromName(value: String?): ResultType =
            entries.firstOrNull { it.name == value } ?: VIDEO
    }
}

/**
 * Kualitas video (FR-106).
 *
 * [height] = `null` untuk "Best" (tanpa batas atas). Pemilihan aktual dilakukan
 * engine berdasarkan format yang tersedia di sumber.
 */
enum class Quality(val height: Int?, @param:StringRes val labelRes: Int) {
    BEST(null, R.string.home_quality_best),
    P1080(1080, R.string.home_quality_1080p),
    P720(720, R.string.home_quality_720p),
    P480(480, R.string.home_quality_480p),
    P360(360, R.string.home_quality_360p);

    companion object {
        fun fromName(value: String?): Quality =
            entries.firstOrNull { it.name == value } ?: BEST
    }
}

/** Bitrate audio (FR-105). */
enum class AudioBitrate(val kbps: Int, @param:StringRes val labelRes: Int) {
    K320(320, R.string.home_bitrate_320),
    K192(192, R.string.home_bitrate_192),
    K128(128, R.string.home_bitrate_128);

    companion object {
        fun fromName(value: String?): AudioBitrate =
            entries.firstOrNull { it.name == value } ?: K320
    }
}

/** Status job, dipakai UI + notifikasi (FR-108, FR-111). */
enum class JobStatus {
    QUEUED,
    RUNNING,
    SAVING,
    DONE,
    FAILED,
    CANCELLED;

    val isActive: Boolean get() = this == QUEUED || this == RUNNING || this == SAVING

    companion object {
        fun fromName(value: String?): JobStatus =
            entries.firstOrNull { it.name == value } ?: QUEUED
    }
}

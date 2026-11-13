package dev.mrksvt.reelsdownloader.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import dev.mrksvt.reelsdownloader.data.ThemeMode

/** Aksen navy diambil dari pelat ikon launcher (`#001040`). */
private val BrandNavy = Color(0xFF0B1B45)
private val BrandNavyLight = Color(0xFF2A3F7A)
private val BrandAccent = Color(0xFF4C6FFF)

private val LightColors = lightColorScheme(
    primary = BrandNavy,
    onPrimary = Color.White,
    primaryContainer = Color(0xFFDDE2FF),
    onPrimaryContainer = BrandNavy,
    secondary = BrandNavyLight,
    tertiary = BrandAccent,
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFB3C2FF),
    onPrimary = BrandNavy,
    primaryContainer = BrandNavyLight,
    onPrimaryContainer = Color(0xFFDDE2FF),
    secondary = Color(0xFFB9C3E8),
    tertiary = Color(0xFF8FA5FF),
)

@Composable
fun ReelsDownloaderTheme(
    themeMode: ThemeMode = ThemeMode.SYSTEM,
    content: @Composable () -> Unit,
) {
    val darkTheme = when (themeMode) {
        ThemeMode.SYSTEM -> isSystemInDarkTheme()
        ThemeMode.LIGHT -> false
        ThemeMode.DARK -> true
    }
    val context = LocalContext.current
    val colorScheme = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ->
            if (darkTheme) dynamicDarkColorScheme(context) else dynamicLightColorScheme(context)

        darkTheme -> DarkColors
        else -> LightColors
    }

    MaterialTheme(colorScheme = colorScheme, content = content)
}

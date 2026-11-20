package com.androidsoundmanager.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

// "The Bakery" palette: golden crust, cream, cocoa, and a strawberry accent.
private val BakeryLight = lightColorScheme(
    primary = Color(0xFFA9571F),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFFFDDB8),
    onPrimaryContainer = Color(0xFF3A1A04),
    secondary = Color(0xFF7B5A43),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFF8DCC6),
    onSecondaryContainer = Color(0xFF2D1708),
    tertiary = Color(0xFFB4485A),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFFFD9DE),
    onTertiaryContainer = Color(0xFF3F0016),
    background = Color(0xFFFFF8F0),
    onBackground = Color(0xFF231A14),
    surface = Color(0xFFFFF8F0),
    onSurface = Color(0xFF231A14),
    surfaceVariant = Color(0xFFF3DFCF),
    onSurfaceVariant = Color(0xFF53443A),
    surfaceContainerLowest = Color(0xFFFFFFFF),
    surfaceContainerLow = Color(0xFFFFF1E4),
    surfaceContainer = Color(0xFFFBEBDB),
    surfaceContainerHigh = Color(0xFFF5E4D3),
    surfaceContainerHighest = Color(0xFFEFDECD),
    outline = Color(0xFF857468),
    outlineVariant = Color(0xFFD8C3B3),
)

private val BakeryDark = darkColorScheme(
    primary = Color(0xFFF2B676),
    onPrimary = Color(0xFF4A2500),
    primaryContainer = Color(0xFF6B3A12),
    onPrimaryContainer = Color(0xFFFFDDB8),
    secondary = Color(0xFFE6BFA0),
    onSecondary = Color(0xFF432B17),
    secondaryContainer = Color(0xFF4B3527),
    onSecondaryContainer = Color(0xFFF8DCC6),
    tertiary = Color(0xFFFFB1BC),
    onTertiary = Color(0xFF66132A),
    tertiaryContainer = Color(0xFF7A2E3C),
    onTertiaryContainer = Color(0xFFFFD9DE),
    background = Color(0xFF1A1310),
    onBackground = Color(0xFFF1E0D2),
    surface = Color(0xFF1A1310),
    onSurface = Color(0xFFF1E0D2),
    surfaceVariant = Color(0xFF4F4036),
    onSurfaceVariant = Color(0xFFD6C2B3),
    surfaceContainerLowest = Color(0xFF140E0B),
    surfaceContainerLow = Color(0xFF221A15),
    surfaceContainer = Color(0xFF271E18),
    surfaceContainerHigh = Color(0xFF322822),
    surfaceContainerHighest = Color(0xFF3D322B),
    outline = Color(0xFF9F8D80),
    outlineVariant = Color(0xFF4F4036),
)

private val BakeryShapes = Shapes(
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(20.dp),
    large = RoundedCornerShape(28.dp),
)

@Composable
fun SoundManagerTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) BakeryDark else BakeryLight,
        shapes = BakeryShapes,
        content = content,
    )
}

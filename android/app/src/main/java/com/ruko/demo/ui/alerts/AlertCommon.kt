package com.ruko.demo.ui.alerts

import android.content.ContextWrapper
import android.content.res.Configuration
import android.content.res.Resources
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.BuildConfig
import com.ruko.demo.R
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.Decision
import com.ruko.demo.ui.PaymentViewModel
import com.ruko.demo.ui.cacheCard
import com.ruko.demo.ui.reasonText
import kotlinx.coroutines.delay
import java.util.Locale

/** The user sees at most this many reasons, the strongest first (the server orders them). */
const val MAX_REASONS = 3

/**
 * Alerts speak the language chosen in the profile, as the watcher's notifications do, not the
 * phone's. Only the words change: the activity stays the context, so the dialer and SMS app open.
 */
@Composable
fun InProfileLanguage(language: String?, content: @Composable () -> Unit) {
    val base = LocalContext.current
    if (language.isNullOrBlank()) return content()
    val config = remember(base, language) {
        Configuration(base.resources.configuration).apply { setLocale(Locale.forLanguageTag(language)) }
    }
    val resources = remember(base, config) { base.createConfigurationContext(config).resources }
    val context = remember(base, resources) {
        object : ContextWrapper(base) {
            override fun getResources(): Resources = resources
        }
    }
    CompositionLocalProvider(
        LocalContext provides context,
        LocalConfiguration provides config,
        LocalResources provides resources,
        content = content,
    )
}

/** Wall-clock time that ticks every [periodMs], for countdowns. */
@Composable
fun rememberNow(periodMs: Long = 1_000L): Long {
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(periodMs) {
        while (true) {
            delay(periodMs)
            now = System.currentTimeMillis()
        }
    }
    return now
}

/** Icon, title and body at the top of an alert. */
@Composable
fun AlertHeader(icon: ImageVector, accent: Color, title: String, body: String) {
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(14.dp)) {
        Box(
            modifier = Modifier.size(52.dp).clip(CircleShape).background(accent.copy(alpha = 0.18f)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = accent, modifier = Modifier.size(28.dp))
        }
        Text(title, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    }
    Text(body, style = MaterialTheme.typography.bodyLarge)
}

/** "Why we are asking" and the top reasons in words. Unknown codes are skipped, never shown raw. */
@Composable
fun ReasonList(codes: List<String>, accent: Color) {
    val reasons = codes.mapNotNull { reasonText(it) }.take(MAX_REASONS)
    if (reasons.isEmpty()) return
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(stringResource(R.string.alert_why), style = MaterialTheme.typography.titleMedium, color = CacheColors.TextSecondary)
        reasons.forEach { reason ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Box(Modifier.padding(top = 8.dp).size(8.dp).clip(CircleShape).background(accent))
                Text(reason, style = MaterialTheme.typography.bodyLarge)
            }
        }
    }
}

/** The line that answers the scammer's script ("ignore any warning screen"). */
@Composable
fun CounterCoaching() {
    Row(
        modifier = Modifier.fillMaxWidth().cacheCard(borderColor = CacheColors.Warning.copy(alpha = 0.6f)).padding(14.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(com.ruko.demo.ui.CacheIcons.Shield, contentDescription = null, tint = CacheColors.Warning, modifier = Modifier.size(22.dp))
        Text(stringResource(R.string.alert_counter_coaching), style = MaterialTheme.typography.bodyMedium)
    }
}

/** Debug builds, with the debug panel switch on: latency and message key. Never a score. */
@Composable
fun AlertDebugLine(vm: PaymentViewModel) {
    if (!BuildConfig.DEBUG || !vm.alertDebug) return
    val result = vm.decision as? Decision.Result ?: return
    Text(
        text = "debug: ${result.response.tier} → ${vm.alertTier}, ${result.millis} ms, message_key=${result.response.messageKey}",
        style = MaterialTheme.typography.bodySmall,
        color = CacheColors.TextSecondary,
    )
}

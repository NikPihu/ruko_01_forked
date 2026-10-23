package com.ruko.demo.ui.alerts

import android.os.SystemClock
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.CacheIcons
import com.ruko.demo.ui.Decision
import com.ruko.demo.ui.PaymentViewModel
import com.ruko.demo.ui.Screen
import com.ruko.demo.ui.SecondaryButton
import com.ruko.demo.ui.cacheCard
import kotlinx.coroutines.delay

/**
 * T2: what we saw, in words, then a 5 second read gate before the slide unlocks. Sliding goes on
 * to the PIN; the user decides.
 */
@Composable
fun ExplainCard(vm: PaymentViewModel, language: String?, onSlid: () -> Unit, onCancel: () -> Unit) {
    val result = vm.decision as? Decision.Result ?: return
    val shownAt = remember { SystemClock.elapsedRealtime() }
    var now by remember { mutableLongStateOf(shownAt) }
    LaunchedEffect(shownAt) {
        while (!AlertRules.slideEnabled(shownAt, now)) {
            delay(100)
            now = SystemClock.elapsedRealtime()
        }
    }
    val unlocked = AlertRules.slideEnabled(shownAt, now)
    val accent = CacheColors.Warning

    InProfileLanguage(language) {
        val copy = AlertText.copy(result.response.messageKey, "T2")
        Screen {
            Column(
                modifier = Modifier.fillMaxWidth().cacheCard(borderColor = accent.copy(alpha = 0.6f)).padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                AlertHeader(CacheIcons.Warning, accent, stringResource(copy.title), stringResource(copy.body))
                ReasonList(result.response.reasons, accent)
            }
            CounterCoaching()
            if (!unlocked) {
                LinearProgressIndicator(
                    progress = { ((now - shownAt).toFloat() / AlertRules.READ_GATE_MS).coerceIn(0f, 1f) },
                    color = accent,
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    stringResource(R.string.alert_read_first, AlertRules.readGateLeftSeconds(shownAt, now)),
                    style = MaterialTheme.typography.bodySmall,
                    color = CacheColors.TextSecondary,
                )
            }
            SlideToConfirm(
                label = stringResource(R.string.alert_slide_to_pay),
                enabled = unlocked,
                onConfirm = {
                    vm.onAlertAction(AlertAction.PROCEEDED)
                    onSlid()
                },
            )
            SecondaryButton(stringResource(R.string.alert_cancel), onClick = {
                vm.onAlertAction(AlertAction.CANCELLED)
                onCancel()
            })
            AlertDebugLine(vm)
        }
    }
}

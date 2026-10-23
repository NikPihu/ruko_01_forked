package com.ruko.demo.ui.alerts

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.CacheIcons
import com.ruko.demo.ui.Decision
import com.ruko.demo.ui.PaymentViewModel
import com.ruko.demo.ui.Screen
import com.ruko.demo.ui.cacheCard

/**
 * T4: "Your bank is checking this payment". There is no review endpoint yet (M6), so nothing is
 * polled: once `pause_minutes` have passed it is treated as a pause that ended (fail open), and
 * "Pay anyway" appears.
 */
@Composable
fun ReviewScreen(
    vm: PaymentViewModel,
    user: AlertUser,
    onPayAnyway: () -> Unit,
    onLeave: () -> Unit,
    onCancel: () -> Unit,
    onAddTrusted: () -> Unit,
) {
    val result = vm.decision as? Decision.Result ?: return
    BackHandler(onBack = onLeave)
    val accent = CacheColors.Info

    InProfileLanguage(user.language) {
        val copy = AlertText.copy(result.response.messageKey, "T4")
        // The scam type, when the server named one, in the T3 words for it.
        val pattern = AlertText.playbookOf(result.response.messageKey)?.let { AlertText.copy("t3_$it", "T3").body }
        Screen {
            Column(
                modifier = Modifier.fillMaxWidth().cacheCard(borderColor = accent.copy(alpha = 0.7f)).padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                AlertHeader(CacheIcons.Shield, accent, stringResource(copy.title), stringResource(copy.body))
                if (pattern != null) {
                    Text(stringResource(pattern), style = MaterialTheme.typography.bodyLarge)
                }
                ReasonList(result.response.reasons, accent)
            }
            CounterCoaching()
            PauseActions(
                vm = vm,
                user = user,
                onPayAnyway = onPayAnyway,
                onWaited = onLeave,
                onAddTrusted = onAddTrusted,
                onKnowThem = null,
            )
            TextButton(onClick = {
                vm.onAlertAction(AlertAction.CANCELLED)
                onCancel()
            }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.alert_cancel), color = CacheColors.TextSecondary)
            }
            AlertDebugLine(vm)
        }
    }
}

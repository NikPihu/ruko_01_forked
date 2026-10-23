package com.ruko.demo.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.BuildConfig
import com.ruko.demo.R
import com.ruko.demo.ui.alerts.TipBanner

private const val MAX_PIN = 6

/** Fake UPI PIN pad. The PIN stays in this screen's memory only; it is never stored or sent. */
@Composable
fun PinScreen(vm: PaymentViewModel, language: String?, onConfirm: () -> Unit) {
    var pin by remember { mutableStateOf("") }
    val canConfirm = pin.length == 4 || pin.length == MAX_PIN

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Column(
            modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 24.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                text = stringResource(R.string.app_name),
                style = MaterialTheme.typography.titleMedium,
                color = CacheColors.PrimaryLight,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = stringResource(R.string.pin_to, formatInr(vm.amountInr ?: 0.0), vm.upiId.trim()),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
            // T1: the tip is here, on the way to the PIN, not on a screen of its own.
            TipBanner(vm, language)
            Text(
                text = stringResource(R.string.pin_title),
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(top = 24.dp),
            )
            PinDots(filled = pin.length, length = MAX_PIN)
            Text(
                text = stringResource(R.string.pin_note),
                style = MaterialTheme.typography.bodySmall,
                color = CacheColors.TextSecondary,
            )
            // T0 shows nothing to the user, so debug builds print it here to check C1 (debug panel
            // switch, so a demo never shows a tier).
            if (BuildConfig.DEBUG && vm.alertDebug) {
                (vm.decision as? Decision.Result)?.let {
                    Text(
                        text = "debug: tier ${it.response.tier}, ${it.millis} ms",
                        style = MaterialTheme.typography.bodySmall,
                        color = CacheColors.TextSecondary,
                    )
                }
            }
        }

        PinPad(
            onDigit = { if (pin.length < MAX_PIN) pin += it },
            onDelete = { pin = pin.dropLast(1) },
            onConfirm = onConfirm,
            canConfirm = canConfirm,
        )
    }
}

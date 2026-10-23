package com.ruko.demo.ui.alerts

import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.CacheIcons
import com.ruko.demo.ui.Decision
import com.ruko.demo.ui.PaymentViewModel
import com.ruko.demo.ui.PrimaryButton
import com.ruko.demo.ui.Screen
import com.ruko.demo.ui.SecondaryButton
import com.ruko.demo.ui.cacheCard
import com.ruko.demo.ui.dial

/** Who is paying and who they trust (sign-up), for the T3 and T4 actions. */
data class AlertUser(val firstName: String, val trustedName: String?, val trustedMobile: String?, val language: String?)

/**
 * T3: a full-screen pause. No way back to the PIN until the countdown ends; then "Pay anyway"
 * appears, because RUKO warns and never blocks. Meanwhile: call or message the trusted person,
 * call 1930, wait for a reminder, or say "I know this person".
 */
@Composable
fun PauseScreen(
    vm: PaymentViewModel,
    user: AlertUser,
    onPayAnyway: () -> Unit,
    onKnowThem: () -> Unit,
    onLeave: () -> Unit,
    onCancel: () -> Unit,
    onAddTrusted: () -> Unit,
) {
    val result = vm.decision as? Decision.Result ?: return
    // Back leaves the pause for Home, never to the PIN or Pay screen.
    BackHandler(onBack = onLeave)
    val accent = CacheColors.Danger

    InProfileLanguage(user.language) {
        val copy = AlertText.copy(result.response.messageKey, "T3")
        Screen {
            Column(
                modifier = Modifier.fillMaxWidth().cacheCard(borderColor = accent.copy(alpha = 0.7f)).padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                AlertHeader(CacheIcons.Warning, accent, stringResource(copy.title), stringResource(copy.body))
                ReasonList(result.response.reasons, accent)
            }
            CounterCoaching()
            PauseActions(
                vm = vm,
                user = user,
                onPayAnyway = onPayAnyway,
                onWaited = onLeave,
                onAddTrusted = onAddTrusted,
                onKnowThem = { why ->
                    vm.knowThisPerson(why)
                    onKnowThem()
                },
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

/**
 * The countdown and the ways out, shared by the T3 pause and the T4 review. [onKnowThem] null
 * hides "I know this person" (T4: the bank is checking, the user cannot vouch it away).
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun PauseActions(
    vm: PaymentViewModel,
    user: AlertUser,
    onPayAnyway: () -> Unit,
    onWaited: () -> Unit,
    onAddTrusted: () -> Unit,
    onKnowThem: ((KnowWhy) -> Unit)?,
) {
    val context = LocalContext.current
    val now = rememberNow()
    val over = AlertRules.payAnywayVisible(now, vm.pauseEndsAtMs)
    val minutesLeft = AlertRules.minutesLeft(now, vm.pauseEndsAtMs)
    var asking by remember { mutableStateOf(false) }

    Text(
        text = if (over) stringResource(R.string.alert_pause_over) else stringResource(R.string.alert_wait_left, minutesLeft),
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
        color = if (over) CacheColors.TextPrimary else CacheColors.Warning,
    )
    if (over) {
        PrimaryButton(stringResource(R.string.alert_pay_anyway), onClick = {
            vm.onAlertAction(AlertAction.PAID_AFTER_PAUSE)
            onPayAnyway()
        })
    }

    val mobile = user.trustedMobile?.takeIf { it.isNotBlank() }
    if (mobile != null) {
        val name = user.trustedName?.takeIf { it.isNotBlank() } ?: mobile
        PrimaryButton(stringResource(R.string.alert_call_trusted, name), onClick = {
            vm.onAlertAction(AlertAction.CALLED_TRUSTED)
            dial(context, mobile)
        })
        val sms = TrustedMessage.body(stringResource(R.string.trusted_contact_sms), user.firstName)
        SecondaryButton(stringResource(R.string.alert_message_trusted, name), onClick = {
            vm.onAlertAction(AlertAction.MESSAGED_TRUSTED)
            context.startActivity(Intent(Intent.ACTION_SENDTO, TrustedMessage.smsUri(mobile)).putExtra("sms_body", sms))
        })
    } else {
        SecondaryButton(stringResource(R.string.alert_add_trusted), onClick = onAddTrusted)
    }

    SecondaryButton(stringResource(R.string.alert_call_1930), onClick = {
        vm.onAlertAction(AlertAction.CALLED_1930)
        dial(context, "1930")
    })
    Text(stringResource(R.string.alert_call_1930_note), style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary)

    if (!over) {
        SecondaryButton(stringResource(R.string.alert_wait, minutesLeft), onClick = {
            vm.onAlertAction(AlertAction.WAITED)
            PauseReminder.schedule(context.applicationContext, vm.pauseEndsAtMs, user.language)
            onWaited()
        })
    }
    if (onKnowThem != null) {
        TextButton(onClick = { asking = true }, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.alert_know_them), color = CacheColors.PrimaryLight)
        }
    }

    if (asking && onKnowThem != null) {
        var why by remember { mutableStateOf<KnowWhy?>(null) }
        ModalBottomSheet(onDismissRequest = { asking = false }, containerColor = CacheColors.Surface) {
            Column(
                modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 20.dp, vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Text(stringResource(R.string.alert_know_title), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                Text(stringResource(R.string.alert_know_note), style = MaterialTheme.typography.bodyMedium, color = CacheColors.TextSecondary)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    KnowWhy.entries.forEach { option ->
                        FilterChip(
                            selected = why == option,
                            onClick = { why = option },
                            label = { Text(stringResource(option.label)) },
                        )
                    }
                }
                PrimaryButton(stringResource(R.string.alert_know_continue), enabled = why != null, onClick = {
                    val chosen = why ?: return@PrimaryButton
                    asking = false
                    onKnowThem(chosen)
                })
            }
        }
    }
}

private val KnowWhy.label: Int
    get() = when (this) {
        KnowWhy.FAMILY -> R.string.alert_know_family
        KnowWhy.FRIEND -> R.string.alert_know_friend
        KnowWhy.SHOP -> R.string.alert_know_shop
        KnowWhy.LANDLORD -> R.string.alert_know_landlord
        KnowWhy.EMPLOYER -> R.string.alert_know_employer
        KnowWhy.OTHER -> R.string.alert_know_other
    }

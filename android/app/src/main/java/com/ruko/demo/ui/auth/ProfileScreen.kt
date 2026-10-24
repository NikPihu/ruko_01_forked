package com.ruko.demo.ui.auth

import com.ruko.demo.shield.ChatListener
import com.ruko.demo.shield.ShieldController
import android.content.Context
import androidx.compose.ui.platform.LocalContext
import androidx.compose.foundation.clickable
import android.provider.Settings
import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.data.Masks
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.CacheIcons
import com.ruko.demo.ui.CacheTopBar
import com.ruko.demo.ui.InitialAvatar
import com.ruko.demo.ui.Screen
import com.ruko.demo.ui.SecondaryButton
import com.ruko.demo.ui.cacheCard

/** Everything stored about the user, masked, with the Scam Shield switches and data controls. */
@Composable
fun ProfileScreen(vm: AuthViewModel, onBack: () -> Unit) {
    val p = vm.profile ?: return
    val c = vm.consents
    var askDelete by remember { mutableStateOf(false) }
    var askDeleteHistory by remember { mutableStateOf(false) }
    val appContext = LocalContext.current.applicationContext
    val notAdded = stringResource(R.string.profile_not_added)

    Screen {
        CacheTopBar(stringResource(R.string.profile_title), onBack)

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            InitialAvatar(p.fullName, size = 64.dp)
            Column {
                Text(p.fullName, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
                Text(p.upiId, style = MaterialTheme.typography.bodyLarge, color = CacheColors.PrimaryLight)
            }
        }

        InfoCard(
            stringResource(R.string.profile_personal),
            stringResource(R.string.profile_mobile) to Masks.mobile(p.mobile),
            stringResource(R.string.profile_email) to Masks.email(p.email),
            stringResource(R.string.profile_dob) to Masks.dateOfBirth(p.dateOfBirth),
            stringResource(R.string.profile_language) to
                stringResource(if (p.language == "hi") R.string.language_hi else R.string.language_en),
            stringResource(R.string.profile_pan) to (p.pan?.let(Masks::pan) ?: notAdded),
        )
        InfoCard(
            stringResource(R.string.profile_bank),
            p.bankName to Masks.account(p.accountLast4),
            stringResource(R.string.ifsc_label) to p.ifsc,
            stringResource(R.string.profile_upi) to p.upiId,
            stringResource(R.string.profile_trusted) to
                (p.trustedName?.let { name -> "$name, ${p.trustedMobile?.let(Masks::mobile)}" } ?: notAdded),
        )

        Text(stringResource(R.string.profile_safety), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        ConsentRow(R.string.consent_calls, R.string.consent_calls_desc, c.callSignals) { vm.updateConsents(c.copy(callSignals = it)) }
        ConsentRow(R.string.consent_apps, R.string.consent_apps_desc, c.appChecks) { vm.updateConsents(c.copy(appChecks = it)) }
        ConsentRow(R.string.consent_session, R.string.consent_session_desc, c.sessionSignals) { vm.updateConsents(c.copy(sessionSignals = it)) }
        ConsentRow(R.string.consent_sms, R.string.consent_sms_desc, c.smsLure) {
            // Watching money alerts needs SMS checks; switching SMS off switches it off too.
            vm.updateConsents(c.copy(smsLure = it, moneyWatch = c.moneyWatch && it, shareAccounts = c.shareAccounts && it, shareReceived = c.shareReceived && it))
        }
        ConsentRow(R.string.consent_watch, R.string.consent_watch_desc, c.moneyWatch) {
            vm.updateConsents(c.copy(moneyWatch = it, smsLure = c.smsLure || it, shareAccounts = c.shareAccounts && it, shareReceived = c.shareReceived && it))
        }
        ConsentRow(R.string.consent_chat, R.string.consent_chat_desc, c.chatLure) {
            vm.updateConsents(c.copy(chatLure = it))
            if (it && !ChatListener.granted(appContext)) openNotificationAccess(appContext)
        }
        if (c.chatLure && !ChatListener.granted(appContext)) {
            TextButton(onClick = { openNotificationAccess(appContext) }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.consent_chat_allow), color = CacheColors.PrimaryLight)
            }
        }
        ConsentRow(R.string.consent_early, R.string.consent_early_desc, c.earlyWarnings) { vm.updateConsents(c.copy(earlyWarnings = it)) }
        if (c.moneyWatch) {
            ConsentRow(R.string.consent_share, R.string.consent_share_desc, c.shareAccounts) { vm.updateConsents(c.copy(shareAccounts = it)) }
            ConsentRow(R.string.consent_share_received, R.string.consent_share_received_desc, c.shareReceived) { vm.updateConsents(c.copy(shareReceived = it)) }
            KeepRunningRow()
            TextButton(onClick = { askDeleteHistory = true }, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.profile_delete_history), color = CacheColors.Warning, style = MaterialTheme.typography.titleMedium)
            }
        }

        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Icon(CacheIcons.Shield, contentDescription = null, tint = CacheColors.PrimaryLight, modifier = Modifier.size(18.dp))
            Text(stringResource(R.string.profile_storage), style = MaterialTheme.typography.bodyMedium, color = CacheColors.TextSecondary)
        }
        SecondaryButton(stringResource(R.string.profile_lock), vm::lock)
        TextButton(onClick = { askDelete = true }, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.profile_delete), color = CacheColors.Danger, style = MaterialTheme.typography.titleMedium)
        }
    }

    if (askDeleteHistory) {
        ConfirmDeleteDialog(
            title = R.string.delete_history_title,
            body = R.string.delete_history_body,
            confirm = R.string.delete_history_confirm,
            onConfirm = {
                askDeleteHistory = false
                Thread { ShieldController.deleteHistory(appContext) }.start()
            },
            onDismiss = { askDeleteHistory = false },
        )
    }

    if (askDelete) {
        ConfirmDeleteDialog(
            title = R.string.delete_title,
            body = R.string.delete_body,
            confirm = R.string.delete_confirm,
            onConfirm = {
                askDelete = false
                vm.deleteAccount()
            },
            onDismiss = { askDelete = false },
        )
    }
}

@Composable
private fun InfoCard(title: String, vararg rows: Pair<String, String>) {
    Column(Modifier.fillMaxWidth().cacheCard().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        rows.forEachIndexed { index, (label, value) ->
            if (index > 0) HorizontalDivider(color = CacheColors.CardBorder)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Text(label, style = MaterialTheme.typography.bodyMedium, color = CacheColors.TextSecondary)
                Text(value, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

/** Some phones (Xiaomi, Oppo, Vivo, Realme) stop background apps; this opens the setting that allows it. */
@Composable
private fun KeepRunningRow() {
    val context = LocalContext.current
    Row(
        modifier = Modifier.fillMaxWidth().cacheCard().clickable {
            runCatching {
                context.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
        }.padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Icon(CacheIcons.Shield, contentDescription = null, tint = CacheColors.PrimaryLight, modifier = Modifier.size(20.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.profile_keep_running), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(R.string.profile_keep_running_desc), style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary)
        }
    }
}

/** Android's own screen for notification access; only the user can switch it on there. */
private fun openNotificationAccess(context: Context) {
    context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}

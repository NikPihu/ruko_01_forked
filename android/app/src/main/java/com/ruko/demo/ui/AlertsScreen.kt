package com.ruko.demo.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.data.AlertEntry
import com.ruko.demo.data.AlertKind
import com.ruko.demo.data.AlertLogFile
import com.ruko.demo.data.PaymentRecord
import com.ruko.demo.shield.AlertRecorder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Payments Scam Shield stepped in on: an explanation (T2), a pause (T3) or a bank review (T4). */
private val STOPPED = setOf("T2", "T3", "T4")

/**
 * Everything Scam Shield warned about, newest first: suspicious messages and other warnings the
 * phone showed (kept by [AlertRecorder], even when the notification was dismissed) and the payments
 * it stepped in on. Never a score (rule 4) and never a message's text (rule 2).
 */
@Composable
fun AlertsScreen(history: List<PaymentRecord>, onMessages: () -> Unit, onHistory: () -> Unit, onBack: () -> Unit) {
    val context = LocalContext.current.applicationContext
    val version by AlertRecorder.version.collectAsState()
    val log by produceState(AlertLogFile(), version) { value = withContext(Dispatchers.IO) { AlertRecorder.load(context) } }
    LaunchedEffect(version) { withContext(Dispatchers.IO) { AlertRecorder.markSeen(context) } }
    val stopped = history.filter { it.tier in STOPPED }.sortedByDescending { it.ts }

    Screen {
        CacheTopBar(stringResource(R.string.alerts_title), onBack)
        if (log.entries.isEmpty() && stopped.isEmpty()) {
            Column(Modifier.fillMaxWidth().cacheCard().padding(20.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(stringResource(R.string.alerts_empty_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                Text(stringResource(R.string.alerts_empty_body), style = MaterialTheme.typography.bodyMedium, color = CacheColors.TextSecondary)
            }
            return@Screen
        }
        if (log.entries.isNotEmpty()) {
            SectionTitle(stringResource(R.string.alerts_section_warnings))
            log.entries.forEach { e ->
                val isNew = e.ts > log.seenAt
                WarningRow(e, isNew, onClick = if (e.kind == AlertKind.SCAM_MESSAGE || e.kind == AlertKind.OTP_ON_CALL) onMessages else null)
            }
        }
        if (stopped.isNotEmpty()) {
            SectionTitle(stringResource(R.string.alerts_section_payments))
            stopped.forEach { p -> PaymentRow(p, onHistory) }
        }
    }
}

@Composable
private fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleSmall, color = CacheColors.TextSecondary, modifier = Modifier.padding(top = 4.dp))
}

@Composable
private fun WarningRow(e: AlertEntry, isNew: Boolean, onClick: (() -> Unit)?) {
    val (icon, tint) = when (e.kind) {
        AlertKind.SCAM_MESSAGE -> CacheIcons.Message to CacheColors.Warning
        AlertKind.OTP_ON_CALL -> CacheIcons.Phone to CacheColors.Danger
        AlertKind.TASK_SCAM, AlertKind.RING_CONFIRMED -> CacheIcons.Warning to CacheColors.Danger
        AlertKind.PAID_OTHER_APP -> CacheIcons.Rupee to CacheColors.Warning
    }
    val title = stringResource(
        when (e.kind) {
            AlertKind.SCAM_MESSAGE -> R.string.alert_scam_message_title
            AlertKind.OTP_ON_CALL -> R.string.msg_otp_call_title
            AlertKind.TASK_SCAM -> R.string.shield_active_title
            AlertKind.PAID_OTHER_APP -> R.string.shield_out_title
            AlertKind.RING_CONFIRMED -> R.string.shield_confirmed_title
        },
    )
    val detail = when (e.kind) {
        AlertKind.SCAM_MESSAGE -> {
            val where = stringResource(if (e.source == "chat") R.string.alert_in_chat else R.string.alert_in_sms)
            val kind = stringResource(scamTagRes(e.tag ?: "other"))
            "$kind · $where" + if (e.aiWritten) " · " + stringResource(R.string.alert_ai_written) else ""
        }
        else -> null
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .cacheCard(borderColor = if (isNew) tint.copy(alpha = 0.6f) else CacheColors.CardBorder)
            .let { if (onClick != null) it.clickable(onClick = onClick) else it }
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        AlertIcon(icon, tint)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
            detail?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary) }
            Text(whenText(e.ts), style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary)
        }
        if (isNew) {
            Text(stringResource(R.string.alert_new), style = MaterialTheme.typography.labelSmall, color = tint, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun PaymentRow(p: PaymentRecord, onClick: () -> Unit) {
    val tint = shieldColor(p.tier)
    Row(
        modifier = Modifier.fillMaxWidth().cacheCard().clickable(onClick = onClick).padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        AlertIcon(CacheIcons.Shield, tint)
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(
                stringResource(R.string.alert_payment_title, formatInr(p.amountInr), p.payeeName ?: p.payee),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                listOfNotNull(shieldText(p.tier), scamTypeText(p.playbook)).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = tint,
            )
            Text("${whenText(p.ts)} · ${statusText(p.state)}", style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary)
        }
    }
}

@Composable
private fun AlertIcon(icon: ImageVector, tint: Color) {
    Box(Modifier.size(40.dp).clip(CircleShape).background(tint.copy(alpha = 0.16f)), contentAlignment = Alignment.Center) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(22.dp))
    }
}

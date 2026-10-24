package com.ruko.demo.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.data.PaymentRecord
import com.ruko.demo.data.PaymentState
import com.ruko.demo.shield.ReceivedPayment
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val WHEN = DateTimeFormatter.ofPattern("d MMM yyyy, h:mm a", Locale.forLanguageTag("en-IN"))
    .withZone(ZoneId.of("Asia/Kolkata"))

private fun whenText(ms: Long): String = WHEN.format(Instant.ofEpochMilli(ms))

/**
 * Every payment started in this app, each with its payment ID (the request_id the server knows it
 * by), Scam Shield's decision and what the user did; the phone's own record, merged with the
 * server's (GET /v1/me/payments) when the server can be reached. And, while the money watch is on,
 * the money received that the watcher read from bank SMS alerts. One list, newest first.
 */
@Composable
fun HistoryScreen(
    history: List<PaymentRecord>,
    received: List<ReceivedPayment>,
    watcherOn: Boolean,
    onOpen: () -> Unit,
    onBack: () -> Unit,
) {
    var open by remember { mutableStateOf<PaymentRecord?>(null) }
    var openReceived by remember { mutableStateOf<ReceivedPayment?>(null) }
    // Opening the list is a good moment to send any outcome that could not be sent before.
    LaunchedEffect(Unit) { onOpen() }

    Screen {
        CacheTopBar(stringResource(R.string.history_title), onBack)
        Text(stringResource(R.string.history_note), style = MaterialTheme.typography.bodyMedium, color = CacheColors.TextSecondary)
        Text(
            stringResource(if (watcherOn) R.string.history_received_note else R.string.history_received_off),
            style = MaterialTheme.typography.bodySmall,
            color = CacheColors.TextSecondary,
        )
        if (history.isEmpty() && received.isEmpty()) {
            Text(
                stringResource(R.string.history_empty),
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.fillMaxWidth().cacheCard().padding(18.dp),
            )
        }
        val rows: List<Pair<Long, @Composable () -> Unit>> =
            history.map { p -> p.ts to @Composable { HistoryRow(p, onClick = { open = p }) } } +
                received.map { r -> r.ts to @Composable { ReceivedRow(r, onClick = { openReceived = r }) } }
        rows.sortedByDescending { it.first }.forEach { it.second() }
    }

    open?.let { p -> PaymentDetail(p, onClose = { open = null }) }
    openReceived?.let { r -> ReceivedDetail(r, onClose = { openReceived = null }) }
}

@Composable
private fun senderText(r: ReceivedPayment): String =
    r.senderName ?: r.sender ?: stringResource(R.string.history_received_unknown_sender)

@Composable
private fun ReceivedRow(r: ReceivedPayment, onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().cacheCard().clickable(onClick = onClick).padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(Modifier.size(10.dp).clip(CircleShape).background(CacheColors.Success))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(senderText(r), style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (r.senderName != null && r.sender != null) {
                Text(r.sender, style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary, maxLines = 1)
            }
            Text(
                "${whenText(r.ts)} · ${stringResource(R.string.history_received_source)}",
                style = MaterialTheme.typography.bodySmall,
                color = CacheColors.TextSecondary,
            )
        }
        Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text("+" + formatInr(r.amountInr), style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold, color = CacheColors.Success)
            Text(stringResource(R.string.history_received), style = MaterialTheme.typography.bodySmall, color = CacheColors.Success)
        }
    }
}

@Composable
private fun ReceivedDetail(r: ReceivedPayment, onClose: () -> Unit) {
    AlertDialog(
        onDismissRequest = onClose,
        containerColor = CacheColors.Card,
        title = { Text("+" + formatInr(r.amountInr), fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Field(stringResource(R.string.history_from)) {
                    Text(listOfNotNull(r.senderName, r.sender).joinToString(" · ")
                        .ifEmpty { stringResource(R.string.history_received_unknown_sender) })
                }
                Field(stringResource(R.string.history_when)) { Text(whenText(r.ts)) }
                Field(stringResource(R.string.history_status)) {
                    Text(stringResource(R.string.history_received), color = CacheColors.Success)
                }
                Text(stringResource(R.string.history_received_detail), style = MaterialTheme.typography.bodySmall,
                    color = CacheColors.TextSecondary)
            }
        },
        confirmButton = { TextButton(onClick = onClose) { Text(stringResource(R.string.history_close)) } },
    )
}

@Composable
private fun HistoryRow(p: PaymentRecord, onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().cacheCard().clickable(onClick = onClick).padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Box(Modifier.size(10.dp).clip(CircleShape).background(shieldColor(p.tier)))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(p.payeeName ?: p.payee, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (p.payeeName != null) {
                Text(p.payee, style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary, maxLines = 1)
            }
            Text(
                "${whenText(p.ts)} · ${shieldText(p.tier)}",
                style = MaterialTheme.typography.bodySmall,
                color = CacheColors.TextSecondary,
            )
            Text(
                "${stringResource(R.string.history_payment_id)} ${p.id.take(8)}…",
                style = MaterialTheme.typography.bodySmall,
                fontFamily = FontFamily.Monospace,
                color = CacheColors.TextSecondary,
            )
        }
        Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(formatInr(p.amountInr), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(statusText(p.state), style = MaterialTheme.typography.bodySmall, color = statusColor(p.state))
        }
    }
}

@Composable
private fun PaymentDetail(p: PaymentRecord, onClose: () -> Unit) {
    val context = LocalContext.current
    val copied = stringResource(R.string.history_copied)
    AlertDialog(
        onDismissRequest = onClose,
        containerColor = CacheColors.Card,
        title = { Text(formatInr(p.amountInr), fontWeight = FontWeight.Bold) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Field(stringResource(R.string.history_payment_id)) {
                    SelectionContainer {
                        Text(p.id, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodyMedium)
                    }
                }
                TextButton(onClick = {
                    val cm = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    cm.setPrimaryClip(ClipData.newPlainText("Payment ID", p.id))
                    Toast.makeText(context, copied, Toast.LENGTH_SHORT).show()
                }) { Text(stringResource(R.string.history_copy), color = CacheColors.PrimaryLight) }
                Field(stringResource(R.string.history_to)) { Text(listOfNotNull(p.payeeName, p.payee).joinToString(" · ")) }
                Field(stringResource(R.string.history_when)) { Text(whenText(p.ts)) }
                Field(stringResource(R.string.history_entered)) { Text(entryText(p.entryMethod)) }
                Field(stringResource(R.string.history_shield)) { Text(shieldText(p.tier), color = shieldColor(p.tier)) }
                scamTypeText(p.playbook)?.let { Field(stringResource(R.string.history_scam_type)) { Text(it) } }
                val reasons = p.reasons.take(3).mapNotNull { reasonText(it) }
                if (reasons.isNotEmpty()) {
                    Field(stringResource(R.string.history_reasons)) {
                        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) { reasons.forEach { Text("• $it") } }
                    }
                }
                Field(stringResource(R.string.history_status)) {
                    Text(
                        statusText(p.state) + (p.outcomeTs?.let { " · ${whenText(it)}" } ?: ""),
                        color = statusColor(p.state),
                    )
                }
                if (p.state != PaymentState.PENDING) {
                    Field(stringResource(R.string.history_sync)) {
                        Text(stringResource(if (p.reported) R.string.history_sync_done else R.string.history_sync_waiting))
                    }
                }
                if (p.serverSeen) {
                    Text(stringResource(R.string.history_server_seen), style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary)
                }
            }
        },
        confirmButton = { TextButton(onClick = onClose) { Text(stringResource(R.string.history_close)) } },
    )
}

@Composable
private fun scamTypeText(playbook: String?): String? = when (playbook) {
    "digital_arrest" -> stringResource(R.string.fraud_digital_arrest)
    "task_job" -> stringResource(R.string.fraud_task_job)
    "trading_group" -> stringResource(R.string.fraud_trading_group)
    "fake_kyc_apk" -> stringResource(R.string.fraud_fake_kyc_apk)
    "refund_qr" -> stringResource(R.string.fraud_refund_qr)
    "fake_customer_care" -> stringResource(R.string.fraud_fake_customer_care)
    else -> null
}

@Composable
private fun Field(label: String, value: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, style = MaterialTheme.typography.labelMedium, color = CacheColors.TextSecondary)
        Row(Modifier.width(280.dp)) { value() }
    }
}

@Composable
private fun shieldText(tier: String?): String = stringResource(
    when (tier) {
        "T0" -> R.string.history_result_t0
        "T1" -> R.string.history_result_t1
        "T2" -> R.string.history_result_t2
        "T3", "T4" -> R.string.history_result_t3
        else -> R.string.history_result_unavailable
    },
)

private fun shieldColor(tier: String?): Color = when (tier) {
    "T0" -> CacheColors.Success
    "T1" -> CacheColors.Info
    "T2" -> CacheColors.Warning
    "T3", "T4" -> CacheColors.Danger
    else -> CacheColors.TextSecondary
}

@Composable
private fun statusText(state: PaymentState): String = stringResource(
    when (state) {
        PaymentState.COMPLETED -> R.string.history_status_completed
        PaymentState.CANCELLED -> R.string.history_status_cancelled
        PaymentState.PENDING -> R.string.history_status_pending
    },
)

private fun statusColor(state: PaymentState): Color = when (state) {
    PaymentState.COMPLETED -> CacheColors.Success
    PaymentState.CANCELLED -> CacheColors.TextSecondary
    PaymentState.PENDING -> CacheColors.Warning
}

@Composable
private fun entryText(method: String): String = stringResource(
    when (method) {
        "contact" -> R.string.entry_contact
        "qr" -> R.string.entry_qr
        "collect" -> R.string.entry_collect
        else -> R.string.entry_typed
    },
)

package com.ruko.demo.ui

import android.Manifest.permission.READ_SMS
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.ruko.demo.R
import com.ruko.demo.data.Consents
import com.ruko.demo.signals.MessageLabel
import com.ruko.demo.signals.MessageScan
import com.ruko.demo.signals.Signals
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private val WHEN = DateTimeFormatter.ofPattern("d MMM, h:mm a", Locale.forLanguageTag("en-IN")).withZone(ZoneId.of("Asia/Kolkata"))

/**
 * "Message check" (A5): the last 3 days of SMS, each with its warning labels, all worked out on
 * the phone. Message text never leaves it. Needs the "SMS scam check" consent (off by default).
 */
@Composable
fun MessageCheckScreen(consents: Consents, onProfile: () -> Unit, onBack: () -> Unit) {
    val context = LocalContext.current
    var granted by remember { mutableStateOf(ContextCompat.checkSelfPermission(context, READ_SMS) == PackageManager.PERMISSION_GRANTED) }
    var messages by remember { mutableStateOf<List<MessageLabel>?>(null) }
    var refresh by remember { mutableIntStateOf(0) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }

    LaunchedEffect(consents.smsLure, granted, refresh) {
        messages = if (consents.smsLure && granted) {
            withContext(Dispatchers.Default) {
                MessageScan.scan(context.applicationContext, Signals.classifier, Signals.aiText, System.currentTimeMillis())
            }
        } else {
            null
        }
    }

    Screen {
        CacheTopBar(stringResource(R.string.msg_title), onBack)
        Text(stringResource(R.string.msg_note), style = MaterialTheme.typography.bodyMedium, color = CacheColors.TextSecondary)
        when {
            !consents.smsLure -> Notice(stringResource(R.string.msg_consent_off)) {
                PrimaryButton(stringResource(R.string.msg_open_profile), onClick = onProfile)
            }
            !granted -> Notice(stringResource(R.string.msg_permission)) {
                PrimaryButton(stringResource(R.string.msg_allow), onClick = { launcher.launch(READ_SMS) })
            }
            messages == null -> Text(stringResource(R.string.msg_checking), style = MaterialTheme.typography.bodyLarge)
            messages!!.isEmpty() -> Notice(stringResource(R.string.msg_empty)) {}
            else -> {
                val list = messages!!
                val flagged = list.count { it.anyWarning }
                Text(
                    stringResource(R.string.msg_summary, list.size, flagged),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                // Warnings first, then the rest, each group newest first.
                list.sortedWith(compareByDescending<MessageLabel> { it.otpDuringCall }.thenByDescending { it.anyWarning }.thenByDescending { it.ts })
                    .forEach { MessageRow(it) }
                SecondaryButton(stringResource(R.string.msg_refresh), onClick = { refresh++ })
            }
        }
    }
}

@Composable
private fun Notice(text: String, action: @Composable () -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth().cacheCard().padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text(text, style = MaterialTheme.typography.bodyLarge)
        action()
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun MessageRow(m: MessageLabel) {
    val border = when {
        m.otpDuringCall || m.scamTag != null -> CacheColors.Danger.copy(alpha = 0.7f)
        m.aiWritten == true || m.unclear -> CacheColors.Warning.copy(alpha = 0.7f)
        else -> CacheColors.CardBorder
    }
    Column(
        modifier = Modifier.fillMaxWidth().cacheCard(borderColor = border).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            "${m.sender.ifBlank { "?" }} · ${WHEN.format(Instant.ofEpochMilli(m.ts))}",
            style = MaterialTheme.typography.bodySmall,
            color = CacheColors.TextSecondary,
        )
        Text(m.preview, style = MaterialTheme.typography.bodyMedium, maxLines = 3, overflow = TextOverflow.Ellipsis)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            m.scamTag?.let { Label(stringResource(R.string.msg_label_scam, scamTagText(it)), CacheColors.Danger) }
            if (m.unclear) Label(stringResource(R.string.msg_label_unclear), CacheColors.Warning)
            if (m.aiWritten == true) Label(stringResource(R.string.msg_label_ai), CacheColors.Warning)
            if (m.otp) Label(stringResource(R.string.msg_label_otp), CacheColors.Info)
            if (!m.anyWarning) Label(stringResource(R.string.msg_label_none), CacheColors.Success)
        }
        if (m.aiWritten == true) {
            Text(stringResource(R.string.msg_ai_note), style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary)
        }
        if (m.otpDuringCall) {
            Text(
                stringResource(R.string.msg_otp_call_text),
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
                color = CacheColors.Danger,
            )
        }
    }
}

@Composable
private fun Label(text: String, color: Color) {
    Text(
        text,
        style = MaterialTheme.typography.labelMedium,
        color = color,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(color.copy(alpha = 0.15f)).padding(horizontal = 10.dp, vertical = 4.dp),
    )
}

@Composable
private fun scamTagText(tag: String): String = stringResource(scamTagRes(tag))


package com.ruko.demo.ui

import android.Manifest.permission.READ_CALL_LOG
import android.Manifest.permission.READ_CONTACTS
import android.Manifest.permission.READ_PHONE_STATE
import android.Manifest.permission.READ_SMS
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import com.ruko.demo.R
import com.ruko.demo.data.Consents
import com.ruko.demo.signals.ShieldPermissions
import com.ruko.demo.shield.ShieldController
import com.ruko.demo.signals.Signals

/**
 * Asks for the runtime permissions the user's Scam Shield consents need. It asks once on its
 * own, then stays on Home as a card until granted; if Android stops showing the dialog, the
 * button opens the app's settings instead.
 */
@Composable
fun ShieldPermissionCard(consents: Consents, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val activity = LocalActivity.current
    var missing by remember(consents) { mutableStateOf(ShieldPermissions.missing(context, consents)) }
    var blocked by remember { mutableStateOf(false) }

    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        missing = ShieldPermissions.missing(context, consents)
        Signals.sensor.start()
        // Permissions granted after the switch went on: run the 30-day backfill now.
        if (consents.moneyWatch) ShieldController.enable(context.applicationContext)
        // No rationale after a refusal means "don't ask again": only Settings can grant it now.
        blocked = missing.isNotEmpty() && activity != null &&
            missing.none { activity.shouldShowRequestPermissionRationale(it) }
    }

    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        missing = ShieldPermissions.missing(context, consents)
        Signals.sensor.start()
    }
    LaunchedEffect(consents) {
        if (missing.isNotEmpty() && !Signals.askedForPermissions) {
            Signals.askedForPermissions = true
            launcher.launch(missing.toTypedArray())
        }
    }

    if (missing.isEmpty()) return
    val what = missing.map {
        when (it) {
            READ_PHONE_STATE -> stringResource(R.string.perm_phone)
            READ_CONTACTS -> stringResource(R.string.perm_contacts)
            READ_CALL_LOG -> stringResource(R.string.perm_call_log)
            READ_SMS -> stringResource(R.string.perm_sms)
            android.Manifest.permission.RECEIVE_SMS -> stringResource(R.string.perm_receive_sms)
            "android.permission.POST_NOTIFICATIONS" -> stringResource(R.string.perm_notifications)
            else -> it.substringAfterLast('.')
        }
    }.distinct().joinToString(", ")

    Column(
        modifier = modifier
            .fillMaxWidth()
            .cacheCard(borderColor = CacheColors.Warning.copy(alpha = 0.6f))
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(CacheIcons.Shield, contentDescription = null, tint = CacheColors.Warning, modifier = Modifier.size(22.dp))
            Text(stringResource(R.string.perm_title), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        }
        Text(stringResource(R.string.perm_body, what), style = MaterialTheme.typography.bodyMedium, color = CacheColors.TextSecondary)
        if (blocked) {
            Text(stringResource(R.string.perm_denied), style = MaterialTheme.typography.bodySmall, color = CacheColors.Warning)
            PrimaryButton(stringResource(R.string.perm_settings), onClick = {
                context.startActivity(
                    Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
            })
        } else {
            PrimaryButton(stringResource(R.string.perm_allow), onClick = { launcher.launch(missing.toTypedArray()) })
        }
    }
}

/** Red pill shown wherever a debug override is changing what gets sent. */
@Composable
fun SimulatedPill(fields: List<String>, modifier: Modifier = Modifier) {
    if (fields.isEmpty()) return
    Text(
        text = stringResource(R.string.simulated) + "  " + fields.joinToString(", "),
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Bold,
        color = CacheColors.Danger,
        modifier = modifier
            .cacheCard(radius = 10.dp, borderColor = CacheColors.Danger.copy(alpha = 0.7f))
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}

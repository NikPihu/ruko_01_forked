package com.ruko.demo.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.shield.EpisodeState
import com.ruko.demo.shield.EpisodeStore
import com.ruko.demo.shield.EpisodeTracker
import com.ruko.demo.shield.ShieldController
import com.ruko.demo.shield.ShieldData
import com.ruko.demo.shield.ShieldNotifier.rupees

/** "Watching money alerts" or "Money alerts off", next to Money Transfers on Home. */
@Composable
fun ShieldStatusChip(watching: Boolean) {
    val tint = if (watching) CacheColors.Accent else CacheColors.TextSecondary
    Row(
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(tint.copy(alpha = 0.18f))
            .border(1.dp, tint.copy(alpha = 0.5f), RoundedCornerShape(50))
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Icon(CacheIcons.Shield, contentDescription = null, tint = tint, modifier = Modifier.size(16.dp))
        Text(
            stringResource(if (watching) R.string.shield_chip_on else R.string.shield_chip_off),
            style = MaterialTheme.typography.labelLarge,
            color = if (watching) Color(0xFFFED7AA) else CacheColors.TextSecondary,
        )
    }
}

/**
 * The background watcher's episode on the Alerts screen, once there is a pattern to show: ACTIVE (bait, then
 * escalating payments to new payees) or confirmed "high" by the server. A WATCHING episode (small
 * money from a stranger, nothing more) stays off Home. The numbers in words, how the scam works,
 * and three ways out. It only warns; payments are never blocked here.
 */
@Composable
fun EpisodeCard(data: ShieldData?, trustedName: String?, trustedMobile: String?, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val ep = data?.watcher?.episode ?: return
    val active = ep.state == EpisodeState.ACTIVE
    val confirmed = ep.state.live && data.serverRisk == "high"
    if (!active && !confirmed) return
    val s = EpisodeTracker(EpisodeStore.rules(context), true, data.watcher).summary(ShieldController.now())
    var howItWorks by remember { mutableStateOf(false) }
    var confirmDismiss by remember { mutableStateOf(false) }
    val accent = CacheColors.Danger

    Column(
        modifier = modifier.fillMaxWidth().cacheCard(borderColor = accent.copy(alpha = 0.7f)).padding(18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Icon(CacheIcons.Warning, contentDescription = null, tint = accent, modifier = Modifier.size(26.dp))
            Text(
                stringResource(R.string.episode_title_active),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
            )
        }
        Text(
            text = if (active) {
                stringResource(
                    R.string.episode_body_active,
                    rupees(s.baitInr ?: 0.0), s.baitCredits ?: 0, rupees(s.outsInr ?: 0.0), s.newPayees ?: 0,
                )
            } else {
                stringResource(R.string.episode_body_watching, rupees(s.baitInr ?: 0.0), s.baitCredits ?: 0)
            },
            style = MaterialTheme.typography.bodyLarge,
        )
        if (confirmed) {
            Text(stringResource(R.string.shield_confirmed_text), style = MaterialTheme.typography.bodyLarge, color = CacheColors.Danger)
        }
        TextButton(onClick = { howItWorks = true }) {
            Text(stringResource(R.string.episode_how), color = CacheColors.PrimaryLight)
        }
        PrimaryButton(stringResource(R.string.episode_call_1930), onClick = { dial(context, "1930") })
        if (!trustedMobile.isNullOrBlank()) {
            SecondaryButton(stringResource(R.string.episode_call_trusted, trustedName ?: trustedMobile), onClick = { dial(context, trustedMobile) })
        }
        TextButton(onClick = { confirmDismiss = true }, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.episode_dismiss), color = CacheColors.TextSecondary)
        }
    }

    if (howItWorks) {
        AlertDialog(
            onDismissRequest = { howItWorks = false },
            title = { Text(stringResource(R.string.episode_how)) },
            text = { Text(stringResource(R.string.episode_how_body)) },
            confirmButton = { TextButton(onClick = { howItWorks = false }) { Text(stringResource(R.string.episode_ok)) } },
        )
    }
    if (confirmDismiss) {
        AlertDialog(
            onDismissRequest = { confirmDismiss = false },
            title = { Text(stringResource(R.string.episode_dismiss)) },
            text = { Text(stringResource(R.string.episode_dismiss_body)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmDismiss = false
                    ShieldController.dismissAsync(context.applicationContext)
                }) { Text(stringResource(R.string.episode_dismiss_confirm)) }
            },
            dismissButton = { TextButton(onClick = { confirmDismiss = false }) { Text(stringResource(R.string.episode_keep)) } },
        )
    }
}

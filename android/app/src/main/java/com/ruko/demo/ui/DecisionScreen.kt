package com.ruko.demo.ui

import androidx.compose.foundation.background
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.BuildConfig
import com.ruko.demo.R

/** Colour that marks how serious a tier is. */
private fun tierColor(tier: String?): Color = when (tier) {
    "T1" -> CacheColors.Info
    "T2" -> CacheColors.Warning
    "T3" -> CacheColors.Danger
    "T4" -> CacheColors.Info
    "T0" -> CacheColors.Success
    else -> CacheColors.TextSecondary
}

/**
 * Placeholder that prints the tier and reasons (guide step 5). The T1 banner, T2 card,
 * T3 full screen and T4 review screen replace it in step 7. Never shows a score.
 */
@Composable
fun DecisionScreen(vm: PaymentViewModel, onContinue: () -> Unit, onCancel: () -> Unit) {
    val result = vm.decision as? Decision.Result
    val accent = tierColor(result?.response?.tier)

    Screen {
        CacheTopBar(stringResource(R.string.decision_title))

        Column(
            modifier = Modifier.fillMaxWidth().cacheCard(borderColor = accent.copy(alpha = 0.6f)).padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Box(
                    modifier = Modifier.size(52.dp).clip(CircleShape).background(accent.copy(alpha = 0.18f)),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = if (result == null) CacheIcons.Shield else CacheIcons.Warning,
                        contentDescription = null,
                        tint = accent,
                        modifier = Modifier.size(28.dp),
                    )
                }
                Text(
                    text = if (result != null) {
                        stringResource(R.string.decision_tier, result.response.tier)
                    } else {
                        stringResource(R.string.decision_unavailable)
                    },
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Bold,
                )
            }

            if (result != null) {
                val reasons = result.response.reasons.take(3).mapNotNull { reasonText(it) }
                if (reasons.isNotEmpty()) {
                    Text(
                        text = stringResource(R.string.decision_why),
                        style = MaterialTheme.typography.titleMedium,
                        color = CacheColors.TextSecondary,
                    )
                    reasons.forEach { reason ->
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            Box(
                                Modifier
                                    .padding(top = 8.dp)
                                    .size(8.dp)
                                    .clip(CircleShape)
                                    .background(accent),
                            )
                            Text(reason, style = MaterialTheme.typography.bodyLarge)
                        }
                    }
                }
                if (BuildConfig.DEBUG) {
                    Text(
                        text = "debug: ${result.millis} ms, message_key=${result.response.messageKey}",
                        style = MaterialTheme.typography.bodySmall,
                        color = CacheColors.TextSecondary,
                    )
                }
            } else {
                Text(
                    text = stringResource(R.string.decision_unavailable_body),
                    style = MaterialTheme.typography.bodyLarge,
                    color = CacheColors.TextSecondary,
                )
            }
        }

        Text(
            text = stringResource(R.string.decision_placeholder),
            style = MaterialTheme.typography.bodySmall,
            color = CacheColors.TextSecondary,
        )
        PrimaryButton(stringResource(R.string.decision_continue), onContinue)
        SecondaryButton(stringResource(R.string.decision_cancel), onCancel)
    }
}

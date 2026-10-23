package com.ruko.demo.ui.alerts

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
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.CacheIcons
import com.ruko.demo.ui.Decision
import com.ruko.demo.ui.PaymentViewModel
import com.ruko.demo.ui.cacheCard
import com.ruko.demo.ui.reasonText

/** T1: one gentle tip at the top of the PIN screen. No extra screen, no extra tap. */
@Composable
fun TipBanner(vm: PaymentViewModel, language: String?) {
    val result = vm.decision as? Decision.Result ?: return
    if (vm.alertTier != "T1") return
    LaunchedEffect(result.response.requestId) { vm.onAlertAction(AlertAction.TIP_SEEN) }

    InProfileLanguage(language) {
        val copy = AlertText.copy(result.response.messageKey, "T1")
        val reason = result.response.reasons.firstNotNullOfOrNull { reasonText(it) }
        Row(
            modifier = Modifier.fillMaxWidth().cacheCard(borderColor = CacheColors.Info.copy(alpha = 0.6f)).padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(CacheIcons.Shield, contentDescription = null, tint = CacheColors.Info, modifier = Modifier.size(22.dp))
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(stringResource(copy.body), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                if (reason != null) {
                    Text(reason, style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary)
                }
            }
        }
    }
}

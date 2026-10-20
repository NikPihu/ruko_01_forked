package com.ruko.demo.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ruko.demo.BuildConfig
import com.ruko.demo.R

/**
 * Placeholder that prints the tier and reasons (guide step 5). The T1 banner, T2 card,
 * T3 full screen and T4 review screen replace it in step 7. Never shows a score.
 */
@Composable
fun DecisionScreen(vm: PaymentViewModel, onContinue: () -> Unit, onCancel: () -> Unit) {
    Screen {
        when (val d = vm.decision) {
            is Decision.Result -> {
                Text(
                    text = stringResource(R.string.decision_tier, d.response.tier),
                    style = MaterialTheme.typography.headlineMedium,
                )
                d.response.reasons.take(3).mapNotNull { reasonText(it) }.forEach {
                    Text("• $it", style = MaterialTheme.typography.bodyLarge)
                }
                if (BuildConfig.DEBUG) {
                    Text(
                        text = "debug: ${d.millis} ms, message_key=${d.response.messageKey}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            Decision.Unavailable, null -> Text(
                text = stringResource(R.string.decision_unavailable),
                style = MaterialTheme.typography.headlineMedium,
            )
        }

        Text(
            text = stringResource(R.string.decision_placeholder),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Button(onClick = onContinue, modifier = Modifier.fillMaxWidth().height(56.dp)) {
            Text(stringResource(R.string.decision_continue))
        }
        OutlinedButton(onClick = onCancel, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.decision_cancel))
        }
    }
}

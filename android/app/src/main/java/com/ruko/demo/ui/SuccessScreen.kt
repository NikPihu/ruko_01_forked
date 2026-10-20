package com.ruko.demo.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ruko.demo.R

@Composable
fun SuccessScreen(vm: PaymentViewModel, onDone: () -> Unit) {
    Screen {
        Text(stringResource(R.string.success_title), style = MaterialTheme.typography.headlineMedium)
        Text(
            text = stringResource(R.string.pin_to, formatInr(vm.amountInr ?: 0.0), vm.upiId.trim()),
            style = MaterialTheme.typography.titleMedium,
        )
        DemoBanner()
        Text(stringResource(R.string.success_note), style = MaterialTheme.typography.bodyLarge)
        Button(onClick = onDone, modifier = Modifier.fillMaxWidth().height(56.dp)) {
            Text(stringResource(R.string.success_done))
        }
    }
}

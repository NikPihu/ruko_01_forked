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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.BuildConfig
import com.ruko.demo.R

@Composable
fun HomeScreen(vm: PaymentViewModel, onPay: () -> Unit) {
    Screen {
        // TODO(step 6): long press on this logo opens the debug panel.
        Text(
            text = "RUKO",
            style = MaterialTheme.typography.displaySmall,
            fontWeight = FontWeight.Bold,
        )
        DemoBanner()

        Button(onClick = onPay, modifier = Modifier.fillMaxWidth().height(56.dp)) {
            Text(stringResource(R.string.home_pay))
        }
        OutlinedButton(onClick = vm::checkServer, modifier = Modifier.fillMaxWidth()) {
            Text(stringResource(R.string.home_check_server))
        }
        vm.serverStatus?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
        Text(
            text = stringResource(R.string.home_api_address, BuildConfig.API_BASE_URL),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

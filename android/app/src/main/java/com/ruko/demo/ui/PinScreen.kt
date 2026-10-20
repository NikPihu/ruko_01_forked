package com.ruko.demo.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.ruko.demo.BuildConfig
import com.ruko.demo.R

/** Fake PIN pad. The PIN stays in this screen's memory only; it is never stored or sent. */
@Composable
fun PinScreen(vm: PaymentViewModel, onConfirm: () -> Unit) {
    var pin by remember { mutableStateOf("") }

    Screen {
        Text(stringResource(R.string.pin_title), style = MaterialTheme.typography.headlineMedium)
        Text(
            text = stringResource(R.string.pin_to, formatInr(vm.amountInr ?: 0.0), vm.upiId.trim()),
            style = MaterialTheme.typography.titleMedium,
        )
        Text(
            text = stringResource(R.string.pin_note),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = pin,
            onValueChange = { text -> pin = text.filter { it.isDigit() }.take(6) },
            visualTransformation = PasswordVisualTransformation(),
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = onConfirm,
            enabled = pin.length == 4 || pin.length == 6,
            modifier = Modifier.fillMaxWidth().height(56.dp),
        ) {
            Text(stringResource(R.string.pin_confirm))
        }

        // T0 shows nothing to the user, so debug builds print it here to check C1.
        if (BuildConfig.DEBUG) {
            (vm.decision as? Decision.Result)?.let {
                Text(
                    text = "debug: tier ${it.response.tier}, ${it.millis} ms",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

package com.ruko.demo.ui

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ruko.demo.R

@Composable
fun PayScreen(vm: PaymentViewModel, onBack: () -> Unit, onDecided: (Decision) -> Unit) {
    Screen {
        Text(stringResource(R.string.pay_title), style = MaterialTheme.typography.headlineMedium)

        OutlinedTextField(
            value = vm.upiId,
            onValueChange = {
                vm.upiId = it
                vm.typedManually = true
            },
            label = { Text(stringResource(R.string.pay_upi_label)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = vm.amountText,
            onValueChange = { text -> vm.amountText = text.filter { it.isDigit() || it == '.' } },
            label = { Text(stringResource(R.string.pay_amount_label)) },
            prefix = { Text("₹") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )

        Button(
            onClick = { vm.pay(onDecided) },
            enabled = vm.canPay,
            modifier = Modifier.fillMaxWidth().height(56.dp),
        ) {
            if (vm.checking) {
                CircularProgressIndicator(modifier = Modifier.size(24.dp), strokeWidth = 2.dp)
            } else {
                Text(stringResource(R.string.pay_button))
            }
        }
        TextButton(onClick = onBack) { Text(stringResource(R.string.back)) }
    }
}

package com.ruko.demo.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ruko.demo.R

@Composable
fun PayScreen(vm: PaymentViewModel, onBack: () -> Unit, onDecided: (Decision) -> Unit) {
    Screen {
        CacheTopBar(stringResource(R.string.pay_title), onBack)

        // Payee card, like a chat header in UPI apps.
        Row(
            modifier = Modifier.fillMaxWidth().cacheCard().padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            InitialAvatar(vm.upiId)
            Column {
                Text(
                    text = vm.upiId.trim().ifEmpty { stringResource(R.string.pay_upi_hint) },
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                )
                Text(
                    text = stringResource(R.string.pay_typed),
                    style = MaterialTheme.typography.bodySmall,
                    color = CacheColors.TextSecondary,
                )
            }
        }

        OutlinedTextField(
            value = vm.upiId,
            onValueChange = {
                vm.upiId = it
                vm.typedManually = true
            },
            label = { Text(stringResource(R.string.pay_upi_label)) },
            singleLine = true,
            shape = RoundedCornerShape(14.dp),
            colors = cacheFieldColors(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
            modifier = Modifier.fillMaxWidth(),
        )

        OutlinedTextField(
            value = vm.amountText,
            onValueChange = { text -> vm.amountText = text.filter { it.isDigit() || it == '.' } },
            label = { Text(stringResource(R.string.pay_amount_label)) },
            prefix = { Text("₹", style = MaterialTheme.typography.headlineMedium) },
            textStyle = MaterialTheme.typography.headlineMedium.copy(fontWeight = FontWeight.Bold),
            singleLine = true,
            shape = RoundedCornerShape(14.dp),
            colors = cacheFieldColors(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )

        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Icon(CacheIcons.Shield, contentDescription = null, tint = CacheColors.PrimaryLight, modifier = Modifier.size(20.dp))
            Text(
                text = stringResource(R.string.pay_shield_note),
                style = MaterialTheme.typography.bodyMedium,
                color = CacheColors.TextSecondary,
                textAlign = TextAlign.Start,
            )
        }

        PrimaryButton(
            text = stringResource(R.string.pay_button),
            onClick = { vm.pay(onDecided) },
            enabled = vm.canPay,
            loading = vm.checking,
        )
    }
}

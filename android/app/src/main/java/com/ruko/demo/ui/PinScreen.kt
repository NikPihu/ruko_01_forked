package com.ruko.demo.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.BuildConfig
import com.ruko.demo.R

private const val MAX_PIN = 6

/** Fake PIN pad. The PIN stays in this screen's memory only; it is never stored or sent. */
@Composable
fun PinScreen(vm: PaymentViewModel, onConfirm: () -> Unit) {
    var pin by remember { mutableStateOf("") }
    val canConfirm = pin.length == 4 || pin.length == MAX_PIN

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Column(
            modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 24.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text(
                text = stringResource(R.string.app_name),
                style = MaterialTheme.typography.titleMedium,
                color = CacheColors.PrimaryLight,
                fontWeight = FontWeight.Bold,
            )
            Text(
                text = stringResource(R.string.pin_to, formatInr(vm.amountInr ?: 0.0), vm.upiId.trim()),
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = stringResource(R.string.pin_title),
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(top = 24.dp),
            )
            PinDots(filled = pin.length)
            Text(
                text = stringResource(R.string.pin_note),
                style = MaterialTheme.typography.bodySmall,
                color = CacheColors.TextSecondary,
            )
            // T0 shows nothing to the user, so debug builds print it here to check C1.
            if (BuildConfig.DEBUG) {
                (vm.decision as? Decision.Result)?.let {
                    Text(
                        text = "debug: tier ${it.response.tier}, ${it.millis} ms",
                        style = MaterialTheme.typography.bodySmall,
                        color = CacheColors.TextSecondary,
                    )
                }
            }
        }

        Keypad(
            onDigit = { if (pin.length < MAX_PIN) pin += it },
            onDelete = { pin = pin.dropLast(1) },
            onConfirm = { if (canConfirm) onConfirm() },
            canConfirm = canConfirm,
        )
    }
}

@Composable
private fun PinDots(filled: Int) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        repeat(MAX_PIN) { index ->
            val active = index < filled
            Box(
                modifier = Modifier
                    .width(42.dp)
                    .height(50.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(CacheColors.Card)
                    .border(
                        width = 1.dp,
                        color = if (active) CacheColors.PrimaryLight else CacheColors.CardBorder,
                        shape = RoundedCornerShape(10.dp),
                    ),
                contentAlignment = Alignment.Center,
            ) {
                if (active) {
                    Box(Modifier.size(12.dp).clip(CircleShape).background(Color.White))
                }
            }
        }
    }
}

@Composable
private fun Keypad(onDigit: (Char) -> Unit, onDelete: () -> Unit, onConfirm: () -> Unit, canConfirm: Boolean) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(CacheColors.Surface)
            .navigationBarsPadding()
            .padding(8.dp),
    ) {
        listOf("123", "456", "789").forEach { row ->
            Row(Modifier.fillMaxWidth()) {
                row.forEach { digit -> DigitKey(digit, onDigit) }
            }
        }
        Row(Modifier.fillMaxWidth()) {
            Key(onClick = onDelete) {
                Icon(CacheIcons.ArrowBack, contentDescription = stringResource(R.string.pin_delete))
            }
            DigitKey('0', onDigit)
            Key(onClick = onConfirm) {
                Box(
                    modifier = Modifier
                        .size(48.dp)
                        .clip(CircleShape)
                        .background(if (canConfirm) CacheColors.Primary else CacheColors.Card),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        CacheIcons.Check,
                        contentDescription = stringResource(R.string.pin_confirm),
                        tint = if (canConfirm) Color.White else CacheColors.TextSecondary,
                    )
                }
            }
        }
    }
}

@Composable
private fun RowScope.DigitKey(digit: Char, onDigit: (Char) -> Unit) {
    Key(onClick = { onDigit(digit) }) {
        Text(digit.toString(), style = MaterialTheme.typography.headlineMedium)
    }
}

@Composable
private fun RowScope.Key(onClick: () -> Unit, content: @Composable () -> Unit) {
    Box(
        modifier = Modifier
            .weight(1f)
            .height(64.dp)
            .clip(RoundedCornerShape(12.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}

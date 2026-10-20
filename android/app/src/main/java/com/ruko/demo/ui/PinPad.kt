package com.ruko.demo.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ruko.demo.R

/** Boxes that show how many digits are entered, never the digits themselves. */
@Composable
fun PinDots(filled: Int, length: Int, error: Boolean = false) {
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        repeat(length) { index ->
            val active = index < filled
            val border = when {
                error -> CacheColors.Danger
                active -> CacheColors.PrimaryLight
                else -> CacheColors.CardBorder
            }
            Box(
                modifier = Modifier
                    .width(42.dp)
                    .height(50.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .background(CacheColors.Card)
                    .border(1.dp, border, RoundedCornerShape(10.dp)),
                contentAlignment = Alignment.Center,
            ) {
                if (active) {
                    Box(Modifier.size(12.dp).clip(CircleShape).background(Color.White))
                }
            }
        }
    }
}

/** On-screen number pad, so passcodes and PINs never go through the system keyboard. */
@Composable
fun PinPad(
    onDigit: (Char) -> Unit,
    onDelete: () -> Unit,
    onConfirm: () -> Unit,
    canConfirm: Boolean,
    enabled: Boolean = true,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(CacheColors.Surface)
            .navigationBarsPadding()
            .padding(8.dp),
    ) {
        listOf("123", "456", "789").forEach { row ->
            Row(Modifier.fillMaxWidth()) {
                row.forEach { digit -> DigitKey(digit, enabled, onDigit) }
            }
        }
        Row(Modifier.fillMaxWidth()) {
            Key(enabled = enabled, onClick = onDelete) {
                Icon(CacheIcons.ArrowBack, contentDescription = stringResource(R.string.pin_delete))
            }
            DigitKey('0', enabled, onDigit)
            Key(enabled = enabled && canConfirm, onClick = onConfirm) {
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
private fun RowScope.DigitKey(digit: Char, enabled: Boolean, onDigit: (Char) -> Unit) {
    Key(enabled = enabled, onClick = { onDigit(digit) }) {
        Text(digit.toString(), style = MaterialTheme.typography.headlineMedium)
    }
}

@Composable
private fun RowScope.Key(enabled: Boolean, onClick: () -> Unit, content: @Composable () -> Unit) {
    Box(
        modifier = Modifier
            .weight(1f)
            .height(64.dp)
            .clip(RoundedCornerShape(12.dp))
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        content()
    }
}

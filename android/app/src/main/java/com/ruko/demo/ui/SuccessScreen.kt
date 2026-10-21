package com.ruko.demo.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ruko.demo.R

@Composable
fun SuccessScreen(vm: PaymentViewModel, onDone: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(Color(0xFF0B3B24), CacheColors.Background)))
            .safeDrawingPadding()
            .padding(horizontal = 24.dp, vertical = 16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Spacer(Modifier.weight(1f))
        Box(
            modifier = Modifier.size(112.dp).clip(CircleShape).background(CacheColors.Success),
            contentAlignment = Alignment.Center,
        ) {
            Icon(CacheIcons.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(64.dp))
        }
        Text(
            text = stringResource(R.string.success_title),
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = formatInr(vm.amountInr ?: 0.0),
            style = MaterialTheme.typography.displaySmall,
            fontWeight = FontWeight.ExtraBold,
        )
        Text(
            text = vm.upiId.trim(),
            style = MaterialTheme.typography.titleMedium,
            color = CacheColors.TextSecondary,
            textAlign = TextAlign.Center,
        )
        vm.checkedPayment?.let { p ->
            SelectionContainer {
                Text(
                    text = stringResource(R.string.success_payment_id, p.id),
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                    color = CacheColors.TextSecondary,
                    textAlign = TextAlign.Center,
                )
            }
        }
        Text(
            text = stringResource(R.string.success_note),
            style = MaterialTheme.typography.bodyLarge,
            color = CacheColors.TextSecondary,
        )
        Spacer(Modifier.weight(1f))
        DemoBanner()
        PrimaryButton(stringResource(R.string.success_done), onDone, Modifier.fillMaxWidth())
    }
}

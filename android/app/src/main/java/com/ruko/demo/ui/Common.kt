package com.ruko.demo.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import java.text.NumberFormat
import java.util.Locale

@Composable
fun RukoTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(primary = Color(0xFF0B57D0)),
        content = content,
    )
}

/** Standard page: padded, scrollable, safe from system bars. */
@Composable
fun Screen(content: @Composable ColumnScope.() -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        content = content,
    )
}

@Composable
fun DemoBanner() {
    Surface(
        color = MaterialTheme.colorScheme.secondaryContainer,
        shape = MaterialTheme.shapes.medium,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Text(
            text = stringResource(R.string.demo_banner),
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.padding(16.dp),
        )
    }
}

private val inr: NumberFormat = NumberFormat.getCurrencyInstance(Locale.forLanguageTag("en-IN"))

fun formatInr(amount: Double): String = inr.format(amount)

/** Plain words for a reason code (contract table). Unknown codes are skipped, never shown raw. */
@Composable
fun reasonText(code: String): String? = when (code) {
    "R1_live_unknown_call" -> stringResource(R.string.reason_R1_live_unknown_call)
    "R2_remote_control" -> stringResource(R.string.reason_R2_remote_control)
    "R3_mule_like_payee" -> stringResource(R.string.reason_R3_mule_like_payee)
    "R4_unusual_amount" -> stringResource(R.string.reason_R4_unusual_amount)
    "R5_lure_message" -> stringResource(R.string.reason_R5_lure_message)
    "R6_new_payee_typed" -> stringResource(R.string.reason_R6_new_payee_typed)
    "R7_tranche_pattern" -> stringResource(R.string.reason_R7_tranche_pattern)
    "R8_intel_hit" -> stringResource(R.string.reason_R8_intel_hit)
    else -> null
}

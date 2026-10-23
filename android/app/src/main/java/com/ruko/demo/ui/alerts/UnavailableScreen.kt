package com.ruko.demo.ui.alerts

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.CacheIcons
import com.ruko.demo.ui.CacheTopBar
import com.ruko.demo.ui.PrimaryButton
import com.ruko.demo.ui.Screen
import com.ruko.demo.ui.SecondaryButton
import com.ruko.demo.ui.cacheCard

/** Fail open (rule 3): Scam Shield could not answer, so the payment goes ahead after a short note. */
@Composable
fun UnavailableScreen(onContinue: () -> Unit, onCancel: () -> Unit) {
    Screen {
        CacheTopBar(stringResource(R.string.decision_title))
        Column(
            modifier = Modifier.fillMaxWidth().cacheCard().padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            AlertHeader(
                CacheIcons.Shield,
                CacheColors.TextSecondary,
                stringResource(R.string.decision_unavailable),
                stringResource(R.string.decision_unavailable_body),
            )
        }
        PrimaryButton(stringResource(R.string.decision_continue), onContinue)
        SecondaryButton(stringResource(R.string.decision_cancel), onCancel)
    }
}

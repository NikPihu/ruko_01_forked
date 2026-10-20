package com.ruko.demo.ui.auth

import android.os.SystemClock
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
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
import com.ruko.demo.R
import com.ruko.demo.data.Masks
import com.ruko.demo.data.Passcode
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.PinDots
import com.ruko.demo.ui.PinPad
import kotlinx.coroutines.delay

@Composable
fun LoginScreen(vm: AuthViewModel) {
    val profile = vm.profile ?: return
    var code by remember { mutableStateOf("") }
    var askReset by remember { mutableStateOf(false) }

    // Ticks once a second while locked out, so the countdown and the keypad update.
    var now by remember { mutableLongStateOf(SystemClock.elapsedRealtime()) }
    LaunchedEffect(vm.lockedUntil) {
        while (SystemClock.elapsedRealtime() < vm.lockedUntil) {
            now = SystemClock.elapsedRealtime()
            delay(1_000)
        }
        now = SystemClock.elapsedRealtime()
    }
    val lockedOut = now < vm.lockedUntil
    val submit = {
        val entered = code
        code = ""
        vm.unlock(entered)
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        Column(
            modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 24.dp, vertical = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Box(
                modifier = Modifier.size(72.dp).clip(CircleShape).background(CacheColors.Primary),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    text = profile.firstName.take(1).uppercase(),
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold,
                    color = Color.White,
                )
            }
            Text(
                text = stringResource(R.string.login_title, profile.firstName),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
            )
            Text(Masks.mobile(profile.mobile), style = MaterialTheme.typography.bodyLarge, color = CacheColors.TextSecondary)
            Text(stringResource(R.string.login_body), style = MaterialTheme.typography.bodyLarge, color = CacheColors.TextSecondary)
            PinDots(filled = code.length, length = Passcode.LENGTH, error = vm.error != null && code.isEmpty())
            if (lockedOut) {
                val seconds = ((vm.lockedUntil - now + 999) / 1_000).toInt()
                Text(stringResource(R.string.login_locked_out, seconds), color = CacheColors.Danger)
            } else {
                ErrorLine(vm.error)
            }
            TextButton(onClick = { askReset = true }) {
                Text(stringResource(R.string.login_forgot), color = CacheColors.PrimaryLight)
            }
        }
        PinPad(
            onDigit = {
                if (code.length < Passcode.LENGTH) {
                    vm.clearError()
                    code += it
                    if (code.length == Passcode.LENGTH) submit()
                }
            },
            onDelete = { code = code.dropLast(1) },
            onConfirm = submit,
            canConfirm = code.length == Passcode.LENGTH,
            enabled = !lockedOut && !vm.busy,
        )
    }

    if (askReset) {
        ConfirmDeleteDialog(
            title = R.string.reset_title,
            body = R.string.reset_body,
            confirm = R.string.reset_confirm,
            onConfirm = {
                askReset = false
                vm.deleteAccount()
            },
            onDismiss = { askReset = false },
        )
    }
}

@Composable
fun ConfirmDeleteDialog(title: Int, body: Int, confirm: Int, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = CacheColors.Card,
        title = { Text(stringResource(title)) },
        text = { Text(stringResource(body), color = CacheColors.TextSecondary) },
        confirmButton = {
            TextButton(onClick = onConfirm) { Text(stringResource(confirm), color = CacheColors.Danger) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) }
        },
    )
}

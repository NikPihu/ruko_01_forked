package com.ruko.demo.ui

import android.Manifest.permission.READ_CONTACTS
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.signals.SavedContact
import com.ruko.demo.signals.Signals
import com.ruko.demo.signals.toE164

/**
 * "To Mobile Number": pick a saved contact or type a number. The number is turned into the UPI ID
 * linked to it (UPI number mapper), then the usual Pay screen and Scam Shield check follow.
 * Contacts are read on the phone only; the server hears just "the payee is a saved contact" (c2-0.7).
 */
@Composable
fun ContactsScreen(vm: PaymentViewModel, onBack: () -> Unit, onReady: () -> Unit) {
    var query by remember { mutableStateOf("") }
    var reload by remember { mutableIntStateOf(0) }
    val book = remember(reload) { Signals.contacts.all() }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { reload++ }

    Screen {
        CacheTopBar(stringResource(R.string.contacts_title), onBack)
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text(stringResource(R.string.contacts_search)) },
            singleLine = true,
            shape = RoundedCornerShape(14.dp),
            colors = cacheFieldColors(),
            keyboardOptions = KeyboardOptions(),
            modifier = Modifier.fillMaxWidth(),
        )

        if (vm.resolving) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                CircularProgressIndicator(color = CacheColors.Primary, modifier = Modifier.padding(4.dp))
                Text(stringResource(R.string.contacts_finding), color = CacheColors.TextSecondary)
            }
        }
        vm.resolveError?.let { e ->
            Text(
                stringResource(
                    when (e) {
                        ResolveError.BAD_NUMBER -> R.string.contacts_bad_number
                        ResolveError.NOT_LINKED -> R.string.contacts_not_linked
                        ResolveError.UNREACHABLE -> R.string.contacts_unreachable
                    },
                ),
                color = CacheColors.Danger,
            )
        }

        // A number typed in full: pay it even if it is not saved.
        val typed = query.filter(Char::isDigit).takeIf { it.length >= 10 }?.let(::toE164)
        if (typed != null && book?.none { it.mobile == typed } != false) {
            ContactRow(SavedContact(stringResource(R.string.contacts_pay_number, typed), typed), saved = false) {
                if (!vm.resolving) vm.payMobile(null, typed, picked = false, onReady)
            }
        }

        if (book == null) {
            Column(
                Modifier.fillMaxWidth().cacheCard().padding(18.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                Text(stringResource(R.string.contacts_permission), style = MaterialTheme.typography.bodyLarge)
                PrimaryButton(stringResource(R.string.perm_allow), onClick = { ask.launch(READ_CONTACTS) })
            }
            return@Screen
        }

        val q = query.trim().lowercase()
        val digits = q.filter(Char::isDigit)
        val shown = book.filter { q.isEmpty() || q in it.name.lowercase() || (digits.isNotEmpty() && digits in it.mobile) }
        if (shown.isEmpty()) Text(stringResource(R.string.contacts_none), color = CacheColors.TextSecondary)
        shown.forEach { c ->
            ContactRow(c, saved = true) { if (!vm.resolving) vm.payMobile(c.name, c.mobile, picked = true, onReady) }
        }
    }
}

@Composable
private fun ContactRow(c: SavedContact, saved: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().cacheCard().clickable(onClick = onClick).padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        InitialAvatar(c.name)
        Column(Modifier.weight(1f)) {
            Text(c.name, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                if (saved) c.mobile else stringResource(R.string.contacts_not_saved),
                style = MaterialTheme.typography.bodySmall,
                color = CacheColors.TextSecondary,
            )
        }
    }
}

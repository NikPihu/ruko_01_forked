package com.ruko.demo.ui.auth

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.cacheFieldColors

@Composable
fun errorText(error: AuthError): String = stringResource(
    when (error) {
        AuthError.MOBILE -> R.string.err_mobile
        AuthError.OTP -> R.string.err_otp
        AuthError.NAME -> R.string.err_name
        AuthError.EMAIL -> R.string.err_email
        AuthError.DOB -> R.string.err_dob
        AuthError.AGE -> R.string.err_age
        AuthError.BANK -> R.string.err_bank
        AuthError.ACCOUNT -> R.string.err_account
        AuthError.IFSC -> R.string.err_ifsc
        AuthError.UPI -> R.string.err_upi
        AuthError.PAN -> R.string.err_pan
        AuthError.TRUSTED_NAME -> R.string.err_trusted_name
        AuthError.TRUSTED_MOBILE -> R.string.err_trusted_mobile
        AuthError.TRUSTED_SELF -> R.string.err_trusted_self
        AuthError.AGREE -> R.string.err_agree
        AuthError.WEAK_PASSCODE -> R.string.err_weak_passcode
        AuthError.PASSCODE_MISMATCH -> R.string.err_passcode_mismatch
        AuthError.WRONG_PASSCODE -> R.string.err_wrong_passcode
        AuthError.LOCKED_OUT -> R.string.err_wrong_passcode
    }
)

@Composable
fun ErrorLine(error: AuthError?) {
    if (error != null) {
        Text(errorText(error), color = CacheColors.Danger, style = MaterialTheme.typography.bodyMedium)
    }
}

/**
 * Text field that only accepts [allowed] characters, up to [maxLength]. [upper] turns letters
 * to capitals as they are typed (IFSC, PAN).
 */
@Composable
fun CacheField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier.fillMaxWidth(),
    keyboardType: KeyboardType = KeyboardType.Text,
    maxLength: Int = 60,
    allowed: (Char) -> Boolean = { true },
    upper: Boolean = false,
    lower: Boolean = false,
    capitalizeWords: Boolean = false,
    prefix: String? = null,
    suffix: String? = null,
) {
    OutlinedTextField(
        value = value,
        onValueChange = { raw ->
            val cased = when {
                upper -> raw.uppercase()
                lower -> raw.lowercase()
                else -> raw
            }
            onValueChange(cased.filter(allowed).take(maxLength))
        },
        label = { Text(label) },
        singleLine = true,
        shape = RoundedCornerShape(14.dp),
        colors = cacheFieldColors(),
        prefix = prefix?.let { { Text(it) } },
        suffix = suffix?.let { { Text(it, color = CacheColors.TextSecondary) } },
        keyboardOptions = KeyboardOptions(
            keyboardType = keyboardType,
            capitalization = when {
                upper -> KeyboardCapitalization.Characters
                capitalizeWords -> KeyboardCapitalization.Words
                else -> KeyboardCapitalization.None
            },
            autoCorrectEnabled = false,
        ),
        modifier = modifier,
    )
}

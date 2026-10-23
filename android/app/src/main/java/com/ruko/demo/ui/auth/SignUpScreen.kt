package com.ruko.demo.ui.auth

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.data.Passcode
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.CacheIcons
import com.ruko.demo.ui.PinDots
import com.ruko.demo.ui.PinPad
import com.ruko.demo.ui.PrimaryButton
import com.ruko.demo.ui.cacheCard

private val BANKS = listOf(
    "State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak Mahindra Bank",
    "Punjab National Bank", "Bank of Baroda", "Canara Bank", "Union Bank of India", "Other bank",
)

@Composable
fun SignUpFlow(vm: AuthViewModel) {
    BackHandler(enabled = vm.step != SignUpStep.WELCOME) { vm.back() }
    when (vm.step) {
        SignUpStep.WELCOME -> WelcomeScreen(vm::startSignUp)
        SignUpStep.PASSCODE -> PasscodeStep(vm)
        else -> FormStep(vm)
    }
}

@Composable
private fun WelcomeScreen(onCreate: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Brush.verticalGradient(listOf(CacheColors.HeroTop, CacheColors.HeroBottom, CacheColors.Background)))
            .safeDrawingPadding()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        Spacer(Modifier.weight(1f))
        Box(
            modifier = Modifier.size(104.dp).clip(CircleShape).background(Color.White),
            contentAlignment = Alignment.Center,
        ) {
            Icon(CacheIcons.Shield, contentDescription = null, tint = CacheColors.Primary, modifier = Modifier.size(60.dp))
        }
        Text(
            text = stringResource(R.string.welcome_title),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.ExtraBold,
            color = Color.White,
            textAlign = TextAlign.Center,
        )
        Text(
            text = stringResource(R.string.welcome_body),
            style = MaterialTheme.typography.bodyLarge,
            color = Color.White.copy(alpha = 0.85f),
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.weight(1f))
        Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Icon(CacheIcons.Shield, contentDescription = null, tint = CacheColors.PrimaryLight, modifier = Modifier.size(18.dp))
            Text(stringResource(R.string.welcome_privacy), style = MaterialTheme.typography.bodyMedium, color = CacheColors.TextSecondary)
        }
        PrimaryButton(stringResource(R.string.welcome_create), onCreate)
    }
}

/** Steps 1 to 5: a header with progress, the step's fields, the error and a Next button. */
@Composable
private fun FormStep(vm: AuthViewModel) {
    Column(
        Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .navigationBarsPadding()
            .imePadding(),
    ) {
        StepHeader(vm.step, onBack = vm::back)
        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            when (vm.step) {
                SignUpStep.MOBILE -> MobileStep(vm)
                SignUpStep.PERSONAL -> PersonalStep(vm)
                SignUpStep.BANK -> BankStep(vm)
                SignUpStep.KYC -> KycStep(vm)
                SignUpStep.PRIVACY -> PrivacyStep(vm)
                else -> Unit
            }
            ErrorLine(vm.error)
        }
        Box(Modifier.padding(20.dp)) {
            when (vm.step) {
                SignUpStep.MOBILE -> if (vm.otpSent == null) {
                    PrimaryButton(stringResource(R.string.mobile_send_otp), vm::sendOtp, enabled = vm.mobile.length == 10)
                } else {
                    PrimaryButton(stringResource(R.string.otp_verify), vm::verifyOtp, enabled = vm.otpInput.length == 6)
                }
                SignUpStep.PERSONAL -> PrimaryButton(stringResource(R.string.next), vm::submitPersonal)
                SignUpStep.BANK -> PrimaryButton(stringResource(R.string.next), vm::submitBank)
                SignUpStep.KYC -> PrimaryButton(stringResource(R.string.next), vm::submitKyc)
                SignUpStep.PRIVACY -> PrimaryButton(stringResource(R.string.next), vm::submitPrivacy)
                else -> Unit
            }
        }
    }
}

@Composable
private fun StepHeader(step: SignUpStep, onBack: () -> Unit) {
    val total = SignUpStep.entries.size - 1
    Column(Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(CacheIcons.ArrowBack, contentDescription = stringResource(R.string.back))
            }
            Text(
                text = stringResource(R.string.signup_step, step.ordinal, total),
                style = MaterialTheme.typography.titleSmall,
                color = CacheColors.TextSecondary,
            )
        }
        LinearProgressIndicator(
            progress = { step.ordinal / total.toFloat() },
            color = CacheColors.Primary,
            trackColor = CacheColors.Card,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp).clip(RoundedCornerShape(50)),
        )
    }
}

@Composable
private fun ColumnScope.Title(title: Int, body: Int) {
    Text(stringResource(title), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
    Text(stringResource(body), style = MaterialTheme.typography.bodyLarge, color = CacheColors.TextSecondary)
}

@Composable
private fun ColumnScope.MobileStep(vm: AuthViewModel) {
    Title(R.string.mobile_title, R.string.mobile_body)
    CacheField(
        value = vm.mobile,
        onValueChange = { vm.mobile = it },
        label = stringResource(R.string.mobile_label),
        keyboardType = KeyboardType.Phone,
        maxLength = 10,
        allowed = Char::isDigit,
        prefix = "+91 ",
    )
    val sent = vm.otpSent ?: return
    CacheField(
        value = vm.otpInput,
        onValueChange = { vm.otpInput = it },
        label = stringResource(R.string.otp_label),
        keyboardType = KeyboardType.NumberPassword,
        maxLength = 6,
        allowed = Char::isDigit,
    )
    Text(stringResource(R.string.otp_demo, sent), style = MaterialTheme.typography.bodyMedium, color = CacheColors.Warning)
    TextButton(onClick = vm::sendOtp) { Text(stringResource(R.string.otp_resend), color = CacheColors.PrimaryLight) }
}

@Composable
private fun ColumnScope.PersonalStep(vm: AuthViewModel) {
    Title(R.string.personal_title, R.string.personal_body)
    CacheField(
        value = vm.fullName,
        onValueChange = { vm.fullName = it },
        label = stringResource(R.string.name_label),
        capitalizeWords = true,
        allowed = { it.isLetter() || it == ' ' || it == '.' || it == '\'' },
    )
    CacheField(
        value = vm.email,
        onValueChange = { vm.email = it },
        label = stringResource(R.string.email_label),
        keyboardType = KeyboardType.Email,
        maxLength = 80,
        allowed = { !it.isWhitespace() },
    )
    Text(stringResource(R.string.dob_label), style = MaterialTheme.typography.titleSmall, color = CacheColors.TextSecondary)
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        CacheField(vm.dobDay, { vm.dobDay = it }, stringResource(R.string.dob_day), Modifier.weight(1f), KeyboardType.Number, 2, Char::isDigit)
        CacheField(vm.dobMonth, { vm.dobMonth = it }, stringResource(R.string.dob_month), Modifier.weight(1f), KeyboardType.Number, 2, Char::isDigit)
        CacheField(vm.dobYear, { vm.dobYear = it }, stringResource(R.string.dob_year), Modifier.weight(1.4f), KeyboardType.Number, 4, Char::isDigit)
    }
    Text(stringResource(R.string.language_label), style = MaterialTheme.typography.titleSmall, color = CacheColors.TextSecondary)
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        ChoiceChip(stringResource(R.string.language_en), vm.language == "en", Modifier.weight(1f)) { vm.language = "en" }
        ChoiceChip(stringResource(R.string.language_hi), vm.language == "hi", Modifier.weight(1f)) { vm.language = "hi" }
    }
}

@Composable
private fun ColumnScope.BankStep(vm: AuthViewModel) {
    Title(R.string.bank_title, R.string.bank_body)
    var open by remember { mutableStateOf(false) }
    Box {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(58.dp)
                .cacheCard(radius = 14.dp)
                .clickable { open = true }
                .padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Icon(CacheIcons.Bank, contentDescription = null, tint = CacheColors.PrimaryLight)
            Text(
                text = vm.bankName.ifEmpty { stringResource(R.string.bank_label) },
                color = if (vm.bankName.isEmpty()) CacheColors.TextSecondary else CacheColors.TextPrimary,
                style = MaterialTheme.typography.bodyLarge,
            )
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            BANKS.forEach { bank ->
                DropdownMenuItem(text = { Text(bank) }, onClick = {
                    vm.bankName = bank
                    open = false
                })
            }
        }
    }
    CacheField(
        value = vm.accountLast4,
        onValueChange = { vm.accountLast4 = it },
        label = stringResource(R.string.account_last4_label),
        keyboardType = KeyboardType.NumberPassword,
        maxLength = 4,
        allowed = Char::isDigit,
        prefix = "•••• ",
    )
    CacheField(
        value = vm.ifsc,
        onValueChange = { vm.ifsc = it },
        label = stringResource(R.string.ifsc_label),
        maxLength = 11,
        upper = true,
        allowed = Char::isLetterOrDigit,
    )
    CacheField(
        value = vm.upiHandle,
        onValueChange = { vm.upiHandle = it },
        label = stringResource(R.string.upi_handle_label),
        keyboardType = KeyboardType.Email,
        maxLength = 40,
        lower = true,
        allowed = { it.isLetterOrDigit() || it in "._-" },
        suffix = "@cachepay",
    )
}

@Composable
private fun ColumnScope.KycStep(vm: AuthViewModel) {
    Title(R.string.kyc_title, R.string.kyc_body)
    CacheField(
        value = vm.pan,
        onValueChange = { vm.pan = it },
        label = stringResource(R.string.pan_label) + " (" + stringResource(R.string.optional) + ")",
        maxLength = 10,
        upper = true,
        allowed = Char::isLetterOrDigit,
    )
    CacheField(
        value = vm.trustedName,
        onValueChange = { vm.trustedName = it },
        label = stringResource(R.string.trusted_name_label),
        capitalizeWords = true,
        allowed = { it.isLetter() || it == ' ' || it == '.' || it == '\'' },
    )
    CacheField(
        value = vm.trustedMobile,
        onValueChange = { vm.trustedMobile = it },
        label = stringResource(R.string.trusted_mobile_label),
        keyboardType = KeyboardType.Phone,
        maxLength = 10,
        allowed = Char::isDigit,
        prefix = "+91 ",
    )
}

@Composable
private fun ColumnScope.PrivacyStep(vm: AuthViewModel) {
    Title(R.string.privacy_title, R.string.privacy_body)
    val c = vm.draftConsents
    ConsentRow(R.string.consent_calls, R.string.consent_calls_desc, c.callSignals) { vm.draftConsents = c.copy(callSignals = it) }
    ConsentRow(R.string.consent_apps, R.string.consent_apps_desc, c.appChecks) { vm.draftConsents = c.copy(appChecks = it) }
    ConsentRow(R.string.consent_session, R.string.consent_session_desc, c.sessionSignals) { vm.draftConsents = c.copy(sessionSignals = it) }
    ConsentRow(R.string.consent_sms, R.string.consent_sms_desc, c.smsLure) {
        vm.draftConsents = c.copy(smsLure = it, moneyWatch = c.moneyWatch && it, shareAccounts = c.shareAccounts && it)
    }
    ConsentRow(R.string.consent_watch, R.string.consent_watch_desc, c.moneyWatch) {
        vm.draftConsents = c.copy(moneyWatch = it, smsLure = c.smsLure || it, shareAccounts = c.shareAccounts && it)
    }
    if (c.moneyWatch) {
        ConsentRow(R.string.consent_share, R.string.consent_share_desc, c.shareAccounts) { vm.draftConsents = c.copy(shareAccounts = it) }
    }
    // Notification access is granted later, from the profile (it needs Android's Settings screen).
    ConsentRow(R.string.consent_chat, R.string.consent_chat_desc, c.chatLure) { vm.draftConsents = c.copy(chatLure = it) }
    ConsentRow(R.string.consent_early, R.string.consent_early_desc, c.earlyWarnings) { vm.draftConsents = c.copy(earlyWarnings = it) }
    Text(
        text = stringResource(R.string.privacy_points),
        style = MaterialTheme.typography.bodyMedium,
        color = CacheColors.TextSecondary,
        modifier = Modifier.fillMaxWidth().cacheCard().padding(16.dp),
    )
    Row(
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .clickable { vm.draftConsents = c.copy(storageAgreed = !c.storageAgreed) },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(
            checked = c.storageAgreed,
            onCheckedChange = { vm.draftConsents = c.copy(storageAgreed = it) },
            colors = CheckboxDefaults.colors(checkedColor = CacheColors.Primary),
        )
        Text(stringResource(R.string.privacy_agree), style = MaterialTheme.typography.bodyLarge)
    }
}

/** A labelled switch, also used on the profile screen. */
@Composable
fun ConsentRow(title: Int, description: Int, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().cacheCard().clickable { onChange(!checked) }.padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(title), style = MaterialTheme.typography.titleMedium)
            Text(stringResource(description), style = MaterialTheme.typography.bodySmall, color = CacheColors.TextSecondary)
        }
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(checkedTrackColor = CacheColors.Primary),
        )
    }
}

@Composable
private fun ChoiceChip(label: String, selected: Boolean, modifier: Modifier, onClick: () -> Unit) {
    Box(
        modifier = modifier
            .height(52.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(if (selected) CacheColors.Primary.copy(alpha = 0.25f) else CacheColors.Card)
            .border(1.dp, if (selected) CacheColors.PrimaryLight else CacheColors.CardBorder, RoundedCornerShape(14.dp))
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, style = MaterialTheme.typography.titleMedium)
    }
}

/** Step 6: set the passcode, then type it again. The account is saved on the second entry. */
@Composable
private fun PasscodeStep(vm: AuthViewModel) {
    var code by remember(vm.passcodeFirst) { mutableStateOf("") }
    val confirming = vm.passcodeFirst != null
    val submit = {
        val entered = code
        code = ""
        vm.submitNewPasscode(entered)
    }

    Column(Modifier.fillMaxSize().statusBarsPadding()) {
        StepHeader(SignUpStep.PASSCODE, onBack = vm::back)
        Column(
            modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 24.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text(
                text = stringResource(if (confirming) R.string.passcode_confirm_title else R.string.passcode_set_title),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.Bold,
            )
            Text(stringResource(R.string.passcode_set_body), style = MaterialTheme.typography.bodyLarge, color = CacheColors.TextSecondary)
            PinDots(filled = code.length, length = Passcode.LENGTH, error = vm.error != null && code.isEmpty())
            ErrorLine(vm.error)
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
            enabled = !vm.busy,
        )
    }
}

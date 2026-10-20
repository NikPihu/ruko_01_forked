package com.ruko.demo.ui.auth

import android.app.Application
import android.os.SystemClock
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.ruko.demo.data.AccountStore
import com.ruko.demo.data.Consents
import com.ruko.demo.data.Passcode
import com.ruko.demo.data.UserProfile
import com.ruko.demo.data.Validators
import com.ruko.demo.shield.ShieldController
import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.util.UUID

sealed interface AuthState {
    data object Loading : AuthState
    data object NeedsSignUp : AuthState
    data object Locked : AuthState
    data object Unlocked : AuthState
}

enum class SignUpStep { WELCOME, MOBILE, PERSONAL, BANK, KYC, PRIVACY, PASSCODE }

/** Sign up, login and the lock. All account data stays in [AccountStore], on this phone. */
class AuthViewModel(app: Application) : AndroidViewModel(app) {

    private val store = AccountStore(app)

    var state by mutableStateOf<AuthState>(AuthState.Loading)
        private set
    var profile by mutableStateOf<UserProfile?>(null)
        private set
    var consents by mutableStateOf(Consents())
        private set
    var recentPayees by mutableStateOf<List<String>>(emptyList())
        private set
    var payments by mutableStateOf<List<MoneyTxn>>(emptyList())
        private set

    // ---- Sign up draft. Kept in memory only until the passcode step saves it. ----
    var step by mutableStateOf(SignUpStep.WELCOME)
        private set
    var mobile by mutableStateOf("")
    var otpInput by mutableStateOf("")
    var otpSent by mutableStateOf<String?>(null)
        private set
    var fullName by mutableStateOf("")
    var email by mutableStateOf("")
    var dobDay by mutableStateOf("")
    var dobMonth by mutableStateOf("")
    var dobYear by mutableStateOf("")
    var language by mutableStateOf("en")
    var bankName by mutableStateOf("")
    var accountLast4 by mutableStateOf("")
    var ifsc by mutableStateOf("")
    var upiHandle by mutableStateOf("")
    var pan by mutableStateOf("")
    var trustedName by mutableStateOf("")
    var trustedMobile by mutableStateOf("")
    var draftConsents by mutableStateOf(Consents())
    var passcodeFirst by mutableStateOf<String?>(null)
        private set
    var busy by mutableStateOf(false)
        private set

    /** Message key for the current screen's error, or null. */
    var error by mutableStateOf<AuthError?>(null)
        private set

    // ---- Login lockout, in memory ----
    private var failedAttempts by mutableIntStateOf(0)
    var lockedUntil by mutableLongStateOf(0L)
        private set
    private var backgroundAt = 0L

    init {
        viewModelScope.launch {
            val (p, c) = withContext(Dispatchers.IO) { store.loadProfile() to store.loadConsents() }
            profile = p
            consents = c
            withContext(Dispatchers.IO) { ShieldController.ensureRunning(getApplication(), c) }
            if (p != null) {
                recentPayees = withContext(Dispatchers.IO) { store.loadRecentPayees() }
                payments = withContext(Dispatchers.IO) { store.loadPayments() }
            }
            state = if (p == null) AuthState.NeedsSignUp else AuthState.Locked
        }
    }

    // ---------------- Sign up ----------------

    fun startSignUp() = goTo(SignUpStep.MOBILE)

    fun sendOtp() {
        if (!Validators.isMobile(mobile)) return fail(AuthError.MOBILE)
        // Demo only: no SMS gateway, so the code is shown on screen.
        otpSent = Passcode.newOtp()
        otpInput = ""
        error = null
    }

    fun verifyOtp() {
        if (otpInput != otpSent) return fail(AuthError.OTP)
        if (upiHandle.isEmpty()) upiHandle = mobile
        goTo(SignUpStep.PERSONAL)
    }

    fun submitPersonal() {
        val dob = Validators.dateOfBirth(dobDay, dobMonth, dobYear)
        when {
            !Validators.isName(fullName) -> fail(AuthError.NAME)
            !Validators.isEmail(email) -> fail(AuthError.EMAIL)
            dob == null -> fail(AuthError.DOB)
            !Validators.isAdult(dob) -> fail(AuthError.AGE)
            else -> goTo(SignUpStep.BANK)
        }
    }

    fun submitBank() {
        when {
            bankName.isBlank() -> fail(AuthError.BANK)
            !Validators.isLast4(accountLast4) -> fail(AuthError.ACCOUNT)
            !Validators.isIfsc(ifsc) -> fail(AuthError.IFSC)
            !Validators.isUpiHandle(upiHandle) -> fail(AuthError.UPI)
            else -> goTo(SignUpStep.KYC)
        }
    }

    fun submitKyc() {
        val hasTrusted = trustedName.isNotBlank() || trustedMobile.isNotBlank()
        when {
            pan.isNotEmpty() && !Validators.isPan(pan) -> fail(AuthError.PAN)
            hasTrusted && !Validators.isName(trustedName) -> fail(AuthError.TRUSTED_NAME)
            hasTrusted && !Validators.isMobile(trustedMobile) -> fail(AuthError.TRUSTED_MOBILE)
            hasTrusted && trustedMobile == mobile -> fail(AuthError.TRUSTED_SELF)
            else -> goTo(SignUpStep.PRIVACY)
        }
    }

    fun submitPrivacy() {
        if (!draftConsents.storageAgreed) return fail(AuthError.AGREE)
        goTo(SignUpStep.PASSCODE)
    }

    /** First entry sets the passcode, the second confirms it and creates the account. */
    fun submitNewPasscode(code: String) {
        val first = passcodeFirst
        when {
            first == null && isWeak(code) -> fail(AuthError.WEAK_PASSCODE)
            first == null -> {
                passcodeFirst = code
                error = null
            }
            first != code -> {
                passcodeFirst = null
                fail(AuthError.PASSCODE_MISMATCH)
            }
            else -> createAccount(code)
        }
    }

    fun back() {
        error = null
        if (step == SignUpStep.PASSCODE && passcodeFirst != null) {
            passcodeFirst = null
            return
        }
        step = SignUpStep.entries.getOrElse(step.ordinal - 1) { SignUpStep.WELCOME }
    }

    private fun createAccount(code: String) {
        val salt = Passcode.newSalt()
        val now = OffsetDateTime.now(ZoneOffset.ofHoursMinutes(5, 30)).withNano(0).toString()
        val dob = Validators.dateOfBirth(dobDay, dobMonth, dobYear)!!
        val newProfile = UserProfile(
            localId = "u_" + UUID.randomUUID().toString().replace("-", "").take(12),
            fullName = fullName.trim(),
            mobile = mobile,
            email = email.trim().lowercase(),
            dateOfBirth = dob.toString(),
            language = language,
            bankName = bankName,
            accountLast4 = accountLast4,
            ifsc = ifsc,
            upiId = "$upiHandle@cachepay",
            pan = pan.ifEmpty { null },
            trustedName = trustedName.trim().ifEmpty { null },
            trustedMobile = trustedMobile.ifEmpty { null },
            passcodeSalt = salt,
            passcodeHash = Passcode.hash(code, salt),
            createdAt = now,
        )
        val agreed = draftConsents.copy(agreedAt = now)
        busy = true
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                store.saveProfile(newProfile)
                store.saveConsents(agreed)
            }
            profile = newProfile
            consents = agreed
            clearDraft()
            busy = false
            state = AuthState.Unlocked
        }
    }

    private fun clearDraft() {
        mobile = ""; otpInput = ""; otpSent = null; fullName = ""; email = ""
        dobDay = ""; dobMonth = ""; dobYear = ""; language = "en"; bankName = ""
        accountLast4 = ""; ifsc = ""; upiHandle = ""; pan = ""; trustedName = ""
        trustedMobile = ""; draftConsents = Consents(); passcodeFirst = null
        step = SignUpStep.WELCOME; error = null
    }

    // ---------------- Login and lock ----------------

    fun isLockedOut(now: Long = SystemClock.elapsedRealtime()) = now < lockedUntil

    fun unlock(code: String) {
        val p = profile ?: return
        if (isLockedOut()) return fail(AuthError.LOCKED_OUT)
        busy = true
        viewModelScope.launch {
            val ok = withContext(Dispatchers.Default) { Passcode.matches(code, p.passcodeSalt, p.passcodeHash) }
            busy = false
            if (ok) {
                failedAttempts = 0
                error = null
                state = AuthState.Unlocked
            } else {
                failedAttempts++
                if (failedAttempts % MAX_ATTEMPTS == 0) {
                    // 30 s after five wrong tries, doubling each time after that.
                    val rounds = failedAttempts / MAX_ATTEMPTS
                    lockedUntil = SystemClock.elapsedRealtime() + LOCKOUT_MS * (1L shl (rounds - 1).coerceAtMost(5))
                    fail(AuthError.LOCKED_OUT)
                } else {
                    fail(AuthError.WRONG_PASSCODE)
                }
            }
        }
    }

    fun lock() {
        if (profile != null) state = AuthState.Locked
    }

    fun onBackground() {
        backgroundAt = SystemClock.elapsedRealtime()
    }

    /** Lock again if the app was away for longer than [AUTO_LOCK_MS]. */
    fun onForeground() {
        if (state == AuthState.Unlocked && backgroundAt > 0 &&
            SystemClock.elapsedRealtime() - backgroundAt > AUTO_LOCK_MS
        ) {
            lock()
        }
        backgroundAt = 0
    }

    fun updateConsents(new: Consents) {
        val old = consents
        consents = new
        viewModelScope.launch(Dispatchers.IO) {
            store.saveConsents(new)
            // The background watcher follows its switch; off also deletes the money history.
            if (new.moneyWatch && !old.moneyWatch) ShieldController.enable(getApplication())
            if (!new.moneyWatch && old.moneyWatch) ShieldController.disable(getApplication())
        }
    }

    /** Remember a paid UPI ID (newest first, at most five), encrypted with the rest. */
    fun rememberPayee(upiId: String) {
        val id = upiId.trim().lowercase()
        if (id.isEmpty()) return
        val updated = (listOf(id) + recentPayees.filter { it != id }).take(MAX_RECENT_PAYEES)
        recentPayees = updated
        viewModelScope.launch(Dispatchers.IO) { store.saveRecentPayees(updated) }
    }

    /** Keep a completed payment for the money flow: 30 days, at most 200, encrypted. */
    fun rememberPayment(upiId: String, amountInr: Double?) {
        val id = upiId.trim().lowercase()
        if (id.isEmpty() || amountInr == null) return
        val now = System.currentTimeMillis()
        val updated = (payments + MoneyTxn(now, amountInr, Flow.OUT, id))
            .filter { now - it.ts <= PAYMENT_HISTORY_MS }
            .takeLast(MAX_PAYMENTS)
        payments = updated
        viewModelScope.launch(Dispatchers.IO) {
            store.savePayments(updated)
            ShieldController.recordAppPayment(getApplication(), id, amountInr)
        }
    }

    /** Delete the account and every stored detail, then start again from sign up. */
    fun deleteAccount() {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { store.deleteAll() }
            profile = null
            consents = Consents()
            recentPayees = emptyList()
            payments = emptyList()
            failedAttempts = 0
            lockedUntil = 0
            clearDraft()
            state = AuthState.NeedsSignUp
        }
    }

    fun clearError() {
        error = null
    }

    private fun goTo(next: SignUpStep) {
        error = null
        step = next
    }

    private fun fail(e: AuthError) {
        error = e
    }

    private fun isWeak(code: String): Boolean =
        code.toSet().size == 1 || code in WEAK_CODES || code == mobile.takeLast(Passcode.LENGTH)

    companion object {
        const val MAX_ATTEMPTS = 5
        const val LOCKOUT_MS = 30_000L
        const val AUTO_LOCK_MS = 60_000L
        const val MAX_RECENT_PAYEES = 5
        const val MAX_PAYMENTS = 200
        const val PAYMENT_HISTORY_MS = 30L * 24 * 60 * 60_000
        private val WEAK_CODES = setOf("123456", "654321", "012345", "123123", "121212", "112233")
    }
}

enum class AuthError {
    MOBILE, OTP, NAME, EMAIL, DOB, AGE, BANK, ACCOUNT, IFSC, UPI, PAN, TRUSTED_NAME,
    TRUSTED_MOBILE, TRUSTED_SELF, AGREE, WEAK_PASSCODE, PASSCODE_MISMATCH, WRONG_PASSCODE, LOCKED_OUT,
}

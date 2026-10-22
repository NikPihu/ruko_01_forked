package com.ruko.demo.ui.auth

import android.app.Application
import android.os.SystemClock
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.ruko.demo.DemoConfig
import com.ruko.demo.data.AccountStore
import com.ruko.demo.data.Consents
import com.ruko.demo.data.Passcode
import com.ruko.demo.data.PaymentHistory
import com.ruko.demo.data.PaymentRecord
import com.ruko.demo.data.PaymentState
import com.ruko.demo.data.UserProfile
import com.ruko.demo.data.Validators
import com.ruko.demo.net.ApiClient
import com.ruko.demo.net.PaymentOutcome
import com.ruko.demo.net.PaymentStatus
import com.ruko.demo.net.RequestBuilder
import com.ruko.demo.shield.ShieldController
import com.ruko.demo.signals.Flow
import com.ruko.demo.signals.MoneyTxn
import com.ruko.demo.signals.SessionTracker
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import retrofit2.HttpException
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

    // This user's usual typing rhythm for the amount (seconds between digits), last 10 payments.
    var typingGaps by mutableStateOf<List<Double>>(emptyList())
        private set

    // Every payment started here, oldest first: payment id, Scam Shield's decision, the outcome.
    var history by mutableStateOf<List<PaymentRecord>>(emptyList())
        private set
    private var reporting = false
    // History saves run one at a time, in order, so a slow save never overwrites a newer list.
    private val historyIo = Dispatchers.IO.limitedParallelism(1)

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
                typingGaps = withContext(Dispatchers.IO) { store.loadTypingGaps() }
                // A payment still pending when the app was closed was never paid here.
                val now = System.currentTimeMillis()
                val loaded = withContext(Dispatchers.IO) { store.loadHistory() }
                history = PaymentHistory.trim(PaymentHistory.closeAbandoned(loaded, now), now)
                if (history != loaded) withContext(historyIo) { store.saveHistory(history) }
                reportOutcomes()
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
                if (agreed.moneyWatch) ShieldController.enable(getApplication())
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
            // Switching sharing off deletes anything still waiting to be sent.
            if (!new.shareAccounts && old.shareAccounts) ShieldController.clearQueue(getApplication())
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

    /** Scam Shield answered (or could not): the payment enters the history as pending. */
    fun recordCheck(record: PaymentRecord) {
        updateHistory(PaymentHistory.add(history, record, System.currentTimeMillis()))
    }

    /** The PIN was entered (COMPLETED) or the user tapped Cancel (CANCELLED). */
    fun settlePayment(id: String, state: PaymentState) {
        updateHistory(PaymentHistory.settle(history, id, state, System.currentTimeMillis()))
        reportOutcomes()
    }

    /** A new Pay screen: anything still pending was left without paying. */
    fun closeAbandonedPayments() {
        val closed = PaymentHistory.closeAbandoned(history, System.currentTimeMillis())
        if (closed != history) {
            updateHistory(closed)
            reportOutcomes()
        }
    }

    /**
     * Tell the server what happened to each finished payment (POST /v1/payment/outcome, c2-0.6), so
     * the payment graph has it. Off the payment path; whatever fails is sent again next time.
     */
    fun reportOutcomes() {
        if (reporting) return
        val pending = PaymentHistory.toReport(history)
        if (pending.isEmpty()) return
        reporting = true
        viewModelScope.launch {
            val done = mutableSetOf<String>()
            for (p in pending) {
                val outcome = PaymentOutcome(
                    requestId = p.id, userId = DemoConfig.USER_ID, payeeUpiId = p.payee, amountInr = p.amountInr,
                    status = if (p.state == PaymentState.COMPLETED) PaymentStatus.COMPLETED else PaymentStatus.CANCELLED,
                    ts = RequestBuilder.istIso(p.outcomeTs ?: p.ts),
                )
                try {
                    withContext(Dispatchers.IO) { ApiClient.events.paymentOutcome(outcome) }
                    done += p.id
                } catch (e: CancellationException) {
                    throw e
                } catch (e: HttpException) {
                    // The server refused it (e.g. 422): sending it again will not help.
                    if (e.code() in 400..499 && e.code() != 408 && e.code() != 429) done += p.id
                    Log.w(TAG, "payment outcome refused: ${e.code()}")
                } catch (e: Exception) {
                    Log.w(TAG, "payment outcome not sent, will retry", e)
                    break // offline: try the rest later
                }
            }
            if (done.isNotEmpty()) updateHistory(PaymentHistory.markReported(history, done))
            reporting = false
        }
    }

    private fun updateHistory(updated: List<PaymentRecord>) {
        history = updated
        viewModelScope.launch(historyIo) { store.saveHistory(updated) }
    }

    /** After a completed payment: keep how fast the amount was typed, so "slow" means slow for this user. */
    fun rememberTypingGap(gapSeconds: Double?) {
        if (gapSeconds == null) return
        val updated = (typingGaps + gapSeconds).takeLast(SessionTracker.BASELINE_KEEP)
        typingGaps = updated
        viewModelScope.launch(Dispatchers.IO) { store.saveTypingGaps(updated) }
    }

    /** Delete the account and every stored detail, then start again from sign up. */
    fun deleteAccount() {
        viewModelScope.launch {
            withContext(Dispatchers.IO) { store.deleteAll() }
            profile = null
            consents = Consents()
            recentPayees = emptyList()
            payments = emptyList()
            typingGaps = emptyList()
            history = emptyList()
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
        private const val TAG = "CachePayAuth"
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

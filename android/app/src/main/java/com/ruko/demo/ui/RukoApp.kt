package com.ruko.demo.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.ruko.demo.data.PaymentState
import com.ruko.demo.signals.Signals
import com.ruko.demo.ui.alerts.AlertScreen
import com.ruko.demo.ui.alerts.AlertUser
import com.ruko.demo.ui.alerts.ExplainCard
import com.ruko.demo.ui.alerts.PauseScreen
import com.ruko.demo.ui.alerts.ReviewScreen
import com.ruko.demo.ui.alerts.UnavailableScreen
import com.ruko.demo.ui.alerts.screenFor
import com.ruko.demo.ui.auth.AuthState
import com.ruko.demo.ui.auth.AuthViewModel
import com.ruko.demo.ui.auth.LoginScreen
import com.ruko.demo.ui.auth.ProfileScreen
import com.ruko.demo.ui.auth.SignUpFlow
import com.ruko.demo.signals.PastPayment

private object Routes {
    const val HOME = "home"
    const val PAY = "pay"
    const val UNAVAILABLE = "unavailable"
    const val ALERT_T2 = "alert_t2"
    const val ALERT_T3 = "alert_t3"
    const val ALERT_T4 = "alert_t4"
    const val PIN = "pin"
    const val SUCCESS = "success"
    const val PROFILE = "profile"
    const val DEBUG = "debug"
    const val HISTORY = "history"
    const val CONTACTS = "contacts"
}

/** Sign up or login first; the payment app only exists once the account is unlocked. */
@Composable
fun RukoApp() {
    val auth: AuthViewModel = viewModel()
    // One view model for the whole payment flow, scoped to the activity.
    val vm: PaymentViewModel = viewModel()

    // Leaving the app mid-payment (for the call, WhatsApp, a chat) is part of the Pay session.
    // Kept here, not in PaymentApp, so it still counts when the app locks while the user is away.
    LifecycleEventEffect(Lifecycle.Event.ON_STOP) {
        auth.onBackground()
        vm.onAppBackground()
    }
    LifecycleEventEffect(Lifecycle.Event.ON_START) {
        auth.onForeground()
        vm.onAppForeground()
    }

    when (auth.state) {
        AuthState.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = CacheColors.Primary)
        }
        AuthState.NeedsSignUp -> SignUpFlow(auth)
        AuthState.Locked -> LoginScreen(auth)
        AuthState.Unlocked -> PaymentApp(auth, vm)
    }
}

private fun routeFor(screen: AlertScreen): String = when (screen) {
    AlertScreen.PIN -> Routes.PIN
    AlertScreen.EXPLAIN -> Routes.ALERT_T2
    AlertScreen.PAUSE -> Routes.ALERT_T3
    AlertScreen.REVIEW -> Routes.ALERT_T4
    AlertScreen.UNAVAILABLE -> Routes.UNAVAILABLE
}

/** Home, Pay, the alert for the tier (M1), PIN, Success (guide step 5), plus the profile. */
@Composable
private fun PaymentApp(auth: AuthViewModel, vm: PaymentViewModel) {
    val nav = rememberNavController()
    val user = auth.profile.let { AlertUser(it?.firstName.orEmpty(), it?.trustedName, it?.trustedMobile, it?.language) }
    val home = { nav.popBackStack(Routes.HOME, inclusive = false) }
    val cancel = {
        vm.checkedPayment?.let { auth.settlePayment(it.id, PaymentState.CANCELLED) }
        home()
    }
    // Signals are read with the user's current consents at the moment of Pay.
    SideEffect {
        vm.consents = auth.consents
        vm.typingGaps = auth.typingGaps
        vm.pastPayments = auth.history.filter { it.state == PaymentState.COMPLETED }
            .map { PastPayment(it.ts / 1000.0, it.payee.trim().lowercase(), it.amountInr) }
    }

    NavHost(navController = nav, startDestination = Routes.HOME) {
        composable(Routes.HOME) {
            HomeScreen(
                vm = vm,
                firstName = auth.profile?.firstName.orEmpty(),
                consents = auth.consents,
                trustedName = auth.profile?.trustedName,
                trustedMobile = auth.profile?.trustedMobile,
                onPay = {
                    auth.closeAbandonedPayments()
                    vm.reset()
                    nav.navigate(Routes.PAY)
                },
                onProfile = { nav.navigate(Routes.PROFILE) },
                onDebug = { nav.navigate(Routes.DEBUG) },
                onHistory = { nav.navigate(Routes.HISTORY) },
                onPayContact = { nav.navigate(Routes.CONTACTS) },
            )
        }
        composable(Routes.PAY) {
            PayScreen(
                vm = vm,
                recentPayees = auth.recentPayees,
                onBack = { nav.popBackStack() },
                onDecided = { decision ->
                    // Every check enters the history, with its payment id (the request_id).
                    vm.checkedPayment?.let(auth::recordCheck)
                    // Silence is a feature: T0 goes straight to the PIN with nothing shown, T1 adds
                    // a tip there. T2 explains, T3 pauses, T4 is checked by the bank.
                    nav.navigate(routeFor(screenFor((decision as? Decision.Result)?.response?.tier)))
                },
            )
        }
        composable(Routes.UNAVAILABLE) {
            UnavailableScreen(onContinue = { nav.navigate(Routes.PIN) }, onCancel = { cancel() })
        }
        composable(Routes.ALERT_T2) {
            ExplainCard(vm, user.language, onSlid = { nav.navigate(Routes.PIN) }, onCancel = { cancel() })
        }
        composable(Routes.ALERT_T3) {
            PauseScreen(
                vm = vm,
                user = user,
                onPayAnyway = { nav.navigate(Routes.PIN) },
                onKnowThem = { nav.navigate(Routes.ALERT_T2) { popUpTo(Routes.ALERT_T3) { inclusive = true } } },
                onLeave = { home() },
                onCancel = { cancel() },
                onAddTrusted = { nav.navigate(Routes.PROFILE) },
            )
        }
        composable(Routes.ALERT_T4) {
            ReviewScreen(
                vm = vm,
                user = user,
                onPayAnyway = { nav.navigate(Routes.PIN) },
                onLeave = { home() },
                onCancel = { cancel() },
                onAddTrusted = { nav.navigate(Routes.PROFILE) },
            )
        }
        composable(Routes.PIN) {
            PinScreen(vm, user.language, onConfirm = {
                if (!vm.previewing) {
                    auth.rememberPayee(vm.upiId)
                    auth.rememberPayment(vm.upiId, vm.amountInr)
                    auth.rememberTypingGap(vm.lastTypingGap)
                }
                vm.checkedPayment?.let { auth.settlePayment(it.id, PaymentState.COMPLETED) }
                nav.navigate(Routes.SUCCESS) { popUpTo(Routes.HOME) }
            })
        }
        composable(Routes.SUCCESS) {
            SuccessScreen(vm, onDone = { nav.popBackStack(Routes.HOME, inclusive = false) })
        }
        composable(Routes.PROFILE) {
            ProfileScreen(auth, onBack = { nav.popBackStack() })
        }
        composable(Routes.CONTACTS) {
            ContactsScreen(vm, onBack = { nav.popBackStack() }, onReady = {
                auth.closeAbandonedPayments()
                nav.navigate(Routes.PAY) { popUpTo(Routes.HOME) }
            })
        }
        composable(Routes.HISTORY) {
            HistoryScreen(auth.history, onOpen = { auth.reportOutcomes(); auth.syncHistoryFromServer() }, onBack = { nav.popBackStack() })
        }
        composable(Routes.DEBUG) {
            DebugPanel(vm, auth.consents, onBack = { nav.popBackStack() }, onPreviewAlert = { tier ->
                vm.previewAlert(tier, pauseMinutes = 1)
                nav.navigate(routeFor(screenFor(tier)))
            })
        }
    }
}

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
import com.ruko.demo.ui.auth.AuthState
import com.ruko.demo.ui.auth.AuthViewModel
import com.ruko.demo.ui.auth.LoginScreen
import com.ruko.demo.ui.auth.ProfileScreen
import com.ruko.demo.ui.auth.SignUpFlow

private object Routes {
    const val HOME = "home"
    const val PAY = "pay"
    const val DECISION = "decision"
    const val PIN = "pin"
    const val SUCCESS = "success"
    const val PROFILE = "profile"
    const val DEBUG = "debug"
}

/** Sign up or login first; the payment app only exists once the account is unlocked. */
@Composable
fun RukoApp() {
    val auth: AuthViewModel = viewModel()

    LifecycleEventEffect(Lifecycle.Event.ON_STOP) { auth.onBackground() }
    LifecycleEventEffect(Lifecycle.Event.ON_START) { auth.onForeground() }

    when (auth.state) {
        AuthState.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            CircularProgressIndicator(color = CacheColors.Primary)
        }
        AuthState.NeedsSignUp -> SignUpFlow(auth)
        AuthState.Locked -> LoginScreen(auth)
        AuthState.Unlocked -> PaymentApp(auth)
    }
}

/** Home, Pay, decision, PIN, Success (guide step 5), plus the profile. */
@Composable
private fun PaymentApp(auth: AuthViewModel) {
    val nav = rememberNavController()
    // One view model for the whole payment flow, scoped to the activity.
    val vm: PaymentViewModel = viewModel()
    // Signals are read with the user's current consents at the moment of Pay.
    SideEffect { vm.consents = auth.consents }

    NavHost(navController = nav, startDestination = Routes.HOME) {
        composable(Routes.HOME) {
            HomeScreen(
                vm = vm,
                firstName = auth.profile?.firstName.orEmpty(),
                consents = auth.consents,
                onPay = {
                    vm.reset()
                    nav.navigate(Routes.PAY)
                },
                onProfile = { nav.navigate(Routes.PROFILE) },
                onDebug = { nav.navigate(Routes.DEBUG) },
            )
        }
        composable(Routes.PAY) {
            PayScreen(
                vm = vm,
                recentPayees = auth.recentPayees,
                onBack = { nav.popBackStack() },
                onDecided = { decision ->
                    // Silence is a feature: T0 goes straight to the PIN with nothing shown.
                    val silent = decision is Decision.Result && decision.response.tier == "T0"
                    nav.navigate(if (silent) Routes.PIN else Routes.DECISION)
                },
            )
        }
        composable(Routes.DECISION) {
            DecisionScreen(
                vm = vm,
                onContinue = { nav.navigate(Routes.PIN) },
                onCancel = { nav.popBackStack(Routes.HOME, inclusive = false) },
            )
        }
        composable(Routes.PIN) {
            PinScreen(vm, onConfirm = {
                auth.rememberPayee(vm.upiId)
                nav.navigate(Routes.SUCCESS) { popUpTo(Routes.HOME) }
            })
        }
        composable(Routes.SUCCESS) {
            SuccessScreen(vm, onDone = { nav.popBackStack(Routes.HOME, inclusive = false) })
        }
        composable(Routes.PROFILE) {
            ProfileScreen(auth, onBack = { nav.popBackStack() })
        }
        composable(Routes.DEBUG) {
            DebugPanel(vm, auth.consents, onBack = { nav.popBackStack() })
        }
    }
}

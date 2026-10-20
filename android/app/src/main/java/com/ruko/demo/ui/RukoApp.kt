package com.ruko.demo.ui

import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController

private object Routes {
    const val HOME = "home"
    const val PAY = "pay"
    const val DECISION = "decision"
    const val PIN = "pin"
    const val SUCCESS = "success"
}

/** Home, Pay, decision, PIN, Success (guide step 5). */
@Composable
fun RukoApp() {
    val nav = rememberNavController()
    // One view model for the whole payment flow, scoped to the activity.
    val vm: PaymentViewModel = viewModel()

    NavHost(navController = nav, startDestination = Routes.HOME) {
        composable(Routes.HOME) {
            HomeScreen(vm, onPay = {
                vm.reset()
                nav.navigate(Routes.PAY)
            })
        }
        composable(Routes.PAY) {
            PayScreen(
                vm = vm,
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
                nav.navigate(Routes.SUCCESS) { popUpTo(Routes.HOME) }
            })
        }
        composable(Routes.SUCCESS) {
            SuccessScreen(vm, onDone = { nav.popBackStack(Routes.HOME, inclusive = false) })
        }
    }
}

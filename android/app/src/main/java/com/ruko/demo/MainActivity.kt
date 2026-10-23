package com.ruko.demo

import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.ruko.demo.signals.Signals
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.CachePayTheme
import com.ruko.demo.ui.RukoApp
import java.util.function.Consumer

class MainActivity : ComponentActivity() {

    companion object {
        /** Notification extra: the screen to open, e.g. [OPEN_MESSAGES]. */
        const val EXTRA_OPEN = "open"
        const val OPEN_MESSAGES = "messages"
    }

    // Android 15+: tells us whether this window is being recorded or mirrored.
    private val recordingCallback = Consumer<Int> { state ->
        Signals.sensor.screenRecorded = state == WindowManager.SCREEN_RECORDING_STATE_VISIBLE
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        // Draw behind the system bars so the home banner reaches the top edge.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        super.onCreate(savedInstanceState)
        Signals.init(this)
        Signals.openScreen = intent?.getStringExtra(EXTRA_OPEN) ?: Signals.openScreen
        // Keep account details out of the recent apps thumbnail.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            setRecentsScreenshotEnabled(false)
        }
        setContent {
            CachePayTheme {
                Surface(Modifier.fillMaxSize(), color = CacheColors.Background) {
                    RukoApp()
                }
            }
        }
    }

    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        intent.getStringExtra(EXTRA_OPEN)?.let { Signals.openScreen = it }
    }

    override fun onStart() {
        super.onStart()
        // Listeners stay on while the app is in the background, so a call that starts in
        // another app is still timed. start() only adds the ones newly permitted.
        Signals.sensor.start()
        Signals.reportDevice()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            recordingCallback.accept(windowManager.addScreenRecordingCallback(mainExecutor, recordingCallback))
        }
    }

    override fun onStop() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.VANILLA_ICE_CREAM) {
            windowManager.removeScreenRecordingCallback(recordingCallback)
        }
        super.onStop()
    }
}

package com.ruko.demo

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.ruko.demo.ui.RukoApp
import com.ruko.demo.ui.RukoTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            RukoTheme {
                Surface(Modifier.fillMaxSize()) {
                    RukoApp()
                }
            }
        }
    }
}

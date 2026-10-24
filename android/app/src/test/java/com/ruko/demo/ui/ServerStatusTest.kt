package com.ruko.demo.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class ServerStatusTest {
    @Test
    fun okHealthIsConnectedWithModel() {
        val body = """{"status":"ok","model_version":"lgbm-0.2","scorer":"ml","policy_version":"policy-0.1"}"""
        assertEquals(ServerStatus.Connected("lgbm-0.2"), ServerStatus.fromHealth(body))
    }

    @Test
    fun okHealthWithoutModelIsStillConnected() {
        assertEquals(ServerStatus.Connected(null), ServerStatus.fromHealth("""{"status":"ok"}"""))
    }

    @Test
    fun anythingElseIsUnhealthy() {
        assertEquals(ServerStatus.Unhealthy, ServerStatus.fromHealth("""{"status":"degraded"}"""))
        assertEquals(ServerStatus.Unhealthy, ServerStatus.fromHealth("<html>proxy error</html>"))
        assertEquals(ServerStatus.Unhealthy, ServerStatus.fromHealth("[]"))
    }
}

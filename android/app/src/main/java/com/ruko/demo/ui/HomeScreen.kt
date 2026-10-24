package com.ruko.demo.ui

import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import com.ruko.demo.data.Consents
import com.ruko.demo.signals.Signals
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import com.ruko.demo.data.AlertLog
import com.ruko.demo.shield.AlertRecorder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.ruko.demo.BuildConfig
import com.ruko.demo.R
import com.ruko.demo.shield.ShieldController

@Composable
fun HomeScreen(
    vm: PaymentViewModel,
    firstName: String,
    consents: Consents,
    trustedName: String?,
    trustedMobile: String?,
    onPay: () -> Unit,
    onProfile: () -> Unit,
    onDebug: () -> Unit,
    onHistory: () -> Unit,
    onPayContact: () -> Unit,
    onMessageCheck: () -> Unit,
    onAlerts: () -> Unit,
) {
    val context = LocalContext.current
    val alertVersion by AlertRecorder.version.collectAsState()
    val unseenAlerts by produceState(0, alertVersion) {
        value = withContext(Dispatchers.IO) { AlertLog.unseen(AlertRecorder.load(context.applicationContext)) }
    }
    // The background watcher may have changed the episode while the app was away.
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { ShieldController.refresh(context.applicationContext, consents) }
    LaunchedEffect(consents) { ShieldController.refresh(context.applicationContext, consents) }
    val shield = ShieldController.live.value

    Column(Modifier.fillMaxSize().background(CacheColors.Background)) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            Hero(vm, firstName, onProfile = onProfile, onDebug = onDebug)
            ShieldPermissionCard(consents, Modifier.padding(start = 20.dp, end = 20.dp, top = 20.dp))
            EpisodeCard(shield, trustedName, trustedMobile, Modifier.padding(start = 20.dp, end = 20.dp, top = 20.dp))

            Section(
                title = stringResource(R.string.home_money_transfers),
                trailing = { ShieldStatusChip(consents.moneyWatch) },
            ) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TransferAction(CacheIcons.Phone, R.string.home_to_mobile, onPayContact, Modifier.weight(1f))
                    TransferAction(CacheIcons.Bank, R.string.home_to_upi, onPay, Modifier.weight(1f))
                    TransferAction(CacheIcons.Message, R.string.home_message_check, onMessageCheck, Modifier.weight(1f))
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(CacheColors.Surface)
                    .padding(horizontal = 20.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                InfoChip(CacheIcons.Alerts, R.string.nav_alerts, CacheColors.Warning, onAlerts, Modifier.weight(1f))
                InfoChip(CacheIcons.Person, R.string.home_trusted_short, CacheColors.Gold, onProfile, Modifier.weight(1f))
            }
            Spacer(Modifier.height(20.dp))

            DemoBanner(Modifier.padding(horizontal = 20.dp))
            Spacer(Modifier.height(28.dp))
        }

        BottomBar(onScan = onPay, onAlerts = onAlerts, alertBadge = unseenAlerts, onHistory = onHistory, onProfile = onProfile)
    }
}

@Composable
private fun Hero(
    vm: PaymentViewModel,
    firstName: String,
    onProfile: () -> Unit,
    onDebug: () -> Unit,
) {
    Box(
        modifier = Modifier
            .fillMaxWidth()
            .background(Brush.verticalGradient(listOf(CacheColors.HeroTop, CacheColors.HeroBottom)))
            .statusBarsPadding()
            .padding(horizontal = 20.dp, vertical = 16.dp),
    ) {
        Row(
            modifier = Modifier
                .align(Alignment.TopStart)
                .clip(RoundedCornerShape(50))
                .clickable(onClick = onProfile),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Box(
                modifier = Modifier.size(48.dp).clip(CircleShape).background(CacheColors.Gold),
                contentAlignment = Alignment.Center,
            ) {
                if (firstName.isEmpty()) {
                    Icon(CacheIcons.Person, contentDescription = stringResource(R.string.home_profile), tint = CacheColors.HeroTop)
                } else {
                    Text(
                        text = firstName.take(1).uppercase(),
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.Bold,
                        color = CacheColors.HeroTop,
                    )
                }
            }
            if (firstName.isNotEmpty()) {
                Text(
                    text = stringResource(R.string.home_greeting, firstName),
                    style = MaterialTheme.typography.titleMedium,
                    color = Color.White,
                    modifier = Modifier.padding(end = 12.dp),
                )
            }
        }
        Column(
            modifier = Modifier.fillMaxWidth().padding(top = 40.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            ShieldEmblem()
            // Long press the name to open the debug panel (guide step 6).
            Text(
                text = stringResource(R.string.app_name),
                style = MaterialTheme.typography.displaySmall,
                fontWeight = FontWeight.ExtraBold,
                color = Color.White,
                modifier = Modifier.combinedClickable(onClick = {}, onLongClick = onDebug),
            )
            SimulatedPill(Signals.overrides.active)
            Text(
                text = stringResource(R.string.home_hero_tagline),
                style = MaterialTheme.typography.bodyLarge,
                color = Color.White.copy(alpha = 0.85f),
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 16.dp),
            )
            Row(
                modifier = Modifier
                    .clip(RoundedCornerShape(50))
                    .background(Color.White.copy(alpha = 0.12f))
                    .border(1.dp, Color.White.copy(alpha = 0.3f), RoundedCornerShape(50))
                    .clickable(onClick = vm::checkServer)
                    .padding(start = 20.dp, end = 10.dp, top = 10.dp, bottom = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(
                    text = stringResource(R.string.home_check_server),
                    style = MaterialTheme.typography.titleMedium,
                    color = Color.White,
                )
                Box(
                    modifier = Modifier.size(24.dp).clip(CircleShape).background(Color.White),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(CacheIcons.ArrowForward, contentDescription = null, tint = CacheColors.Primary, modifier = Modifier.size(16.dp))
                }
            }
            vm.serverStatus?.let { ServerStatusCard(it) }
            if (BuildConfig.DEBUG) {
                Text(
                    text = stringResource(R.string.home_api_address, BuildConfig.API_BASE_URL),
                    style = MaterialTheme.typography.labelSmall,
                    color = Color.White.copy(alpha = 0.55f),
                )
            }
        }
    }
}

/** The answer to "Check Scam Shield": connected or not, in words, never the server's raw reply. */
@Composable
private fun ServerStatusCard(status: ServerStatus) {
    val tint = when (status) {
        ServerStatus.Checking -> Color.White
        is ServerStatus.Connected -> CacheColors.Success
        ServerStatus.Unhealthy, ServerStatus.Unreachable -> CacheColors.Warning
    }
    val title = stringResource(
        when (status) {
            ServerStatus.Checking -> R.string.home_server_checking
            is ServerStatus.Connected -> R.string.home_server_ok_title
            ServerStatus.Unhealthy, ServerStatus.Unreachable -> R.string.home_server_down_title
        },
    )
    val body = when (status) {
        ServerStatus.Checking -> null
        is ServerStatus.Connected -> stringResource(R.string.home_server_ok_body)
        ServerStatus.Unhealthy, ServerStatus.Unreachable -> stringResource(R.string.home_server_down_body)
    }
    Row(
        modifier = Modifier
            .padding(horizontal = 16.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(Color.Black.copy(alpha = 0.22f))
            .border(1.dp, tint.copy(alpha = 0.5f), RoundedCornerShape(16.dp))
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(
            modifier = Modifier.size(32.dp).clip(CircleShape).background(tint.copy(alpha = 0.18f)),
            contentAlignment = Alignment.Center,
        ) {
            if (status == ServerStatus.Checking) {
                CircularProgressIndicator(modifier = Modifier.size(18.dp), color = tint, strokeWidth = 2.dp)
            } else {
                val icon = if (status is ServerStatus.Connected) CacheIcons.Check else CacheIcons.Warning
                Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(18.dp))
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold, color = Color.White)
            body?.let {
                Text(it, style = MaterialTheme.typography.bodySmall, color = Color.White.copy(alpha = 0.8f))
            }
            if (BuildConfig.DEBUG && status is ServerStatus.Connected && status.model != null) {
                Text(
                    text = stringResource(R.string.home_server_model, status.model),
                    style = MaterialTheme.typography.labelSmall,
                    color = Color.White.copy(alpha = 0.55f),
                )
            }
        }
    }
}

/** Glowing shield badge in the banner. */
@Composable
private fun ShieldEmblem() {
    Box(
        modifier = Modifier
            .size(128.dp)
            .clip(CircleShape)
            .background(Brush.radialGradient(listOf(Color.White.copy(alpha = 0.28f), Color.Transparent))),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(88.dp)
                .clip(CircleShape)
                .background(Brush.linearGradient(listOf(Color.White, Color(0xFFD6E4FF)))),
            contentAlignment = Alignment.Center,
        ) {
            Icon(CacheIcons.Shield, contentDescription = null, tint = CacheColors.Primary, modifier = Modifier.size(52.dp))
        }
    }
}

@Composable
private fun Section(
    title: String,
    trailing: (@Composable () -> Unit)? = null,
    content: @Composable () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 20.dp),
        verticalArrangement = Arrangement.spacedBy(18.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            trailing?.invoke()
        }
        content()
    }
}

@Composable
private fun TransferAction(icon: ImageVector, @StringRes label: Int, onClick: () -> Unit, modifier: Modifier) {
    Column(
        modifier = modifier.clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick).padding(vertical = 4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Box(
            modifier = Modifier
                .size(60.dp)
                .clip(CircleShape)
                .background(Brush.linearGradient(listOf(CacheColors.Primary, CacheColors.PrimaryDeep))),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = Color.White, modifier = Modifier.size(28.dp))
        }
        Text(
            text = stringResource(label),
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            minLines = 2,
            maxLines = 2,
        )
    }
}

@Composable
private fun InfoChip(icon: ImageVector, @StringRes label: Int, tint: Color, onClick: () -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier
            .cacheCard(radius = 12.dp)
            .clickable(onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(22.dp))
        Text(stringResource(label), style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun BottomBar(onScan: () -> Unit, onAlerts: () -> Unit, alertBadge: Int, onHistory: () -> Unit, onProfile: () -> Unit) {
    Box(Modifier.fillMaxWidth().background(CacheColors.Surface).navigationBarsPadding()) {
        Row(
            modifier = Modifier.fillMaxWidth().height(72.dp).padding(horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            NavItem(CacheIcons.Home, R.string.nav_home, selected = true, onClick = {}, modifier = Modifier.weight(1f))
            NavItem(CacheIcons.Alerts, R.string.nav_alerts, selected = false, onClick = onAlerts, modifier = Modifier.weight(1f), badge = alertBadge)
            Spacer(Modifier.weight(1f))
            NavItem(CacheIcons.History, R.string.nav_history, selected = false, onClick = onHistory, modifier = Modifier.weight(1f))
            NavItem(CacheIcons.Person, R.string.nav_profile, selected = false, onClick = onProfile, modifier = Modifier.weight(1f))
        }
        Box(
            modifier = Modifier
                .align(Alignment.TopCenter)
                .offset(y = (-20).dp)
                .size(72.dp)
                .clip(CircleShape)
                .background(CacheColors.Background)
                .padding(5.dp)
                .clip(CircleShape)
                .background(Brush.linearGradient(listOf(CacheColors.Primary, CacheColors.PrimaryDeep)))
                .clickable(onClick = onScan),
            contentAlignment = Alignment.Center,
        ) {
            Icon(CacheIcons.Scan, contentDescription = stringResource(R.string.nav_scan), tint = Color.White, modifier = Modifier.size(32.dp))
        }
    }
}

@Composable
private fun NavItem(icon: ImageVector, @StringRes label: Int, selected: Boolean, onClick: () -> Unit, modifier: Modifier, badge: Int = 0) {
    val color = if (selected) Color.White else CacheColors.TextSecondary
    Column(
        modifier = modifier.clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick).padding(vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box {
            Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(26.dp))
            if (badge > 0) {
                Box(
                    modifier = Modifier
                        .align(Alignment.TopEnd)
                        .offset(x = 8.dp, y = (-4).dp)
                        .size(18.dp)
                        .clip(CircleShape)
                        .background(CacheColors.Danger),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(if (badge > 9) "9+" else badge.toString(), color = Color.White, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold)
                }
            }
        }
        Text(
            text = stringResource(label),
            style = MaterialTheme.typography.labelMedium,
            color = color,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
        )
    }
}

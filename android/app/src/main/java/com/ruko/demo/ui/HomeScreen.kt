package com.ruko.demo.ui

import android.widget.Toast
import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import com.ruko.demo.data.Consents
import com.ruko.demo.signals.Signals
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
) {
    val context = LocalContext.current
    val demoOnly = { Toast.makeText(context, R.string.demo_only, Toast.LENGTH_SHORT).show() }
    // The background watcher may have changed the episode while the app was away.
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { ShieldController.refresh(context.applicationContext, consents) }
    LaunchedEffect(consents) { ShieldController.refresh(context.applicationContext, consents) }
    val shield = ShieldController.live.value

    Column(Modifier.fillMaxSize().background(CacheColors.Background)) {
        Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
            Hero(vm, firstName, onProfile = onProfile, onHelp = demoOnly, onDebug = onDebug)
            ShieldPermissionCard(consents, Modifier.padding(start = 20.dp, end = 20.dp, top = 20.dp))
            EpisodeCard(shield, trustedName, trustedMobile, Modifier.padding(start = 20.dp, end = 20.dp, top = 20.dp))

            Section(
                title = stringResource(R.string.home_money_transfers),
                trailing = { ShieldStatusChip(consents.moneyWatch) },
            ) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TransferAction(CacheIcons.Phone, R.string.home_to_mobile, onPayContact, Modifier.weight(1f))
                    TransferAction(CacheIcons.Bank, R.string.home_to_bank, onPay, Modifier.weight(1f))
                    TransferAction(CacheIcons.ArrowDown, R.string.home_receive, demoOnly, Modifier.weight(1f))
                    TransferAction(CacheIcons.Rupee, R.string.home_check_balance, demoOnly, Modifier.weight(1f))
                }
            }

            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .background(CacheColors.Surface)
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp, vertical = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                InfoChip(CacheIcons.Person, R.string.home_trusted, CacheColors.Gold, onProfile)
                InfoChip(CacheIcons.Shield, R.string.home_how_shield, CacheColors.PrimaryLight, demoOnly)
            }

            Section(title = stringResource(R.string.home_bills)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    BillTile(CacheIcons.Smartphone, R.string.bill_mobile, CacheColors.Info, demoOnly, Modifier.weight(1f))
                    BillTile(CacheIcons.House, R.string.bill_rent, CacheColors.Accent, demoOnly, Modifier.weight(1f))
                    BillTile(CacheIcons.Bolt, R.string.bill_electricity, CacheColors.Gold, demoOnly, Modifier.weight(1f))
                    BillTile(CacheIcons.Receipt, R.string.bill_loan, CacheColors.Success, demoOnly, Modifier.weight(1f))
                }
                PayAnyUpiRow(onPay)
            }

            DemoBanner(Modifier.padding(horizontal = 20.dp))
            Spacer(Modifier.height(28.dp))
        }

        BottomBar(onScan = onPay, onHistory = onHistory, onOther = demoOnly)
    }
}

@Composable
private fun Hero(
    vm: PaymentViewModel,
    firstName: String,
    onProfile: () -> Unit,
    onHelp: () -> Unit,
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
        Box(
            modifier = Modifier
                .align(Alignment.TopEnd)
                .size(36.dp)
                .clip(CircleShape)
                .border(2.dp, Color.White, CircleShape)
                .clickable(onClick = onHelp),
            contentAlignment = Alignment.Center,
        ) {
            Text("?", color = Color.White, fontWeight = FontWeight.Bold)
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
            vm.serverStatus?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = Color.White.copy(alpha = 0.8f),
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                )
            }
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
                .background(Brush.linearGradient(listOf(Color.White, Color(0xFFDCD3F5)))),
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
private fun InfoChip(icon: ImageVector, @StringRes label: Int, tint: Color, onClick: () -> Unit) {
    Row(
        modifier = Modifier
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
private fun BillTile(icon: ImageVector, @StringRes label: Int, tint: Color, onClick: () -> Unit, modifier: Modifier) {
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(
            modifier = Modifier.fillMaxWidth().height(64.dp).cacheCard(radius = 14.dp).clickable(onClick = onClick),
            contentAlignment = Alignment.Center,
        ) {
            Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.size(30.dp))
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
private fun PayAnyUpiRow(onPay: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .cacheCard(radius = 14.dp)
            .clickable(onClick = onPay)
            .padding(horizontal = 18.dp, vertical = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(stringResource(R.string.home_pay_upi), style = MaterialTheme.typography.titleMedium)
        Icon(CacheIcons.ArrowForward, contentDescription = null, tint = CacheColors.PrimaryLight)
    }
}

@Composable
private fun BottomBar(onScan: () -> Unit, onHistory: () -> Unit, onOther: () -> Unit) {
    Box(Modifier.fillMaxWidth().background(CacheColors.Surface).navigationBarsPadding()) {
        Row(
            modifier = Modifier.fillMaxWidth().height(72.dp).padding(horizontal = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            NavItem(CacheIcons.Home, R.string.nav_home, selected = true, onClick = {}, modifier = Modifier.weight(1f))
            NavItem(CacheIcons.Search, R.string.nav_search, selected = false, onClick = onOther, modifier = Modifier.weight(1f))
            Spacer(Modifier.weight(1f))
            NavItem(CacheIcons.Alerts, R.string.nav_alerts, selected = false, onClick = onOther, modifier = Modifier.weight(1f))
            NavItem(CacheIcons.History, R.string.nav_history, selected = false, onClick = onHistory, modifier = Modifier.weight(1f))
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
private fun NavItem(icon: ImageVector, @StringRes label: Int, selected: Boolean, onClick: () -> Unit, modifier: Modifier) {
    val color = if (selected) Color.White else CacheColors.TextSecondary
    Column(
        modifier = modifier.clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick).padding(vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Icon(icon, contentDescription = null, tint = color, modifier = Modifier.size(26.dp))
        Text(
            text = stringResource(label),
            style = MaterialTheme.typography.labelMedium,
            color = color,
            fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
        )
    }
}

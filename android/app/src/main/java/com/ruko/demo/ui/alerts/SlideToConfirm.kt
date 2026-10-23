package com.ruko.demo.ui.alerts

import androidx.compose.animation.core.animate
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.disabled
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import com.ruko.demo.R
import com.ruko.demo.ui.CacheColors
import com.ruko.demo.ui.CacheIcons
import kotlin.math.roundToInt

private val THUMB = 56.dp

/**
 * Drag the thumb across (at least [AlertRules.SLIDE_DONE] of the way) to go on to the PIN. A tap is
 * not enough, which is the point. TalkBack users get a "Confirm payment" action instead.
 */
@Composable
fun SlideToConfirm(label: String, enabled: Boolean, onConfirm: () -> Unit, modifier: Modifier = Modifier) {
    val confirmLabel = stringResource(R.string.alert_confirm_payment)
    val thumbPx = with(LocalDensity.current) { (THUMB + 8.dp).toPx() }
    var trackPx by remember { mutableIntStateOf(0) }
    var offset by remember { mutableFloatStateOf(0f) }
    var done by remember { mutableStateOf(false) }
    val maxPx = (trackPx - thumbPx).coerceAtLeast(1f)
    val dragState = rememberDraggableState { delta -> offset = (offset + delta).coerceIn(0f, maxPx) }
    val tint = if (enabled) CacheColors.Primary else CacheColors.TextSecondary

    Box(
        modifier = modifier
            .fillMaxWidth()
            .height(THUMB + 8.dp)
            .clip(RoundedCornerShape(50))
            .background(tint.copy(alpha = 0.18f))
            .border(1.dp, tint.copy(alpha = 0.5f), RoundedCornerShape(50))
            .onSizeChanged { trackPx = it.width }
            .semantics(mergeDescendants = true) {
                contentDescription = label
                if (enabled) {
                    customActions = listOf(CustomAccessibilityAction(confirmLabel) { onConfirm(); true })
                } else {
                    disabled()
                }
            },
        contentAlignment = Alignment.CenterStart,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = FontWeight.SemiBold,
            color = if (enabled) CacheColors.TextPrimary else CacheColors.TextSecondary,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(start = THUMB, end = 12.dp),
        )
        Box(
            modifier = Modifier
                .offset { IntOffset(offset.roundToInt(), 0) }
                .padding(4.dp)
                .size(THUMB)
                .clip(CircleShape)
                .background(if (enabled) CacheColors.Primary else CacheColors.CardBorder)
                .draggable(
                    state = dragState,
                    orientation = Orientation.Horizontal,
                    enabled = enabled && !done,
                    onDragStopped = {
                        if (offset >= AlertRules.SLIDE_DONE * maxPx) {
                            done = true
                            offset = maxPx
                            onConfirm()
                        } else {
                            animate(offset, 0f) { value, _ -> offset = value }
                        }
                    },
                ),
            contentAlignment = Alignment.Center,
        ) {
            Icon(CacheIcons.ArrowForward, contentDescription = null, tint = Color.White)
        }
    }
}

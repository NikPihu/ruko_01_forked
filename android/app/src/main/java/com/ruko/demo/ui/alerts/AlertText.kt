package com.ruko.demo.ui.alerts

import androidx.annotation.StringRes
import com.ruko.demo.R

/**
 * Title and body for a server `message_key` (contract: `t1_tip`, `t2_generic`, `t3_generic`, or
 * `<tier>_<playbook>`). The tier picks the screen; the key only picks the words. A key this app
 * does not know (a new playbook found by discovery, a typo) falls back to the tier's generic text,
 * so every alert still renders. Never a score, never the tier label.
 */
object AlertText {

    /** Scam types with their own words (`backend/features` playbooks). */
    val PLAYBOOKS = listOf("digital_arrest", "trading_group", "task_job", "fake_kyc_apk", "refund_qr", "fake_customer_care")

    data class Copy(@StringRes val title: Int, @StringRes val body: Int)

    private val byKey: Map<String, Copy> = mapOf(
        "t1_tip" to Copy(R.string.t1_tip_title, R.string.t1_tip_body),
        "t2_generic" to Copy(R.string.t2_generic_title, R.string.t2_generic_body),
        "t3_generic" to Copy(R.string.t3_generic_title, R.string.t3_generic_body),
        "t4_review" to Copy(R.string.t4_review_title, R.string.t4_review_body),
        "t2_digital_arrest" to Copy(R.string.t2_digital_arrest_title, R.string.t2_digital_arrest_body),
        "t3_digital_arrest" to Copy(R.string.t3_digital_arrest_title, R.string.t3_digital_arrest_body),
        "t2_trading_group" to Copy(R.string.t2_trading_group_title, R.string.t2_trading_group_body),
        "t3_trading_group" to Copy(R.string.t3_trading_group_title, R.string.t3_trading_group_body),
        "t2_task_job" to Copy(R.string.t2_task_job_title, R.string.t2_task_job_body),
        "t3_task_job" to Copy(R.string.t3_task_job_title, R.string.t3_task_job_body),
        "t2_fake_kyc_apk" to Copy(R.string.t2_fake_kyc_apk_title, R.string.t2_fake_kyc_apk_body),
        "t3_fake_kyc_apk" to Copy(R.string.t3_fake_kyc_apk_title, R.string.t3_fake_kyc_apk_body),
        "t2_refund_qr" to Copy(R.string.t2_refund_qr_title, R.string.t2_refund_qr_body),
        "t3_refund_qr" to Copy(R.string.t3_refund_qr_title, R.string.t3_refund_qr_body),
        "t2_fake_customer_care" to Copy(R.string.t2_fake_customer_care_title, R.string.t2_fake_customer_care_body),
        "t3_fake_customer_care" to Copy(R.string.t3_fake_customer_care_title, R.string.t3_fake_customer_care_body),
    )

    /** Every key with its own words. */
    val KEYS: Set<String> get() = byKey.keys

    private fun generic(tier: String): Copy = when (tier) {
        "T1" -> byKey.getValue("t1_tip")
        "T2" -> byKey.getValue("t2_generic")
        "T4" -> byKey.getValue("t4_review")
        else -> byKey.getValue("t3_generic")
    }

    /** The scam type in a key (`t3_digital_arrest` → `digital_arrest`), or null for generic keys. */
    fun playbookOf(key: String?): String? =
        key?.takeIf { TIER_KEY.matches(it) }?.substringAfter('_')?.takeIf { it in PLAYBOOKS }

    /**
     * The words for [key] shown on [tier]'s screen. The same scam type keeps its words when the
     * screen changes tier ("I know this person" turns a T3 pause into the T2 card).
     */
    fun copy(key: String?, tier: String): Copy {
        val own = key?.takeIf { TIER_KEY.matches(it) }?.substringAfter('_') ?: return generic(tier)
        return byKey["${tier.lowercase()}_$own"] ?: generic(tier)
    }

    @StringRes
    fun messageTitle(key: String?, tier: String): Int = copy(key, tier).title

    @StringRes
    fun messageBody(key: String?, tier: String): Int = copy(key, tier).body

    private val TIER_KEY = Regex("t[0-4]_[a-z0-9_]+")
}

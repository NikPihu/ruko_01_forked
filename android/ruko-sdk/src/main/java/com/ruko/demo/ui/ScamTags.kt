package com.ruko.demo.ui

import com.ruko.sdk.R

/** The words for a lure tag (also used by the "may be a scam" notification). */
fun scamTagRes(tag: String): Int =
    when (tag) {
        "arrest_threat" -> R.string.msg_tag_arrest_threat
        "kyc" -> R.string.msg_tag_kyc
        "refund" -> R.string.msg_tag_refund
        "task_job" -> R.string.msg_tag_task_job
        "trading_tip" -> R.string.msg_tag_trading_tip
        "other_scam" -> R.string.msg_tag_other_scam
        else -> R.string.msg_tag_other
    }

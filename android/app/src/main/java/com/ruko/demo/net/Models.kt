package com.ruko.demo.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

// Mirrors contract c2-0.11: backend/schema/events.py, published in contracts/.
// The server rejects unknown fields with HTTP 422, so keys must match exactly; ContractTest
// checks these classes against contracts/c2_decide.schema.json and the example files.
// A null field means "unknown", never "safe".

const val CONTRACT_VERSION = "c2-0.11"

@Serializable
enum class CallKind {
    @SerialName("sim") SIM,
    @SerialName("voip") VOIP,
}

@Serializable
enum class CallDirection {
    @SerialName("incoming") INCOMING,
    @SerialName("outgoing") OUTGOING,
}

@Serializable
enum class EntryMethod {
    @SerialName("typed") TYPED,
    @SerialName("qr") QR,
    @SerialName("contact") CONTACT,
    @SerialName("collect") COLLECT,
}

/** Answer to "Who are you paying?", asked for new payees above a small amount. */
@Serializable
enum class PayerSays {
    @SerialName("government") GOVERNMENT,
    @SerialName("company") COMPANY,
    @SerialName("family") FAMILY,
    @SerialName("shop") SHOP,
    @SerialName("investment") INVESTMENT,
    @SerialName("other") OTHER,
}

@Serializable
data class CallSignal(
    val active: Boolean? = null,
    val kind: CallKind? = null,
    val direction: CallDirection? = null,
    @SerialName("caller_number") val callerNumber: String? = null, // only for FRI / registry lookups
    @SerialName("caller_in_contacts") val callerInContacts: Boolean? = null,
    @SerialName("started_min_ago") val startedMinAgo: Double? = null,
    @SerialName("ended_min_ago") val endedMinAgo: Double? = null, // a call that just finished
    @SerialName("speaker_on") val speakerOn: Boolean? = null, // c2-0.5: call on the loudspeaker at Pay
    val video: Boolean? = null, // c2-0.10: VoIP call while another app uses the camera (a video call)
)

@Serializable
data class DeviceSignal(
    @SerialName("remote_access_active") val remoteAccessActive: Boolean? = null,
    @SerialName("remote_app_installed_min_ago") val remoteAppInstalledMinAgo: Double? = null,
    @SerialName("untrusted_accessibility") val untrustedAccessibility: Boolean? = null,
    @SerialName("sideloaded_last_24h") val sideloadedLast24h: Boolean? = null,
)

@Serializable
data class LureSignal(val tag: String, val conf: Double, @SerialName("min_ago") val minAgo: Double)

/**
 * The task-scam episode the background watcher keeps across payees for up to 30 days (c2-0.3).
 * Bait fields are null when SMS can't be read. Built by shield/EpisodeTracker.
 */
@Serializable
data class EpisodeSignal(
    val state: String, // none | watching | active | dismissed
    @SerialName("age_days") val ageDays: Double? = null,
    @SerialName("bait_credits") val baitCredits: Int? = null,
    @SerialName("bait_inr") val baitInr: Double? = null,
    val outs: Int? = null,
    @SerialName("outs_inr") val outsInr: Double? = null,
    @SerialName("new_payees") val newPayees: Int? = null,
    @SerialName("escalation_steps") val escalationSteps: Int? = null,
    @SerialName("last_out_inr") val lastOutInr: Double? = null,
    @SerialName("out_to_in_ratio") val outToInRatio: Double? = null,
    @SerialName("payee_seen_in_episode") val payeeSeenInEpisode: Boolean? = null,
    @SerialName("rules_version") val rulesVersion: String? = null,
)

/**
 * How the user behaved on the Pay screen of this payment (c2-0.5). Counts and rounded seconds
 * only, never the keys typed or the other apps opened. Built by signals/SessionTracker.
 */
@Serializable
data class SessionSignal(
    @SerialName("amount_digits") val amountDigits: Int? = null,
    @SerialName("amount_median_gap_s") val amountMedianGapS: Double? = null,
    @SerialName("amount_max_gap_s") val amountMaxGapS: Double? = null,
    @SerialName("amount_gap_vs_usual") val amountGapVsUsual: Double? = null, // null until 3 past payments
    @SerialName("amount_edits") val amountEdits: Int? = null,
    @SerialName("payee_pasted") val payeePasted: Boolean? = null,
    @SerialName("pasted_within_s_of_return") val pastedWithinSOfReturn: Double? = null,
    @SerialName("app_switches") val appSwitches: Int? = null,
    @SerialName("away_s") val awayS: Double? = null,
    @SerialName("pay_screen_s") val payScreenS: Double? = null,
    @SerialName("abandoned_flows_30m") val abandonedFlows30m: Int? = null,
)

@Serializable
data class Context(
    val call: CallSignal? = null,
    val device: DeviceSignal? = null,
    val lures: List<LureSignal> = emptyList(),
    val episode: EpisodeSignal? = null,
    val session: SessionSignal? = null, // c2-0.5; null when "Session checks" is off
    // c2-0.7: the payee (its UPI ID, or the mobile it was paid by) is a saved contact. Only this
    // yes/no leaves the phone, never names or numbers; null when contacts cannot be read.
    @SerialName("payee_in_contacts") val payeeInContacts: Boolean? = null,
    // c2-0.8: the phone's own model on what only the phone saw; null when it did not run.
    @SerialName("device_verdict") val deviceVerdict: DeviceVerdict? = null,
)

/**
 * The phone's verdict (c2-0.8), built by signals/DeviceVerdicts from signals/DeviceModel. The
 * readings behind it (calls, apps, SMS, the Pay screen, payment history) never leave the phone.
 */
@Serializable
data class DeviceVerdict(
    @SerialName("model_version") val modelVersion: String,
    @SerialName("fraud_class") val fraudClass: String? = null, // the engine's playbook names
    val level: String, // low | medium | high
    val c: Double? = null, // calls and remote control; null = not measured
    val l: Double? = null, // lure messages and the task-scam episode
    val b: Double? = null, // own spending and the Pay screen
    val reasons: List<String> = emptyList(),
)

/** The server's threat analysis of the payment (c2-0.8). */
@Serializable
data class Threat(
    val score: Int, // 0..100
    val level: String, // none | low | medium | high | critical
    @SerialName("fraud_type") val fraudType: String? = null,
    val families: List<String> = emptyList(),
)

@Serializable
data class DecideRequest(
    @SerialName("request_id") val requestId: String, // a new UUID per Pay tap, echoed back
    @SerialName("user_id") val userId: String,
    @SerialName("payee_upi_id") val payeeUpiId: String,
    @SerialName("amount_inr") val amountInr: Double,
    @SerialName("entry_method") val entryMethod: EntryMethod,
    @SerialName("payer_says") val payerSays: PayerSays? = null,
    val ts: String, // ISO 8601 with +05:30
    val context: Context? = null, // null when the user opted out of every phone signal
)

// ---------- Episode events (c2-0.4): the watcher's state changes, only with "Share" on ----------

@Serializable
data class EpisodeAccount(
    @SerialName("upi_id") val upiId: String,
    val role: String, // bait_sender | payee
    val n: Int,
    val inr: Double,
    @SerialName("first_seen_min_ago") val firstSeenMinAgo: Double,
    val via: String? = null, // payees only: this_app | other_app
    val step: Int? = null, // payees only: position in the escalation run
)

@Serializable
data class EpisodeEvent(
    @SerialName("event_id") val eventId: String,
    @SerialName("episode_id") val episodeId: String,
    @SerialName("user_id") val userId: String,
    val ts: String,
    val trigger: String, // watching | active | out_payment | bait | dismissed | closed
    @SerialName("rules_version") val rulesVersion: String,
    val summary: EpisodeSignal,
    val accounts: List<EpisodeAccount> = emptyList(),
)

@Serializable
data class EpisodeEventResponse(
    @SerialName("event_id") val eventId: String,
    @SerialName("episode_risk") val episodeRisk: String, // unknown | low | elevated | high
    val reasons: List<String> = emptyList(),
    @SerialName("message_key") val messageKey: String? = null,
    @SerialName("case_id") val caseId: String? = null,
    @SerialName("contract_version") val contractVersion: String? = null,
)

@Serializable
data class DecideResponse(
    @SerialName("request_id") val requestId: String,
    val tier: String,
    val reasons: List<String>,
    @SerialName("message_key") val messageKey: String? = null,
    @SerialName("pause_minutes") val pauseMinutes: Int = 0,
    val playbook: String? = null,
    val stage: String? = null,
    @SerialName("evidence_id") val evidenceId: String? = null,
    @SerialName("fail_open") val failOpen: Boolean = false,
    @SerialName("contract_version") val contractVersion: String? = null,
    val threat: Threat? = null, // c2-0.8; null when RUKO failed open
)

// ---------- Payment outcome (c2-0.6): after the PIN or Cancel, off the payment path ----------

@Serializable
enum class PaymentStatus {
    @SerialName("completed") COMPLETED, // the user entered the PIN
    @SerialName("cancelled") CANCELLED, // the user left without paying
}

/** The payment id is the /v1/decide `request_id`. Payee and amount are repeated so the server can
 * record the payment even when its check never arrived (timeout, fail open). Safe to retry. */
@Serializable
data class PaymentOutcome(
    @SerialName("request_id") val requestId: String,
    @SerialName("user_id") val userId: String,
    @SerialName("payee_upi_id") val payeeUpiId: String,
    @SerialName("amount_inr") val amountInr: Double,
    val status: PaymentStatus,
    val ts: String,
)

@Serializable
data class PaymentOutcomeResponse(
    @SerialName("request_id") val requestId: String,
    val status: PaymentStatus,
    val recorded: Boolean,
    @SerialName("contract_version") val contractVersion: String? = null,
)

// ---------- c2-0.11: money received, read from a bank SMS on this phone ----------

/** POST /v1/payment/received: one credit the money watch read from a bank SMS (never the text). Only
 * with "Share money received" on. Safe to retry: the server records an event_id once. */
@Serializable
data class MoneyReceived(
    @SerialName("event_id") val eventId: String,
    @SerialName("user_id") val userId: String,
    @SerialName("sender_upi_id") val senderUpiId: String?, // null: the alert named no UPI ID (unknown)
    @SerialName("amount_inr") val amountInr: Double,
    val ts: String,
    val source: String = "bank_sms",
)

@Serializable
data class MoneyReceivedResponse(
    @SerialName("event_id") val eventId: String,
    val recorded: Boolean,
    @SerialName("contract_version") val contractVersion: String? = null,
)

// ---------- c2-0.9: alert feedback, watch events, the app's own payments ----------

/** What the user did on an alert screen. Wire names match the contract's FeedbackAction. */
@Serializable
enum class FeedbackAction {
    @SerialName("tip_seen") TIP_SEEN,
    @SerialName("slid_to_pay") SLID_TO_PAY,
    @SerialName("cancelled_from_alert") CANCELLED_FROM_ALERT,
    @SerialName("waited") WAITED,
    @SerialName("pay_after_pause") PAY_AFTER_PAUSE,
    @SerialName("called_trusted") CALLED_TRUSTED,
    @SerialName("messaged_trusted") MESSAGED_TRUSTED,
    @SerialName("called_1930") CALLED_1930,
    @SerialName("i_know_them") I_KNOW_THEM,
}

/** Why the user says they know the payee ("I know this person"). */
@Serializable
enum class KnowWhy {
    @SerialName("family") FAMILY,
    @SerialName("friend") FRIEND,
    @SerialName("shop") SHOP,
    @SerialName("landlord") LANDLORD,
    @SerialName("employer") EMPLOYER,
    @SerialName("other") OTHER,
}

/** POST /v1/feedback. One action on one alert; safe to retry with the same feedback_id. */
@Serializable
data class Feedback(
    @SerialName("feedback_id") val feedbackId: String,
    @SerialName("request_id") val requestId: String, // the payment id (/v1/decide request_id)
    @SerialName("user_id") val userId: String,
    val action: FeedbackAction,
    val why: KnowWhy? = null, // only with I_KNOW_THEM
    @SerialName("dwell_ms") val dwellMs: Long? = null, // alert shown -> this action
    val ts: String,
)

@Serializable
data class FeedbackResponse(
    @SerialName("feedback_id") val feedbackId: String,
    val recorded: Boolean,
    // I_KNOW_THEM only: false when RUKO still recommends waiting (list hit or someone controls the phone).
    @SerialName("trusted_accepted") val trustedAccepted: Boolean? = null,
    @SerialName("message_key") val messageKey: String? = null,
    @SerialName("contract_version") val contractVersion: String? = null,
)

@Serializable
enum class WatchKind {
    @SerialName("lure_seen") LURE_SEEN, // tag only, never the message text
    @SerialName("remote_access_on") REMOTE_ACCESS_ON,
    @SerialName("long_unknown_call") LONG_UNKNOWN_CALL,
    @SerialName("sideload") SIDELOAD,
}

/** POST /v1/watch. Sent only when a threshold is crossed, only with "Early warnings" on. */
@Serializable
data class WatchEvent(
    @SerialName("event_id") val eventId: String,
    @SerialName("user_id") val userId: String,
    val kind: WatchKind,
    val ts: String,
    @SerialName("lure_tag") val lureTag: String? = null,
    @SerialName("lure_conf") val lureConf: Double? = null,
    val source: String? = null, // sms | notification
    @SerialName("ai_written") val aiWritten: Boolean? = null, // c2-0.10, lure_seen only
    @SerialName("call_kind") val callKind: CallKind? = null,
    @SerialName("call_minutes") val callMinutes: Double? = null,
)

@Serializable
data class WatchEventResponse(
    @SerialName("event_id") val eventId: String,
    val recorded: Boolean,
    val stage: String? = null,
    @SerialName("contract_version") val contractVersion: String? = null,
)

/** One of the user's own payments as RUKO recorded it. Plain words only, never a score. */
@Serializable
data class MyPayment(
    @SerialName("payment_id") val paymentId: String,
    @SerialName("payee_upi_id") val payeeUpiId: String,
    @SerialName("amount_inr") val amountInr: Double,
    val ts: String,
    val tier: String,
    val reasons: List<String>,
    @SerialName("message_key") val messageKey: String? = null,
    val playbook: String? = null,
    val status: String, // checked | completed | cancelled
    @SerialName("outcome_ts") val outcomeTs: String? = null,
)

@Serializable
data class MyPayments(
    val payments: List<MyPayment>,
    @SerialName("contract_version") val contractVersion: String? = null,
)

// explicitNulls sends unknown fields as null; ignoreUnknownKeys keeps the app working when
// the server adds an optional response field before the app catches up.
val RukoJson = Json {
    encodeDefaults = true
    explicitNulls = true
    ignoreUnknownKeys = true
}

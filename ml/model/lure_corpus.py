"""Synthetic SMS corpus for the on-device lure classifier -> ml/data/lure_texts.csv

    PYTHONPATH=backend;ml;data python -m model.lure_corpus

Written by the team from public I4C / RBI / NPCI advisories, with LLM help, and labelled synthetic
(deck appendix B). Scam scripts are fluent on purpose: AI-written lures have no typos, so the
model must learn intent (pay or install now, secrecy, authority, unlockable earnings), not style.
`normal` holds everyday messages AND look-alikes that share the scam words: real OTPs, genuine
bank KYC reminders, police and RBI awareness SMS, real refunds, real job and broker messages.

Every row keeps its template id, so evaluation can hold out whole templates (unseen phrasings).
"""
from __future__ import annotations

import argparse
import random
import re
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "lure_texts.csv"

FILL: dict[str, list[str]] = {
    "name": ["Rahul", "Priya", "Meena ji", "Sunita", "Amit", "Rohan", "Neha", "Arjun", "Kavita", "Imran",
             "Deepak", "Anjali", "Suresh", "Pooja", "Vikram", "Farah"],
    "bank": ["SBI", "HDFC Bank", "ICICI Bank", "Axis Bank", "PNB", "Kotak Bank", "Bank of Baroda", "Canara Bank"],
    "agency": ["CBI", "Mumbai Cyber Crime", "Narcotics Control Bureau", "ED", "Customs", "TRAI",
               "Delhi Police Crime Branch", "RBI Vigilance"],
    "city": ["Mumbai", "Delhi", "Kolkata", "Chennai", "Hyderabad", "Bengaluru"],
    "company": ["Amazon", "Flipkart", "Meesho", "YouTube", "Google Maps", "Myntra", "Swiggy"],
    "courier": ["FedEx", "DHL", "Blue Dart", "India Post", "Delhivery"],
    "stock": ["SUZLON", "IREDA", "Tata Power", "Yes Bank", "an upcoming IPO", "RVNL", "Adani Green"],
    "app": ["AnyDesk", "the RBI KYC app", "QuickSupport", "the SBI YONO update", "RustDesk", "the Aadhaar Seva app"],
    "time": ["tonight 9:30 PM", "within 2 hours", "today itself", "before 6 PM", "in 30 minutes"],
    "pct": ["20%", "35%", "40%", "300%", "15% weekly", "double"],
    "days": ["2", "3", "7", "10"],
    "broker": ["Zerodha", "Groww", "Upstox", "Angel One"],
    "month": ["October", "November", "December"],
    "relation": ["Mummy", "Papa", "Didi", "Bhaiya", "Beta"],
}
HI_FILL = {
    "agency": ["सीबीआई", "मुंबई साइबर क्राइम", "नारकोटिक्स ब्यूरो", "ईडी", "कस्टम विभाग", "ट्राई"],
    "bank": ["एसबीआई", "एचडीएफसी बैंक", "पीएनबी", "बैंक ऑफ बड़ौदा", "एक्सिस बैंक"],
    "time": ["आज रात 9:30 बजे", "2 घंटे में", "आज ही", "शाम 6 बजे तक"],
    "relation": ["मम्मी", "पापा", "दीदी", "भैया", "बेटा"],
}

# (tag, language, template). Slots: {name} {bank} {agency} {city} {company} {courier} {stock} {app}
# {time} {pct} {days} {broker} {month} {relation} {amount} {amount2} {small} {link} {phone} {case}
# {upi} {otp} {acct} {ref} {date}
TEMPLATES: list[tuple[str, str, str]] = [
    # ---------------- arrest_threat: "digital arrest" ----------------
    ("arrest_threat", "en", "This is {agency}. A parcel in your name containing illegal drugs was seized at {city} airport. Case {case}. Join the video call at {link} immediately or a warrant will be issued."),
    ("arrest_threat", "en", "Your Aadhaar number is linked to a money laundering case ({case}). Do not disconnect the call and do not inform your family. The {agency} officer will guide you."),
    ("arrest_threat", "en", "FINAL NOTICE from {agency}: an arrest warrant has been issued in your name. To avoid arrest, transfer {amount} to the RBI verification account for checking. Call {phone} now."),
    ("arrest_threat", "en", "Your mobile number will be disconnected by TRAI {time} because it was used for illegal activity. Press 9 or call {phone} to speak to the cyber cell."),
    ("arrest_threat", "en", "You are under digital arrest. Keep your camera on and do not leave the room. Your savings must be verified by RBI. Send {amount} to the safe account the officer gives you."),
    ("arrest_threat", "en", "{agency}: your SIM card was used in fraud case {case}. Cooperate on the WhatsApp video call, otherwise a non-bailable warrant will be issued today."),
    ("arrest_threat", "en", "Court summons: you are accused in case {case}. To settle the matter quietly, pay the security deposit of {amount}. Do not discuss this with anyone."),
    ("arrest_threat", "en", "This call is being recorded by {agency}. Your bank account is under investigation. Move all funds to the government safe account so we can clear your name."),
    ("arrest_threat", "hi", "मैं {agency} से बोल रहा हूँ। आपके नाम का पार्सल पकड़ा गया है जिसमें ड्रग्स हैं। केस नंबर {case}। तुरंत वीडियो कॉल पर जुड़ें वरना गिरफ्तारी होगी।"),
    ("arrest_threat", "hi", "आपका आधार मनी लॉन्ड्रिंग केस से जुड़ा है। कॉल मत काटिए और परिवार को कुछ मत बताइए। जांच के लिए {amount} आरबीआई खाते में भेजें।"),
    ("arrest_threat", "hi", "अंतिम सूचना: आपके खिलाफ गिरफ्तारी वारंट जारी हो गया है। बचने के लिए तुरंत {phone} पर संपर्क करें।"),
    ("arrest_threat", "hi", "आप डिजिटल अरेस्ट में हैं। कैमरा चालू रखें और कमरे से बाहर न जाएं। अपने पैसे की जांच के लिए {amount} सुरक्षित खाते में ट्रांसफर करें।"),
    ("arrest_threat", "hi", "{agency}: आपका सिम कार्ड धोखाधड़ी में इस्तेमाल हुआ है। {time} आपका नंबर बंद कर दिया जाएगा। अधिकारी से बात करने के लिए 9 दबाएं।"),
    ("arrest_threat", "hinglish", "Aapke naam ka parcel customs ne pakda hai, usme drugs mile hain. Case {case}. Turant video call join karo warna arrest ho jayega."),
    ("arrest_threat", "hinglish", "Aapka Aadhaar money laundering case me use hua hai. Call mat kaatna aur kisi ko mat batana. {agency} officer se baat karo."),
    ("arrest_threat", "hinglish", "Aap digital arrest me ho. Camera on rakho. Verification ke liye {amount} RBI safe account me abhi transfer karo."),
    ("arrest_threat", "hinglish", "Aapke number pe police complaint darj hui hai. Non bailable warrant aaj nikal jayega, turant {phone} pe call karo."),
    ("arrest_threat", "hinglish", "Mamla court tak nahi jayega agar aap {amount} security deposit abhi bhej do. Ghar walo ko kuch mat batana."),

    # ---------------- kyc: fake KYC / APK ----------------
    ("kyc", "en", "Dear {bank} customer, your account will be blocked today due to pending KYC. Update now: {link}"),
    ("kyc", "en", "Your PAN is not linked. {bank} net banking will be suspended in 24 hours. Click {link} to complete re-KYC."),
    ("kyc", "en", "ALERT: your {bank} account is deactivated. Install the KYC update app from {link} and allow all permissions to restore access."),
    ("kyc", "en", "Your SIM e-KYC has expired. Complete it {time} or your number will stop working. Download {app}: {link}"),
    ("kyc", "en", "Your wallet KYC verification failed. Share the OTP you just received with our executive to avoid suspension."),
    ("kyc", "en", "Dear user, {amount} reward points on your credit card expire today. Redeem by updating KYC at {link}"),
    ("kyc", "en", "{bank}: your debit card is blocked. To unblock, install {app} and tell the code on your screen to our support officer."),
    ("kyc", "en", "Aadhaar-bank link failed. Your LPG subsidy and pension will stop. Verify now at {link} using your card details."),
    ("kyc", "hi", "प्रिय ग्राहक, केवाईसी अपडेट न होने के कारण आपका {bank} खाता आज बंद हो जाएगा। तुरंत अपडेट करें: {link}"),
    ("kyc", "hi", "आपका पैन कार्ड लिंक नहीं है। 24 घंटे में नेट बैंकिंग बंद हो जाएगी। री-केवाईसी के लिए {link} पर क्लिक करें।"),
    ("kyc", "hi", "आपका सिम केवाईसी समाप्त हो गया है। {time} तक ई-केवाईसी पूरा करें वरना सेवा बंद। ऐप डाउनलोड करें: {link}"),
    ("kyc", "hi", "आपका डेबिट कार्ड ब्लॉक है। चालू करने के लिए यह ऐप इंस्टॉल करें और स्क्रीन पर आया कोड हमारे अधिकारी को बताएं।"),
    ("kyc", "hinglish", "Dear customer aapka {bank} account aaj block ho jayega, KYC pending hai. Abhi update karo {link}"),
    ("kyc", "hinglish", "Aapka PAN link nahi hai, netbanking band ho jayegi. Re-KYC ke liye ye app install karo {link} aur sab permission allow karo."),
    ("kyc", "hinglish", "Sir aapka KYC expire ho gaya hai, OTP batao to hum update kar denge, warna account freeze ho jayega."),
    ("kyc", "hinglish", "Aapki pension band ho jayegi, Aadhaar link nahi hai. Is link pe card details daal ke verify karo {link}"),

    # ---------------- task_job: task / part-time job ----------------
    ("task_job", "en", "Hi! We are hiring part-time. Like YouTube videos and earn {small} per task, up to {amount} daily. Contact us on Telegram: {link}"),
    ("task_job", "en", "Work from home offer: rate products on {company} and get paid every day. Reply YES to join our team."),
    ("task_job", "en", "Congratulations, you completed 3 tasks and earned {small}. To unlock your commission, complete the prepaid task of {amount}."),
    ("task_job", "en", "Your earnings of {amount} are frozen. Pay {amount2} to upgrade your level and withdraw. Higher task, higher commission."),
    ("task_job", "en", "HR from {company}: daily income of 3,000 to 8,000 rupees, no experience needed, only 15 minutes a day. WhatsApp {phone}"),
    ("task_job", "en", "Join our VIP task group. Today's merchant task gives {pct} return. Deposit {amount} to start earning."),
    ("task_job", "en", "Your task account balance is {amount}. One final combination task of {amount2} is required before withdrawal."),
    ("task_job", "en", "Earn money by writing Google Maps reviews. {small} per review, paid instantly to your UPI. Message our mentor on Telegram."),
    ("task_job", "hi", "पार्ट टाइम जॉब: यूट्यूब वीडियो लाइक करें और रोज़ {amount} तक कमाएं। टेलीग्राम पर जुड़ें: {link}"),
    ("task_job", "hi", "आपका कमीशन {amount} रुका हुआ है। निकालने के लिए {amount2} का प्रीपेड टास्क पूरा करें।"),
    ("task_job", "hi", "घर बैठे काम करें, रोज़ाना भुगतान। सिर्फ 15 मिनट रोज़। व्हाट्सएप करें {phone}"),
    ("task_job", "hi", "बधाई हो! आपने 3 टास्क पूरे किए और {small} कमाए। अगला लेवल खोलने के लिए {amount} जमा करें।"),
    ("task_job", "hinglish", "Part time job hai, sirf videos like karo aur roz {amount} tak kamao. Telegram pe join karo {link}"),
    ("task_job", "hinglish", "Aapka commission {amount} lock hai, withdraw ke liye {amount2} ka prepaid task karo."),
    ("task_job", "hinglish", "Ghar baithe kaam, daily payment. 3 task complete karo aur {small} turant milega."),
    ("task_job", "hinglish", "Aapka level upgrade pending hai, {amount2} bharo to {amount} ka payout aaj hi milega."),

    # ---------------- trading_tip: investment / trading group ----------------
    ("trading_tip", "en", "SEBI registered expert: {stock} will give {pct} return this week. Join our VIP WhatsApp group: {link}"),
    ("trading_tip", "en", "Guaranteed {pct} profit in IPO allotment. Pay {amount} to our institutional account for pre-allotment."),
    ("trading_tip", "en", "Your trading account shows a profit of {amount}. Pay {amount2} as service tax to withdraw."),
    ("trading_tip", "en", "Stock tip of the day: buy {stock} at open. Our members made {pct} last month. Limited seats in the premium group."),
    ("trading_tip", "en", "Crypto arbitrage: double your money in {days} days. Minimum investment {amount}. Withdraw any time."),
    ("trading_tip", "en", "Exclusive block deal for our students only. Transfer {amount} to the company account and the shares will be credited tomorrow."),
    ("trading_tip", "hi", "सेबी रजिस्टर्ड एक्सपर्ट: {stock} इस हफ्ते {pct} रिटर्न देगा। हमारे वीआईपी ग्रुप से जुड़ें: {link}"),
    ("trading_tip", "hi", "आईपीओ में गारंटीड मुनाफा। प्री-अलॉटमेंट के लिए {amount} कंपनी खाते में जमा करें।"),
    ("trading_tip", "hi", "आपके ट्रेडिंग खाते में {amount} का प्रॉफिट है। निकालने के लिए {amount2} टैक्स भरें।"),
    ("trading_tip", "hinglish", "Bhai {stock} me {pct} pakka return hai is week, VIP group join kar lo {link}"),
    ("trading_tip", "hinglish", "IPO me guaranteed allotment milega, {amount} institutional account me aaj hi bhejo."),
    ("trading_tip", "hinglish", "Aapka profit {amount} ho gaya hai, withdrawal ke liye pehle {amount2} fees bharo."),

    # ---------------- refund: refund / QR / bill tricks ----------------
    ("refund", "en", "Dear consumer, your electricity will be disconnected {time} because last month's bill is not updated. Call our officer {phone} immediately."),
    ("refund", "en", "Your refund of {amount} is approved. Scan the QR code to receive the money in your account."),
    ("refund", "en", "You have received a payment request of {amount}. Enter your UPI PIN to accept the refund."),
    ("refund", "en", "{company} order cancelled. Refund of {amount} pending. Call customer care {phone} and install {app} for processing."),
    ("refund", "en", "Sorry, I sent {amount} to your number by mistake. Please return it to this UPI ID: {upi}"),
    ("refund", "en", "Your gas connection will be cut {time} due to pending KYC of the bill. Pay {small} verification fee at {link}"),
    ("refund", "hi", "प्रिय उपभोक्ता, पिछले महीने का बिल अपडेट नहीं होने से {time} बिजली काट दी जाएगी। तुरंत {phone} पर कॉल करें।"),
    ("refund", "hi", "आपका {amount} का रिफंड मंजूर हो गया है। पैसे पाने के लिए क्यूआर कोड स्कैन करें।"),
    ("refund", "hi", "पैसा प्राप्त करने के लिए अपना यूपीआई पिन डालें। रिफंड राशि {amount}।"),
    ("refund", "hinglish", "Aapki bijli aaj raat kat jayegi, bill update nahi hua. Electricity officer {phone} pe turant call karo."),
    ("refund", "hinglish", "Aapka refund {amount} approve ho gaya, paisa lene ke liye QR scan karo aur PIN dalo."),
    ("refund", "hinglish", "Galti se aapke number pe {amount} bhej diya, please is UPI pe wapas kar do {upi}"),

    # ---------------- normal: everyday messages and look-alikes ----------------
    ("normal", "en", "{otp} is your OTP for a transaction of {amount} at {company}. Valid for 5 minutes. Do not share it with anyone. -{bank}"),
    ("normal", "en", "Rs {amount} debited from a/c XX{acct} on {date} to VPA {upi}. UPI Ref {ref}. Not you? Call 1800-111-109 -{bank}"),
    ("normal", "en", "Your a/c XX{acct} is credited with INR {amount} on {date} by UPI from {name}. Ref {ref}. -{bank}"),
    ("normal", "en", "Dear Customer, periodic KYC update is due for your {bank} account. Please visit your home branch with ID proof. We never ask for OTP or PIN on call."),
    ("normal", "en", "Your {courier} shipment {ref} is out for delivery today. Please keep your phone reachable."),
    ("normal", "en", "Refund of {amount} for your {company} order has been processed to your original payment method. It may take 3 to 5 working days."),
    ("normal", "en", "Hi {name}, your interview with {company} HR is scheduled on {date} at 11 AM at our Pune office. Please bring your resume."),
    ("normal", "en", "Trade executed: bought 10 shares of {stock} at the market price. The contract note has been sent to your email. -{broker}"),
    ("normal", "en", "MSEDCL: bill of Rs {amount} for consumer no. {ref} is due on {date}. Pay on the app or website to avoid a late fee."),
    ("normal", "en", "Cyber Dost: police never arrest anyone over a video call. If someone threatens you, hang up and report it at 1930."),
    ("normal", "en", "RBI Kehta Hai: never share OTP, PIN or CVV. Banks never ask you to move money to a safe account."),
    ("normal", "en", "Recharge of Rs 299 successful. Validity 28 days. Thank you for choosing Jio."),
    ("normal", "en", "Society maintenance of Rs {amount} for {month} is due. Please pay to the society account before the 10th."),
    ("normal", "en", "Salary of Rs {amount} credited to your account XX{acct}. -{bank}"),
    ("normal", "en", "Your appointment with Dr. Kulkarni is confirmed for {date}, 6 PM. Reply C to cancel."),
    ("normal", "en", "Happy birthday {name}! Party at our place at 8, don't be late."),
    ("normal", "en", "Reached the station, will call you after dinner."),
    ("normal", "en", "Your {company} order has been delivered. Rate your experience in the app."),
    ("normal", "en", "Your IPO application for {stock} is received. Allotment status will be shared on {date}. -{broker}"),
    ("normal", "en", "You earned {small} cashback on your last bill payment. It has been added to your wallet."),
    ("normal", "en", "Your SIM e-KYC is complete. No further action is needed. Never share OTP with anyone claiming to be from TRAI."),
    ("normal", "en", "Parcel from your relative is held at the post office. Collect it with ID proof between 10 AM and 5 PM."),
    ("normal", "en", "Hey {name}, can you send me the notes from today's class?"),
    ("normal", "en", "Electricity supply will be off on {date} from 10 AM to 2 PM for maintenance in your area. -MSEDCL"),
    ("normal", "hi", "आपका ओटीपी {otp} है। इसे किसी के साथ साझा न करें। -{bank}"),
    ("normal", "hi", "{relation}, सब्जी के लिए {small} भेज दो, शाम को लौटा दूँगी।"),
    ("normal", "hi", "आपका बिजली बिल {amount} देय है। अंतिम तिथि {date} है।"),
    ("normal", "hi", "पुलिस कभी वीडियो कॉल पर गिरफ्तार नहीं करती। धोखाधड़ी की शिकायत 1930 पर करें।"),
    ("normal", "hi", "आपका पार्सल आज डिलीवर होगा। कृपया फोन चालू रखें।"),
    ("normal", "hi", "कल सुबह 10 बजे मीटिंग है, समय पर आ जाना।"),
    ("normal", "hi", "प्रिय ग्राहक, आपके खाते का केवाईसी अपडेट होना है। कृपया अपनी शाखा में पहचान पत्र के साथ आएं। बैंक कभी ओटीपी नहीं मांगता।"),
    ("normal", "hi", "आपके खाते में {amount} जमा हुए हैं। -{bank}"),
    ("normal", "hi", "{relation}, घर पहुँच गया हूँ, खाना खा लिया।"),
    ("normal", "hi", "आपका रिफंड {amount} आपके खाते में भेज दिया गया है। 3 से 5 दिन लग सकते हैं।"),
    ("normal", "hinglish", "Bhai kal match dekhne chalega? 7 baje milte hain."),
    ("normal", "hinglish", "{relation} main ghar pahunch gaya, khana kha liya."),
    ("normal", "hinglish", "Didi rent ke {amount} bhej diye hain, check kar lo."),
    ("normal", "hinglish", "Sir aapka order out for delivery hai, ghar pe rahiye."),
    ("normal", "hinglish", "Office me aaj late hoga, tum kha lena."),
    ("normal", "hinglish", "Plumber ko {small} de dena, kaam ho gaya hai."),
    ("normal", "hinglish", "Kal se online class 9 baje start hogi, link group me daal diya hai."),
    ("normal", "hinglish", "Mandir ke liye {small} chanda dena hai, society group me details hain."),
    ("normal", "hinglish", "Aapka OTP {otp} hai, kisi ke saath share mat karna. -{bank}"),
    ("normal", "hinglish", "Bhaiya paise mil gaye, thank you. Shaam ko call karta hoon."),
]

LINKS = ["bit.ly/3xK9pQ", "tinyurl.com/kyc-upd8", "rbi-verify.in/kyc", "t.me/earn_daily_vip", "wa.me/918824551290",
         "sbi-kyc-update.com", "hdfc-netbank-verify.net", "cutt.ly/Rk7Tq", "is.gd/Qx2kL", "vip-trade-group.in/join"]


def _amount(r: random.Random, lo: int, hi: int) -> str:
    v = r.randrange(lo, hi)
    v = round(v, -2) if r.random() < 0.6 else v
    s = f"{v:,}"
    return r.choice([f"Rs {s}", f"Rs.{s}", f"₹{s}", f"INR {s}", f"{s} rupees", f"₹ {s}"])


def _fill(text: str, lang: str, r: random.Random) -> str:
    def slot(m: re.Match) -> str:
        k = m.group(1)
        if lang == "hi" and k in HI_FILL and r.random() < 0.7:
            return r.choice(HI_FILL[k])
        if k in FILL:
            return r.choice(FILL[k])
        if k == "amount":
            return _amount(r, 1_000, 200_000)
        if k == "amount2":
            return _amount(r, 2_000, 90_000)
        if k == "small":
            return _amount(r, 50, 600)
        if k == "link":
            return r.choice(LINKS)
        if k == "phone":
            return r.choice(["+91 ", "", "0"]) + f"{r.choice('6789')}{r.randrange(10**8, 10**9)}"
        if k == "case":
            return r.choice(["CR/2026/", "FIR No. ", "Case ID "]) + str(r.randrange(1000, 99999))
        if k == "upi":
            return f"{r.choice(['refund.desk', 'help.center', 'rahul.k', 'cs.support'])}{r.randrange(10, 99)}@{r.choice(['ybl', 'okaxis', 'paytm', 'ibl'])}"
        if k == "otp":
            return f"{r.randrange(10**5, 10**6)}"
        if k == "acct":
            return f"{r.randrange(1000, 9999)}"
        if k == "ref":
            return f"{r.randrange(10**11, 10**12)}"
        if k == "date":
            return f"{r.randrange(1, 29):02d}-{r.choice(['10', '11', '12'])}-26"
        raise KeyError(k)
    return re.sub(r"\{(\w+)\}", slot, text)


LOOKALIKE = str.maketrans({"o": "0", "i": "1", "a": "@", "e": "3", "s": "$"})
EMOJI = ["🚨", "⚠️", "✅", "💰", "📦", "🙏", "👉", "🔥"]


def _vary(text: str, tag: str, r: random.Random) -> str:
    """Surface changes real messages have: casing, emoji, spacing, scammers' look-alike letters."""
    if r.random() < 0.08:
        text = text.upper()
    if tag != "normal" and r.random() < 0.06:
        words = text.split(" ")
        i = r.randrange(len(words))
        words[i] = words[i].translate(LOOKALIKE)
        text = " ".join(words)
    if r.random() < 0.12:
        text = f"{r.choice(EMOJI)} {text}" if r.random() < 0.5 else f"{text} {r.choice(EMOJI)}"
    if r.random() < 0.08:
        text = text.replace(". ", ".  ").replace(", ", " , ")
    if r.random() < 0.05:
        text = text.replace(" ", "\n", 1)
    return text


def generate(seed: int = 7, per_scam_template: int = 30, per_normal_template: int = 60) -> pd.DataFrame:
    r = random.Random(seed)
    rows = []
    for tid, (tag, lang, tpl) in enumerate(TEMPLATES):
        for _ in range(per_normal_template if tag == "normal" else per_scam_template):
            rows.append({"text": _vary(_fill(tpl, lang, r), tag, r), "tag": tag, "lang": lang,
                         "template_id": tid, "synthetic": True})
    return pd.DataFrame(rows).drop_duplicates("text").reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    df = generate(a.seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False, encoding="utf-8")
    print(f"{len(df):,} messages from {df.template_id.nunique()} templates -> {a.out}")
    print(df.groupby(["tag", "lang"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main()

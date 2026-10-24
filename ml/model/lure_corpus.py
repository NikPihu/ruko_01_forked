"""Synthetic SMS corpus for the on-device lure classifier -> ml/data/lure_texts.csv

    PYTHONPATH=backend;ml;data python -m model.lure_corpus

Written by the team from public I4C / RBI / NPCI / DoT advisories, with LLM help, and labelled
synthetic (deck appendix B). Scam scripts are fluent on purpose: AI-written lures have no typos, so
the model must learn intent (pay or install now, secrecy, authority, unlockable earnings, a fee
before money arrives), not style.

Classes (lure-0.2): the five scam types the playbooks know (`arrest_threat`, `kyc`, `task_job`,
`trading_tip`, `refund`), `other_scam` (parcel/customs, power or gas cut-off, lottery, loan fee,
society bill clone, job registration fee, sextortion, e-challan, insurance bonus, wrong-UPI
"please return", crypto / gift card, fake donation) and `normal`. `normal` is most of the corpus
(at least 55%): everyday traffic (OTPs, bank alerts, UPI receipts, deliveries, recharges, bills,
doctor / school / society notices, family and friends chat, promos) AND look-alikes that share the
scam words (real KYC reminders, real refunds, police and RBI awareness SMS, real job and broker
messages, real e-challans with no link to pay).

Every row keeps its template id, so evaluation can hold out whole templates (unseen phrasings).
Phone numbers, links and UPI IDs are made up (links use reserved `.example` / `.test` names on
both sides, so the domain itself is not a clue). Names are generic first names only.
"""
from __future__ import annotations

import argparse
import random
import re
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "lure_texts.csv"
SCAM_TAGS = ("arrest_threat", "kyc", "task_job", "trading_tip", "refund", "other_scam")
CLASSES = (*SCAM_TAGS, "normal")

FILL: dict[str, list[str]] = {
    "name": ["Rahul", "Priya", "Meena ji", "Sunita", "Amit", "Rohan", "Neha", "Arjun", "Kavita", "Imran",
             "Deepak", "Anjali", "Suresh", "Pooja", "Vikram", "Farah", "Ravi", "Sneha", "Manoj", "Geeta",
             "Karan", "Ritu", "Ajay", "Swati"],
    "bank": ["SBI", "HDFC Bank", "ICICI Bank", "Axis Bank", "PNB", "Kotak Bank", "Bank of Baroda", "Canara Bank",
             "Union Bank", "IDFC First Bank"],
    "agency": ["CBI", "Mumbai Cyber Crime", "Narcotics Control Bureau", "ED", "Customs", "TRAI",
               "Delhi Police Crime Branch", "RBI Vigilance", "Income Tax Department", "Cyber Cell"],
    "city": ["Mumbai", "Delhi", "Kolkata", "Chennai", "Hyderabad", "Bengaluru", "Pune", "Lucknow", "Jaipur", "Indore"],
    "company": ["Amazon", "Flipkart", "Meesho", "YouTube", "Google Maps", "Myntra", "Swiggy", "Zomato", "Ajio", "Nykaa"],
    "courier": ["FedEx", "DHL", "Blue Dart", "India Post", "Delhivery", "Ecom Express", "DTDC"],
    "stock": ["SUZLON", "IREDA", "Tata Power", "Yes Bank", "an upcoming IPO", "RVNL", "Adani Green", "IRFC", "NHPC"],
    "app": ["AnyDesk", "the RBI KYC app", "QuickSupport", "the YONO update", "RustDesk", "the Aadhaar Seva app",
            "the Customer Support APK", "the bank verification app"],
    "time": ["tonight 9:30 PM", "within 2 hours", "today itself", "before 6 PM", "in 30 minutes", "by midnight"],
    "pct": ["20%", "35%", "40%", "300%", "15% weekly", "double", "5% daily", "60%"],
    "days": ["2", "3", "7", "10", "15"],
    "broker": ["Zerodha", "Groww", "Upstox", "Angel One", "Dhan"],
    "month": ["October", "November", "December", "January"],
    "relation": ["Mummy", "Papa", "Didi", "Bhaiya", "Beta", "Chachu", "Mausi"],
    "clock": ["7 PM", "8:30 PM", "10 AM", "6:15 PM", "11:30 AM", "9 PM", "4 PM"],
    "day": ["tomorrow", "Monday", "Saturday", "Sunday", "Friday", "this weekend"],
    "item": ["milk", "vegetables", "medicines", "the cake", "school books", "atta", "bread and eggs", "fruits"],
    "shop": ["DMart", "Reliance Smart", "Apollo Pharmacy", "More Supermarket", "Croma", "BigBasket", "Blinkit",
             "Zepto", "Shree Ganesh Kirana", "Café Coffee Day"],
    "operator": ["Jio", "Airtel", "Vi", "BSNL"],
    "clinic": ["City Care Clinic", "Sai Hospital", "Lifeline Diagnostics", "Sunrise Dental", "Dr. Kulkarni's clinic",
               "Apex Eye Care"],
    "school": ["Sunrise Public School", "Green Valley School", "Little Flowers School", "Vidya Niketan"],
    "society": ["Green Park Society", "Shanti Nagar CHS", "Lake View Apartments", "Sai Krupa Residency"],
    "insurer": ["LIC", "HDFC Life", "SBI Life", "Star Health", "ICICI Lombard"],
    "crypto": ["USDT", "Bitcoin", "crypto", "TRX"],
    "gift": ["Amazon gift cards", "Google Play gift cards", "Apple gift cards"],
    "cause": ["flood relief", "earthquake victims", "a child's cancer surgery", "the gaushala", "army welfare",
              "cyclone relief"],
    "prize": ["KBC lucky draw", "Jio lucky draw", "Amazon anniversary draw", "Tata Motors lucky draw",
              "Diwali bumper lottery"],
    "loanapp": ["QuickCash", "RupeeNow", "InstaLoan", "CashBuddy", "LoanSathi"],
    "airline": ["IndiGo", "Air India", "Akasa Air", "SpiceJet"],
    "plan": ["Rs 299", "Rs 239", "Rs 719", "Rs 155", "Rs 666", "Rs 349"],
    "ott": ["Netflix", "Hotstar", "Prime Video", "SonyLIV"],
}
HI_FILL = {
    "name": ["राहुल", "प्रिया", "सुनीता", "अमित", "नेहा", "रवि", "गीता", "मनोज", "पूजा", "दीपक"],
    "agency": ["सीबीआई", "मुंबई साइबर क्राइम", "नारकोटिक्स ब्यूरो", "ईडी", "कस्टम विभाग", "ट्राई", "आयकर विभाग"],
    "bank": ["एसबीआई", "एचडीएफसी बैंक", "पीएनबी", "बैंक ऑफ बड़ौदा", "एक्सिस बैंक", "केनरा बैंक"],
    "time": ["आज रात 9:30 बजे", "2 घंटे में", "आज ही", "शाम 6 बजे तक", "30 मिनट में"],
    "relation": ["मम्मी", "पापा", "दीदी", "भैया", "बेटा", "चाचा जी"],
    "clock": ["शाम 7 बजे", "सुबह 10 बजे", "रात 9 बजे", "दोपहर 2 बजे", "शाम 5 बजे"],
    "day": ["कल", "सोमवार", "शनिवार", "रविवार", "परसों"],
    "item": ["दूध", "सब्ज़ी", "दवाई", "आटा", "फल", "किताबें"],
    "city": ["मुंबई", "दिल्ली", "कोलकाता", "पुणे", "लखनऊ", "जयपुर"],
    "month": ["अक्टूबर", "नवंबर", "दिसंबर"],
}
HINGLISH_FILL = {
    "day": ["kal", "Monday", "Sunday", "parso", "is weekend"],
    "item": ["doodh", "sabzi", "dawai", "atta", "fruits", "anda bread"],
    "time": ["aaj raat 9 baje", "2 ghante me", "aaj hi", "shaam 6 baje tak", "30 minute me"],
    "clock": ["7 baje", "shaam 6 baje", "subah 10 baje", "raat 9 baje", "dopahar 2 baje"],
}

# Slots: every key of FILL, plus the generated ones in _fill(): {amount} {amount2} {small} {link}
# {nlink} {phone} {case} {upi} {otp} {acct} {ref} {date} {vehicle} {pnr} {order} {hours}
T: dict[str, dict[str, list[str]]] = {
    # ---------------- arrest_threat: "digital arrest", fake police / court / TRAI ----------------
    "arrest_threat": {
        "en": [
            "This is {agency}. A parcel in your name containing illegal drugs was seized at {city} airport. Case {case}. Join the video call at {link} immediately or a warrant will be issued.",
            "Your Aadhaar number is linked to a money laundering case ({case}). Do not disconnect the call and do not inform your family. The {agency} officer will guide you.",
            "FINAL NOTICE from {agency}: an arrest warrant has been issued in your name. To avoid arrest, transfer {amount} to the RBI verification account for checking. Call {phone} now.",
            "Your mobile number will be disconnected by TRAI {time} because it was used for illegal activity. Press 9 or call {phone} to speak to the cyber cell.",
            "You are under digital arrest. Keep your camera on and do not leave the room. Your savings must be verified by RBI. Send {amount} to the safe account the officer gives you.",
            "{agency}: your SIM card was used in fraud case {case}. Cooperate on the WhatsApp video call, otherwise a non-bailable warrant will be issued today.",
            "Court summons: you are accused in case {case}. To settle the matter quietly, pay the security deposit of {amount}. Do not discuss this with anyone.",
            "This call is being recorded by {agency}. Your bank account is under investigation. Move all funds to the government safe account so we can clear your name.",
            "Official notice: 17 complaints are registered against your Aadhaar in {city}. Report to the investigating officer on video call within {hours} hours to avoid custody.",
            "Dear citizen, your name has appeared in a human trafficking and hawala case. This is strictly confidential under the Official Secrets Act. Speak only to {agency} on {phone}.",
            "Your bank account was used to receive proceeds of crime. As per Supreme Court order, deposit {amount} for fund verification; it will be refunded after the inquiry.",
            "We have a CCTV record and an FIR ({case}) against you. Stay on this call with the inspector. If you hang up, local police will arrive at your house within the hour.",
            "{agency} has frozen your accounts in case {case}. To unfreeze them, pay the verification charge of {amount2} to the account shared by the senior officer.",
            "Your son has been detained by {city} police in a rape case. Pay {amount} now to settle it before the FIR is filed. Do not call anyone else.",
            "Customs notice: a package booked with your ID holds 5 fake passports and MDMA. Contact {agency} at {phone} within {hours} hours, or your arrest will be processed.",
            "Attention: an e-warrant ({case}) has been generated against your PAN for tax evasion. Settle the penalty of {amount} online today to stop the arrest: {link}",
            "This is the investigating inspector from {agency}. You must remain in isolation on Skype until verification is done. Telling your family will be treated as obstruction of justice.",
            "Your phone number appears in a terror funding investigation. You are ordered to join the National Security video hearing at {link} within {hours} hours.",
        ],
        "hi": [
            "मैं {agency} से बोल रहा हूँ। आपके नाम का पार्सल पकड़ा गया है जिसमें ड्रग्स हैं। केस नंबर {case}। तुरंत वीडियो कॉल पर जुड़ें वरना गिरफ्तारी होगी।",
            "आपका आधार मनी लॉन्ड्रिंग केस से जुड़ा है। कॉल मत काटिए और परिवार को कुछ मत बताइए। जांच के लिए {amount} आरबीआई खाते में भेजें।",
            "अंतिम सूचना: आपके खिलाफ गिरफ्तारी वारंट जारी हो गया है। बचने के लिए तुरंत {phone} पर संपर्क करें।",
            "आप डिजिटल अरेस्ट में हैं। कैमरा चालू रखें और कमरे से बाहर न जाएं। अपने पैसे की जांच के लिए {amount} सुरक्षित खाते में ट्रांसफर करें।",
            "{agency}: आपका सिम कार्ड धोखाधड़ी में इस्तेमाल हुआ है। {time} आपका नंबर बंद कर दिया जाएगा। अधिकारी से बात करने के लिए 9 दबाएं।",
            "आपके बैंक खाते में अपराध का पैसा आया है। सुप्रीम कोर्ट के आदेश से {amount} जांच खाते में जमा करें, जांच के बाद लौटा दिया जाएगा।",
            "आपके बेटे को {city} पुलिस ने हिरासत में लिया है। मामला रफा-दफा करने के लिए अभी {amount} भेजिए, किसी और को फोन मत कीजिए।",
            "कोर्ट का नोटिस: केस {case} में आप आरोपी हैं। मामला चुपचाप निपटाने के लिए {amount} सुरक्षा राशि जमा करें।",
            "यह कॉल {agency} द्वारा रिकॉर्ड की जा रही है। जांच पूरी होने तक वीडियो कॉल पर बने रहें, किसी को बताना कानूनी अपराध माना जाएगा।",
            "आपके पैन पर टैक्स चोरी का ई-वारंट जारी हुआ है। गिरफ्तारी रोकने के लिए आज ही {amount} जुर्माना भरें: {link}",
            "आपके नाम से बुक पार्सल में नकली पासपोर्ट मिले हैं। {hours} घंटे के अंदर {phone} पर {agency} से संपर्क करें वरना गिरफ्तारी होगी।",
            "आपके खाते {agency} ने फ्रीज़ कर दिए हैं। खाते चालू कराने के लिए अधिकारी द्वारा दिए खाते में {amount2} सत्यापन शुल्क भेजें।",
        ],
        "hinglish": [
            "Aapke naam ka parcel customs ne pakda hai, usme drugs mile hain. Case {case}. Turant video call join karo warna arrest ho jayega.",
            "Aapka Aadhaar money laundering case me use hua hai. Call mat kaatna aur kisi ko mat batana. {agency} officer se baat karo.",
            "Aap digital arrest me ho. Camera on rakho. Verification ke liye {amount} RBI safe account me abhi transfer karo.",
            "Aapke number pe police complaint darj hui hai. Non bailable warrant aaj nikal jayega, turant {phone} pe call karo.",
            "Mamla court tak nahi jayega agar aap {amount} security deposit abhi bhej do. Ghar walo ko kuch mat batana.",
            "Aapke bank account me hawala ka paisa aaya hai. Supreme Court order ke hisaab se {amount} verification ke liye jama karo, baad me wapas milega.",
            "Aapke bete ko {city} police ne pakda hai. Abhi {amount} bhejo to FIR nahi hogi, kisi aur ko phone mat karna.",
            "Ye call {agency} record kar rahi hai. Jab tak inquiry khatam nahi hoti video call pe hi rehna, family ko batana obstruction mana jayega.",
            "Aapke PAN pe tax evasion ka e-warrant nikla hai. Arrest rokna hai to aaj hi {amount} penalty bharo {link}",
            "Aapke ID se book hue parcel me fake passport mile hain. {hours} ghante me {agency} ko {phone} pe contact karo warna giraftari hogi.",
            "Aapke saare account {agency} ne freeze kar diye hain. Unfreeze karwana hai to officer ke diye account me {amount2} verification charge bhejo.",
            "TRAI aapka number {time} band kar dega kyunki illegal activity me use hua hai. Cyber cell se baat karne ke liye 9 dabao.",
        ],
    },
    # ---------------- kyc: fake KYC / account block / APK / OTP ----------------
    "kyc": {
        "en": [
            "Dear {bank} customer, your account will be blocked today due to pending KYC. Update now: {link}",
            "Your PAN is not linked. {bank} net banking will be suspended in 24 hours. Click {link} to complete re-KYC.",
            "ALERT: your {bank} account is deactivated. Install the KYC update app from {link} and allow all permissions to restore access.",
            "Your SIM e-KYC has expired. Complete it {time} or your number will stop working. Download {app}: {link}",
            "Your wallet KYC verification failed. Share the OTP you just received with our executive to avoid suspension.",
            "Dear user, {amount} reward points on your credit card expire today. Redeem by updating KYC at {link}",
            "{bank}: your debit card is blocked. To unblock, install {app} and tell the code on your screen to our support officer.",
            "Aadhaar-bank link failed. Your LPG subsidy and pension will stop. Verify now at {link} using your card details.",
            "Your {bank} YONO account is locked due to incomplete documents. Upload your Aadhaar and PAN at {link} within {hours} hours.",
            "Important: as per new RBI guidelines your account needs biometric re-verification. Download {app} and keep the screen shared during the process.",
            "{bank} credit card limit upgrade approved. Confirm your card number, expiry and CVV at {link} to activate it today.",
            "Your Paytm wallet will be closed tonight for incomplete KYC. Our executive will call you; read out the 6-digit code you receive to complete it.",
            "Dear customer, your account has been put on hold. Your mobile number is not updated with {bank}. Update immediately: {link}",
            "Your electricity-linked Aadhaar KYC is pending, so your DBT payments are on hold. Fill the form at {link} with your bank PIN.",
            "Last reminder: your {bank} account will be frozen at midnight. Our KYC officer is waiting on {phone}; keep your debit card ready.",
            "Your demat KYC is non-compliant. Trading will be stopped from tomorrow. Revalidate with net banking login at {link}",
            "Your UPI ID will be deactivated in 2 hours because KYC is incomplete. Approve the request in your UPI app to verify.",
            "Dear pensioner, your life certificate has expired. Submit it online at {link} with your Aadhaar OTP or the pension will stop this month.",
        ],
        "hi": [
            "प्रिय ग्राहक, केवाईसी अपडेट न होने के कारण आपका {bank} खाता आज बंद हो जाएगा। तुरंत अपडेट करें: {link}",
            "आपका पैन कार्ड लिंक नहीं है। 24 घंटे में नेट बैंकिंग बंद हो जाएगी। री-केवाईसी के लिए {link} पर क्लिक करें।",
            "आपका सिम केवाईसी समाप्त हो गया है। {time} तक ई-केवाईसी पूरा करें वरना सेवा बंद। ऐप डाउनलोड करें: {link}",
            "आपका डेबिट कार्ड ब्लॉक है। चालू करने के लिए यह ऐप इंस्टॉल करें और स्क्रीन पर आया कोड हमारे अधिकारी को बताएं।",
            "आपकी पेंशन रुक जाएगी क्योंकि जीवन प्रमाण पत्र समाप्त हो गया है। आधार ओटीपी के साथ {link} पर तुरंत जमा करें।",
            "आपके क्रेडिट कार्ड के {amount} रिवॉर्ड पॉइंट आज खत्म हो रहे हैं। केवाईसी अपडेट करके {link} पर रिडीम करें।",
            "आरबीआई के नए नियम के अनुसार आपके खाते का दोबारा सत्यापन जरूरी है। ऐप डाउनलोड करें और प्रक्रिया के दौरान स्क्रीन शेयर रखें।",
            "आपका यूपीआई आईडी 2 घंटे में बंद हो जाएगा। केवाईसी पूरा करने के लिए अपने ऐप में आया अनुरोध स्वीकार करें।",
            "{bank}: आपका खाता होल्ड पर है क्योंकि मोबाइल नंबर अपडेट नहीं है। तुरंत अपडेट करें: {link}",
            "आपका वॉलेट केवाईसी फेल हो गया है। खाता बंद होने से बचाने के लिए अभी आया ओटीपी हमारे प्रतिनिधि को बताएं।",
            "अंतिम चेतावनी: आज रात आपका {bank} खाता फ्रीज़ हो जाएगा। केवाईसी अधिकारी {phone} पर इंतज़ार कर रहे हैं, डेबिट कार्ड तैयार रखें।",
            "आपकी एलपीजी सब्सिडी रुक गई है क्योंकि आधार-बैंक लिंक फेल है। कार्ड की जानकारी डालकर {link} पर सत्यापित करें।",
        ],
        "hinglish": [
            "Dear customer aapka {bank} account aaj block ho jayega, KYC pending hai. Abhi update karo {link}",
            "Aapka PAN link nahi hai, netbanking band ho jayegi. Re-KYC ke liye ye app install karo {link} aur sab permission allow karo.",
            "Sir aapka KYC expire ho gaya hai, OTP batao to hum update kar denge, warna account freeze ho jayega.",
            "Aapki pension band ho jayegi, Aadhaar link nahi hai. Is link pe card details daal ke verify karo {link}",
            "Aapka SIM KYC expire ho gaya hai, {time} update nahi kiya to number band. {app} download karo {link}",
            "Aapka debit card block hai. Unblock ke liye app install karo aur screen pe jo code aaye wo hamare officer ko batao.",
            "Credit card ke {amount} reward points aaj expire ho rahe hain, KYC update karke redeem karo {link}",
            "Aapka UPI ID 2 ghante me deactivate ho jayega, KYC verify karne ke liye app me aayi request approve karo.",
            "Bank ka naya rule hai, account ka video KYC karna padega. App download karo aur process ke time screen share on rakho.",
            "Last warning: aaj raat aapka {bank} account freeze ho jayega. KYC officer {phone} pe wait kar rahe hain, card ready rakho.",
            "Aapka wallet KYC fail ho gaya hai, account band na ho isliye abhi aaya OTP hamare executive ko bata do.",
            "Aapka demat KYC incomplete hai, kal se trading band. Net banking login karke {link} pe revalidate karo.",
        ],
    },
    # ---------------- task_job: task / part-time job / prepaid task ----------------
    "task_job": {
        "en": [
            "Hi! We are hiring part-time. Like YouTube videos and earn {small} per task, up to {amount} daily. Contact us on Telegram: {link}",
            "Work from home offer: rate products on {company} and get paid every day. Reply YES to join our team.",
            "Congratulations, you completed 3 tasks and earned {small}. To unlock your commission, complete the prepaid task of {amount}.",
            "Your earnings of {amount} are frozen. Pay {amount2} to upgrade your level and withdraw. Higher task, higher commission.",
            "HR from {company}: daily income of 3,000 to 8,000 rupees, no experience needed, only 15 minutes a day. WhatsApp {phone}",
            "Join our VIP task group. Today's merchant task gives {pct} return. Deposit {amount} to start earning.",
            "Your task account balance is {amount}. One final combination task of {amount2} is required before withdrawal.",
            "Earn money by writing Google Maps reviews. {small} per review, paid instantly to your UPI. Message our mentor on Telegram.",
            "Hello {name}, I am a recruiter from a digital marketing agency. We pay {small} for each hotel you rate. Interested? Reply 1.",
            "Your account has a negative balance because the order task was not completed. Recharge {amount2} to restore your earnings of {amount}.",
            "Simple online job for housewives and students: follow Instagram pages and earn up to {amount} a day. Join here: {link}",
            "Thank you for completing today's welfare task. Your reward of {small} is sent. Tomorrow's tasks need a deposit of {amount} for higher profit.",
            "The reception mentor has assigned you a lucky order of {amount2}. Complete it to receive triple commission along with your principal.",
            "We noticed your profile on a job portal. Part-time role, salary {amount} per week, payment daily to your bank. Click {link} to register.",
            "Your withdrawal failed due to a low credit score on the task platform. Pay {amount2} to repair the score and release your {amount}.",
            "Movie rating job: rate 30 movies a day and earn {amount} monthly. First three tasks are free, then join the prepaid VIP level.",
            "Dear member, to withdraw your commission you must pay the 18% tax of {amount2} first. The full {amount} will be credited in 10 minutes.",
            "Our team leader added you to the earning group. Everyone here earned {amount} this week. Send {small} for the first paid task and see it double.",
        ],
        "hi": [
            "पार्ट टाइम जॉब: यूट्यूब वीडियो लाइक करें और रोज़ {amount} तक कमाएं। टेलीग्राम पर जुड़ें: {link}",
            "आपका कमीशन {amount} रुका हुआ है। निकालने के लिए {amount2} का प्रीपेड टास्क पूरा करें।",
            "घर बैठे काम करें, रोज़ाना भुगतान। सिर्फ 15 मिनट रोज़। व्हाट्सएप करें {phone}",
            "बधाई हो! आपने 3 टास्क पूरे किए और {small} कमाए। अगला लेवल खोलने के लिए {amount} जमा करें।",
            "गृहिणियों और छात्रों के लिए ऑनलाइन काम: होटल को रेटिंग दें और हर रिव्यू पर {small} पाएं। अभी जुड़ें: {link}",
            "आपके टास्क खाते में नेगेटिव बैलेंस है। अपनी {amount} की कमाई वापस पाने के लिए {amount2} रिचार्ज करें।",
            "आपकी निकासी फेल हो गई क्योंकि क्रेडिट स्कोर कम है। स्कोर सुधारने के लिए {amount2} भरें और {amount} पाएं।",
            "मेंटर ने आपको {amount2} का लकी ऑर्डर दिया है। इसे पूरा करें और मूल राशि के साथ तीन गुना कमीशन पाएं।",
            "कमीशन निकालने से पहले {amount2} टैक्स भरना होगा। पूरी {amount} राशि 10 मिनट में खाते में आ जाएगी।",
            "आपकी प्रोफाइल जॉब पोर्टल पर देखी। पार्ट टाइम काम, हफ्ते की सैलरी {amount}। रजिस्टर करने के लिए {link} पर क्लिक करें।",
            "आज का टास्क पूरा करने के लिए धन्यवाद, {small} भेज दिए गए। कल ज़्यादा मुनाफे के लिए {amount} जमा करना होगा।",
            "इंस्टाग्राम पेज फॉलो करें और रोज़ {amount} तक कमाएं। पहले तीन टास्क फ्री, फिर वीआईपी लेवल जॉइन करें।",
        ],
        "hinglish": [
            "Part time job hai, sirf videos like karo aur roz {amount} tak kamao. Telegram pe join karo {link}",
            "Aapka commission {amount} lock hai, withdraw ke liye {amount2} ka prepaid task karo.",
            "Ghar baithe kaam, daily payment. 3 task complete karo aur {small} turant milega.",
            "Aapka level upgrade pending hai, {amount2} bharo to {amount} ka payout aaj hi milega.",
            "Hotel rating ka kaam hai, har review pe {small}. Housewives aur students ke liye best, abhi join karo {link}",
            "Aapke task account me negative balance aa gaya hai, {amount2} recharge karo to {amount} wapas mil jayega.",
            "Withdrawal fail hua kyunki credit score kam hai. {amount2} bharo score theek hoga aur {amount} release hoga.",
            "Mentor ne aapko {amount2} ka lucky order diya hai, complete karo to principal ke saath teen guna commission.",
            "Commission nikalne se pehle 18% tax {amount2} bharna padega, phir poora {amount} 10 minute me aa jayega.",
            "Aapka profile job portal pe dekha. Part time kaam, weekly salary {amount}. Register karne ke liye {link}",
            "Team leader ne aapko earning group me add kiya hai, sabne is hafte {amount} kamaye. Pehle task ke liye {small} bhejo, double ho jayega.",
            "Instagram pages follow karo aur roz {amount} tak kamao. Pehle 3 task free, fir VIP level join karna hai.",
        ],
    },
    # ---------------- trading_tip: investment / trading group ----------------
    "trading_tip": {
        "en": [
            "SEBI registered expert: {stock} will give {pct} return this week. Join our VIP WhatsApp group: {link}",
            "Guaranteed {pct} profit in IPO allotment. Pay {amount} to our institutional account for pre-allotment.",
            "Your trading account shows a profit of {amount}. Pay {amount2} as service tax to withdraw.",
            "Stock tip of the day: buy {stock} at open. Our members made {pct} last month. Limited seats in the premium group.",
            "Crypto arbitrage: double your money in {days} days. Minimum investment {amount}. Withdraw any time.",
            "Exclusive block deal for our students only. Transfer {amount} to the company account and the shares will be credited tomorrow.",
            "Welcome to the {broker} Elite Investors Club. Download our institutional app from {link} to get OTC shares at a 30% discount.",
            "Professor's free stock class starts tonight. Students who followed yesterday's signal earned {pct}. Add our assistant on WhatsApp {phone}",
            "Your withdrawal of {amount} is pending risk control. Deposit a 20% margin of {amount2} to release the funds to your bank.",
            "Last 5 seats: our AI trading bot gives {pct} monthly with zero risk. Start with {amount} and see profits from day one.",
            "Insider news: {stock} results will surprise the market. Buy before Friday. Paid members get the exit price; pay {small} to join.",
            "Dear investor, your allotment in the private placement of {stock} is confirmed. Pay {amount} to the custodian account today to secure it.",
            "Forex signal group with 95% accuracy. Members made {amount} last week alone. Membership fee {amount2}, money-back guarantee.",
            "Our fund manager will trade on your behalf. Share your login and deposit {amount}; you keep 70% of the profit every week.",
            "Your account is upgraded to VIP. VIP members get guaranteed upper-circuit stocks. Transfer the upgrade fee of {amount2} to activate.",
            "Mutual fund NFO with assured {pct} returns, backed by a foreign institution. Invest through our agent link only: {link}",
            "Congratulations, you won a new share allotment in the lucky IPO draw. Pay {amount} within {hours} hours or the shares go to the next investor.",
            "Gold investment scheme: invest {amount} today and get {pct} return in {days} days. Our relationship manager will share the account.",
        ],
        "hi": [
            "सेबी रजिस्टर्ड एक्सपर्ट: {stock} इस हफ्ते {pct} रिटर्न देगा। हमारे वीआईपी ग्रुप से जुड़ें: {link}",
            "आईपीओ में गारंटीड मुनाफा। प्री-अलॉटमेंट के लिए {amount} कंपनी खाते में जमा करें।",
            "आपके ट्रेडिंग खाते में {amount} का प्रॉफिट है। निकालने के लिए {amount2} टैक्स भरें।",
            "आज का स्टॉक टिप: {stock} खरीदें। हमारे सदस्यों ने पिछले महीने {pct} कमाया। प्रीमियम ग्रुप में कुछ ही सीटें बाकी।",
            "क्रिप्टो में {days} दिन में पैसा दोगुना करें। न्यूनतम निवेश {amount}, कभी भी निकालें।",
            "हमारे संस्थागत ऐप से 30% छूट पर शेयर पाएं। ऐप यहां से डाउनलोड करें: {link}",
            "आपकी {amount} की निकासी रिस्क कंट्रोल में है। पैसा छुड़ाने के लिए {amount2} मार्जिन जमा करें।",
            "हमारा एआई ट्रेडिंग बॉट हर महीने {pct} देता है, बिना जोखिम। {amount} से शुरू करें।",
            "प्रोफेसर की फ्री स्टॉक क्लास आज रात है। कल के सिग्नल से छात्रों ने {pct} कमाया। व्हाट्सएप करें {phone}",
            "आपका खाता वीआईपी में अपग्रेड हुआ। गारंटीड अपर सर्किट शेयर पाने के लिए {amount2} अपग्रेड फीस भेजें।",
            "गोल्ड निवेश योजना: आज {amount} लगाएं और {days} दिन में {pct} रिटर्न पाएं। हमारे मैनेजर खाता नंबर भेजेंगे।",
            "हमारे फंड मैनेजर आपकी ओर से ट्रेड करेंगे। लॉगिन दें और {amount} जमा करें, हर हफ्ते 70% मुनाफा आपका।",
        ],
        "hinglish": [
            "Bhai {stock} me {pct} pakka return hai is week, VIP group join kar lo {link}",
            "IPO me guaranteed allotment milega, {amount} institutional account me aaj hi bhejo.",
            "Aapka profit {amount} ho gaya hai, withdrawal ke liye pehle {amount2} fees bharo.",
            "Aaj ka tip: {stock} open pe kharido, members ne last month {pct} kamaya. Premium group me last seats.",
            "Crypto me {days} din me paisa double, minimum {amount} invest karo, kabhi bhi withdraw.",
            "Hamare institutional app se OTC shares 30% discount pe milenge, app yaha se download karo {link}",
            "Aapka {amount} withdrawal risk control me hai, release ke liye {amount2} margin jama karo.",
            "AI trading bot har mahine {pct} deta hai zero risk ke saath, {amount} se start karo.",
            "Professor ki free stock class aaj raat hai, kal ke signal se sabne {pct} kamaya. Assistant ko WhatsApp karo {phone}",
            "Aapka account VIP me upgrade hua, guaranteed upper circuit shares ke liye {amount2} upgrade fee bhejo.",
            "Gold scheme hai, aaj {amount} lagao aur {days} din me {pct} return. Manager account number bhejenge.",
            "Fund manager aapki taraf se trade karega, login do aur {amount} deposit karo, har hafte 70% profit aapka.",
        ],
    },
    # ---------------- refund: fake refund / cashback / collect request / QR ----------------
    "refund": {
        "en": [
            "Your refund of {amount} is approved. Scan the QR code to receive the money in your account.",
            "You have received a payment request of {amount}. Enter your UPI PIN to accept the refund.",
            "{company} order cancelled. Refund of {amount} pending. Call customer care {phone} and install {app} for processing.",
            "Your income tax refund of {amount} is ready. Verify your bank account at {link} to receive it today.",
            "You were charged twice for your {company} order. To get the extra {amount} back, approve the collect request we just sent.",
            "Cashback of {small} is waiting for you. Scan the attached QR and enter your PIN to claim it now.",
            "Your {airline} flight was cancelled. A refund of {amount} is due; share your card details at {link} to process it.",
            "This is {company} support. Your return pickup is done. For the refund, download {app} and enter the code shown to our agent.",
            "Dear customer, a reversal of {amount} is stuck. Accept the {amount2} request in your UPI app and the full amount will be credited back.",
            "Your electricity deposit refund of {amount} is approved. Fill in your debit card number and expiry at {link} to receive it.",
            "GST refund of {amount} has been sanctioned for your PAN. Click {link} and log in with net banking to credit it.",
            "Your insurance premium was paid in excess. To refund {amount}, our executive will send a QR; scan it and enter your PIN.",
            "Sorry for the trouble with your {company} order. We are refunding {amount}. Please share your screen through {app} so we can process it.",
            "Your failed UPI transaction of {amount} will be reversed only after you confirm the request with your PIN within {hours} hours.",
            "Congratulations, you are eligible for a {small} refund on your last recharge. Tap {link} and enter your UPI PIN to receive it.",
            "The buyer has paid for your OLX item. To receive {amount}, scan the QR the buyer sent and enter your UPI PIN.",
            "Your train ticket was cancelled and {amount} is refundable. Call the IRCTC refund desk at {phone} and keep your card ready.",
            "Your {bank} credit card annual fee of {amount2} will be refunded. Confirm by entering the OTP at {link}",
        ],
        "hi": [
            "आपका {amount} का रिफंड मंजूर हो गया है। पैसे पाने के लिए क्यूआर कोड स्कैन करें।",
            "पैसा प्राप्त करने के लिए अपना यूपीआई पिन डालें। रिफंड राशि {amount}।",
            "आपका आयकर रिफंड {amount} तैयार है। आज ही पाने के लिए {link} पर अपना बैंक खाता सत्यापित करें।",
            "आपके {company} ऑर्डर पर दो बार पैसा कटा है। अतिरिक्त {amount} वापस पाने के लिए हमारा भेजा अनुरोध स्वीकार करें।",
            "आपके लिए {small} कैशबैक है। क्यूआर स्कैन करें और पिन डालकर अभी पाएं।",
            "आपकी फ्लाइट रद्द हो गई है। {amount} रिफंड के लिए {link} पर कार्ड की जानकारी दें।",
            "आपका रिटर्न पिकअप हो गया है। रिफंड के लिए ऐप डाउनलोड करें और स्क्रीन पर आया कोड हमारे एजेंट को बताएं।",
            "आपका {amount} का रिवर्सल अटका है। यूपीआई ऐप में {amount2} का अनुरोध स्वीकार करें, पूरी राशि वापस आ जाएगी।",
            "जीएसटी रिफंड {amount} आपके पैन पर मंजूर हुआ है। नेट बैंकिंग से लॉगिन करके {link} पर लें।",
            "खरीदार ने आपके सामान का भुगतान कर दिया है। {amount} पाने के लिए भेजा गया क्यूआर स्कैन करें और पिन डालें।",
            "आपका ट्रेन टिकट रद्द हुआ, {amount} रिफंड होगा। रिफंड डेस्क {phone} पर कॉल करें और कार्ड तैयार रखें।",
            "पिछले रिचार्ज पर आपको {small} रिफंड मिलेगा। {link} पर जाकर यूपीआई पिन डालें।",
        ],
        "hinglish": [
            "Aapka refund {amount} approve ho gaya, paisa lene ke liye QR scan karo aur PIN dalo.",
            "{company} order cancel hua hai, refund {amount} pending hai. Customer care {phone} pe call karo aur {app} install karo.",
            "Aapka income tax refund {amount} ready hai, aaj hi lena hai to {link} pe bank account verify karo.",
            "Aapke order pe double payment cut gaya, extra {amount} wapas chahiye to hamari bheji request approve karo.",
            "{small} cashback aapka wait kar raha hai, QR scan karo aur PIN dalke claim karo.",
            "Flight cancel ho gayi hai, {amount} refund ke liye card details {link} pe daalo.",
            "Return pickup ho gaya hai, refund ke liye app download karo aur screen pe aaya code agent ko batao.",
            "Aapka {amount} reversal atka hua hai, UPI app me {amount2} ki request accept karo, poora paisa wapas aa jayega.",
            "Buyer ne OLX item ka payment kar diya hai, {amount} lene ke liye uska bheja QR scan karo aur PIN dalo.",
            "Train ticket cancel hua, {amount} refund milega. Refund desk {phone} pe call karo aur card ready rakho.",
            "Last recharge pe {small} refund milega, {link} pe jaake UPI PIN daalo.",
            "Insurance premium zyada kat gaya tha, {amount} refund ke liye executive QR bhejega, scan karke PIN dalna.",
        ],
    },
    # ---------------- other_scam: scams outside the five ----------------
    "other_scam": {
        "en": [
            # courier / customs parcel held
            "{courier}: your parcel is held at the warehouse due to an incomplete address. Pay a {small} redelivery fee at {link} within 24 hours.",
            "India Post: your package could not be delivered. Update your address and pay the {small} handling charge here: {link}",
            "Customs has held a gift parcel sent to you from London. Pay the clearance duty of {amount} to release it today.",
            # electricity / gas disconnection
            "Dear consumer, your electricity will be disconnected {time} because last month's bill is not updated. Call our officer {phone} immediately.",
            "Your gas connection will be cut {time} due to pending KYC of the bill. Pay {small} verification fee at {link}",
            "Electricity Board: your meter shows an unpaid balance. Power will be cut tonight. Contact the electricity officer on {phone} to update.",
            # lottery / prize
            "Congratulations! Your number won {amount} in the {prize}. Pay the {amount2} processing tax to claim your prize. Call {phone}",
            "You are selected as the lucky winner of a car in the {prize}. Pay the registration fee of {amount2} to receive the keys.",
            # instant loan fee
            "Your loan of {amount} from {loanapp} is approved without CIBIL. Pay the {amount2} processing fee to receive the money in 10 minutes.",
            "Pre-approved personal loan of {amount} at 0% interest. Only file charge of {small} required. Apply now: {link}",
            # loan app harassment
            "Your {loanapp} loan is overdue. Pay {amount2} today or your photos will be sent to everyone in your contact list.",
            # society maintenance / water bill clone
            "{society}: the maintenance account has changed. Please pay {month} maintenance of {amount} to the new UPI ID {upi} today.",
            "Water supply to your flat will be stopped tomorrow due to pending water bill. Pay {small} immediately at {link}",
            # fake job registration fee
            "Congratulations, you are selected for the post of data entry operator at {company}. Pay the {amount2} registration and uniform fee to get your joining letter.",
            "Airport ground staff vacancy: you are shortlisted. Deposit {amount2} for training and the ID card before {date} to confirm your seat.",
            # sextortion / video-call blackmail
            "I have recorded your video call. If you do not pay {amount} within one hour, I will send the video to your family and post it online.",
            "This is Cyber Police. A complaint about an obscene video involving you has been filed. Pay {amount} to delete the case and the video.",
            # fake traffic e-challan
            "Traffic e-challan: your vehicle {vehicle} has a pending fine of {small}. Pay now to avoid court action: {link}",
            "Your vehicle {vehicle} was caught over-speeding. Download the e-challan app from {link} to pay the penalty today.",
            # insurance / LIC bonus
            "{insurer}: your policy bonus of {amount} is ready. Pay the GST of {amount2} to release the maturity amount to your account.",
            "Your lapsed {insurer} policy can be revived with a bonus of {amount}. Transfer the revival charge of {amount2} to our officer.",
            # wrong-UPI "please return"
            "Sorry, I sent {amount} to your number by mistake. Please return it to this UPI ID: {upi}",
            # crypto / gift card
            "This is your manager. I am in a meeting; please buy {gift} worth {amount} and send me the codes urgently. I will repay you today.",
            # fake charity / donation
            "Please help: donate for {cause}. Every rupee counts. Send any amount to {upi}; 80G receipt will be sent on WhatsApp.",
        ],
        "hi": [
            "आपका पार्सल अधूरे पते के कारण रुका है। {small} दोबारा डिलीवरी शुल्क {link} पर 24 घंटे में भरें।",
            "प्रिय उपभोक्ता, पिछले महीने का बिल अपडेट नहीं होने से {time} बिजली काट दी जाएगी। तुरंत {phone} पर कॉल करें।",
            "आपका गैस कनेक्शन {time} काट दिया जाएगा। {small} सत्यापन शुल्क {link} पर भरें।",
            "बधाई हो! आपके नंबर ने {prize} में {amount} जीते हैं। इनाम पाने के लिए {amount2} टैक्स भरें।",
            "बिना सिबिल {amount} का लोन मंजूर। 10 मिनट में पैसा पाने के लिए {amount2} प्रोसेसिंग फीस भरें।",
            "आपका लोन बकाया है। आज {amount2} नहीं भरे तो आपकी फोटो आपके सभी कॉन्टैक्ट्स को भेज दी जाएंगी।",
            "सोसाइटी का मेंटेनेंस खाता बदल गया है। कृपया {amount} नए यूपीआई आईडी {upi} पर आज ही भेजें।",
            "डाटा एंट्री पद के लिए आपका चयन हुआ है। जॉइनिंग लेटर के लिए {amount2} रजिस्ट्रेशन फीस भरें।",
            "मैंने आपकी वीडियो कॉल रिकॉर्ड कर ली है। एक घंटे में {amount} नहीं भेजे तो वीडियो आपके परिवार को भेज दूंगा।",
            "ट्रैफिक ई-चालान: आपके वाहन {vehicle} पर {small} का जुर्माना बाकी है। कोर्ट कार्रवाई से बचने के लिए अभी भरें: {link}",
            "आपकी बीमा पॉलिसी का {amount} बोनस तैयार है। राशि पाने के लिए {amount2} जीएसटी भरें।",
            "गलती से आपके नंबर पर {amount} भेज दिए, कृपया इस यूपीआई पर वापस कर दें {upi}",
            "मैं मीटिंग में हूँ, जल्दी से {amount} के गिफ्ट कार्ड खरीदकर कोड भेज दो, आज ही लौटा दूंगा।",
            "कृपया {cause} के लिए दान करें। कोई भी राशि {upi} पर भेजें, रसीद व्हाट्सएप पर मिलेगी।",
        ],
        "hinglish": [
            "Aapka parcel address incomplete hone ki wajah se ruka hai, {small} redelivery fee {link} pe 24 ghante me bharo.",
            "Aapki bijli aaj raat kat jayegi, bill update nahi hua. Electricity officer {phone} pe turant call karo.",
            "Gas connection {time} kat jayega, {small} verification fee {link} pe bharo.",
            "Badhai ho! Aapke number ne {prize} me {amount} jeete hain, prize lene ke liye {amount2} tax bharo.",
            "Bina CIBIL {amount} ka loan approve hai, 10 minute me paisa chahiye to {amount2} processing fee bharo.",
            "Loan overdue hai, aaj {amount2} nahi bhara to aapki photos sab contacts ko bhej denge.",
            "Society ka maintenance account change ho gaya hai, {amount} naye UPI {upi} pe aaj hi bhejo.",
            "Data entry job ke liye aap select ho gaye ho, joining letter ke liye {amount2} registration fee bharo.",
            "Maine tumhari video call record kar li hai, ek ghante me {amount} nahi bheje to video family ko bhej dunga.",
            "Gaadi {vehicle} pe {small} ka e-challan pending hai, court se bachna hai to abhi pay karo {link}",
            "Policy ka {amount} bonus ready hai, release ke liye {amount2} GST bharo.",
            "Galti se aapke number pe {amount} bhej diya, please is UPI pe wapas kar do {upi}",
            "Main meeting me hoon, jaldi se {amount} ke gift cards le ke codes bhej do, aaj hi wapas kar dunga.",
            "{cause} ke liye donation karo, koi bhi amount {upi} pe bhejo, receipt WhatsApp pe milegi.",
        ],
    },
    # ---------------- normal: everyday messages and honest look-alikes ----------------
    "normal": {
        "en": [
            # OTPs
            "{otp} is your OTP for a transaction of {amount} at {company}. Valid for 5 minutes. Do not share it with anyone. -{bank}",
            "Your OTP to log in to {company} is {otp}. Do not share it with anyone, our staff will never ask for it.",
            "{otp} is the verification code for your {operator} account. It expires in 10 minutes.",
            "Use {otp} as your one-time password to reset your {bank} net banking password. Never share it.",
            "Dear customer, {otp} is your OTP to register your mobile number on {bank} mobile banking. Valid for 3 minutes.",
            "{otp} is your Aadhaar OTP for the update request. It is valid for 10 minutes. -UIDAI",
            # bank debit / credit / UPI receipts
            "Rs {amount} debited from a/c XX{acct} on {date} to VPA {upi}. UPI Ref {ref}. Not you? Call the number on the back of your card. -{bank}",
            "Your a/c XX{acct} is credited with INR {amount} on {date} by UPI from {name}. Ref {ref}. -{bank}",
            "Salary of Rs {amount} credited to your account XX{acct}. -{bank}",
            "You paid {small} to {shop} via UPI. Ref no {ref}. Available balance is shown in your app.",
            "Payment of {small} to {shop} successful. UPI transaction ID {ref}.",
            "INR {amount2} withdrawn at an ATM in {city} from a/c XX{acct} on {date}. If not done by you, block your card from the app. -{bank}",
            "Your {bank} credit card XX{acct} was used for {small} at {shop} on {date}. Available limit updated.",
            "Your EMI of {amount2} for loan a/c XX{acct} has been debited on {date}. Thank you. -{bank}",
            "Your SIP of {small} in the Flexi Cap Fund has been processed on {date}. Units will be allotted at today's NAV.",
            "Fixed deposit XX{acct} of {amount} has matured and the amount is credited to your savings account. -{bank}",
            "Cheque no. {acct} for {amount2} has been cleared on {date}. -{bank}",
            "You have received {small} from {name} on your UPI ID. Ref {ref}.",
            # deliveries / orders
            "Your {courier} shipment {ref} is out for delivery today. Please keep your phone reachable.",
            "Your {company} order has been delivered. Rate your experience in the app.",
            "Your {company} order {order} has been shipped and will arrive by {day}. Track it here: {nlink}",
            "Your {shop} order is on the way. The delivery partner will reach you in {mins} minutes.",
            "Delivery attempt failed for order {order} as the house was locked. We will try again {day}.",
            "Your {company} return request for order {order} is accepted. Pickup is scheduled for {day}.",
            "OTP for delivering your {company} order is {otp}. Share it only with the delivery agent at your door.",
            "{courier}: your parcel {ref} has reached the {city} hub and will be delivered in 2 days.",
            # recharges / bills paid / utilities
            "Recharge of {plan} successful. Validity 28 days. Thank you for choosing {operator}.",
            "Your {operator} plan expires in 3 days. Recharge on the app to continue enjoying unlimited calls.",
            "Your electricity bill of Rs {amount2} for consumer no. {ref} is due on {date}. Pay on the official app or website to avoid a late fee.",
            "Thank you! Payment of {small} received for your electricity bill, consumer no. {ref}.",
            "Electricity supply will be off on {date} from 10 AM to 2 PM for maintenance in your area.",
            "Your piped gas bill of {small} is generated. Due date {date}. Pay on the official app.",
            "Your DTH subscription is renewed for 30 days. Amount {small} debited from your wallet.",
            "Your {ott} subscription has been renewed for {small}. Manage it in your account settings.",
            "FASTag: {small} deducted at the toll plaza for vehicle {vehicle}. Balance updated.",
            # doctor / school / society / work
            "Your appointment at {clinic} is confirmed for {date}, {clock}. Reply C to cancel.",
            "Your lab report is ready. You can collect it from {clinic} or view it in the app.",
            "Reminder: your child's vaccination is due on {date} at {clinic}.",
            "{school}: the parent-teacher meeting is on {day} at {clock}. Please attend.",
            "{school}: school will remain closed {day} due to heavy rain.",
            "{school}: fees for the {month} quarter are due by {date}. Pay at the school office or through the school app.",
            "{society}: water supply will be off on {day} from 10 AM to 1 PM for tank cleaning.",
            "{society}: maintenance of Rs {amount2} for {month} is due. Please pay to the society account before the 10th.",
            "{society}: the AGM is on {day} at {clock} in the clubhouse. All members are requested to attend.",
            "Team, the review meeting is moved to {clock} {day}. Please update your slides.",
            "Hi {name}, your interview with {company} HR is scheduled on {date} at 11 AM at our {city} office. Please bring your resume.",
            "Your leave request for {date} has been approved by your manager.",
            # look-alikes: genuine KYC, refunds, police / RBI awareness, jobs, brokers, e-challan
            "Dear Customer, periodic KYC update is due for your {bank} account. Please visit your home branch with ID proof. We never ask for OTP or PIN on call.",
            "Your KYC has been successfully updated. No further action is needed. -{bank}",
            "Your SIM e-KYC is complete. No further action is needed. Never share OTP with anyone claiming to be from TRAI.",
            "Re-KYC reminder: you can update KYC through the bank's official app or at any branch. {bank} never sends links to update KYC.",
            "Refund of {amount} for your {company} order has been processed to your original payment method. It may take 3 to 5 working days.",
            "Your income tax refund of {amount} for AY 2026-27 has been credited to your bank account XX{acct}.",
            "The refund of {small} for your cancelled {airline} booking has been credited to your card.",
            "Your failed UPI transaction of {small} on {date} has been reversed to your account. Ref {ref}. -{bank}",
            "Cashback of {small} has been credited to your wallet for your last bill payment.",
            "Cyber Dost: police never arrest anyone over a video call. If someone threatens you, hang up and report it at 1930.",
            "RBI Kehta Hai: never share OTP, PIN or CVV. Banks never ask you to move money to a safe account.",
            "Beware of fake e-challan links. Check challans only on the official Parivahan site. Police never send payment links on WhatsApp.",
            "Alert from {bank}: we never ask you to install screen sharing apps. Do not scan QR codes to receive money.",
            "There is no such thing as digital arrest. No government agency asks for money on a call. Report such calls at 1930.",
            "Traffic e-challan: a challan of {small} has been issued to vehicle {vehicle} on {date}. Check and pay only on the official Parivahan portal.",
            "Trade executed: bought 10 shares of {stock} at the market price. The contract note has been sent to your email. -{broker}",
            "Your IPO application for {stock} is received. Allotment status will be shared on {date}. -{broker}",
            "Funds of {amount} added to your {broker} trading account. Happy investing.",
            "Your {broker} account statement for {month} is ready. Log in to the app to view it.",
            "Thank you for applying to {company}. Your application is under review and our team will contact you if shortlisted.",
            "{company} Careers: your online assessment is scheduled for {date}. There is no fee at any stage of our hiring.",
            "Your {insurer} policy premium of {amount2} is due on {date}. Pay through the official app or at the branch.",
            "Your {insurer} policy has matured. The amount of {amount} will be credited to your registered bank account.",
            "Parcel from your relative is held at the post office. Collect it with ID proof between 10 AM and 5 PM.",
            "Your loan application with {bank} is approved. Our branch will contact you for the documents.",
            # promos / offers
            "Big Diwali sale at {shop}: up to 50% off on electronics. Visit your nearest store this weekend.",
            "Get flat {small} off on your next order with code SAVE50. Valid till {date}. T&C apply.",
            "{company} Mega Sale starts {day}. Members get early access. Download the app to shop.",
            "Upgrade to a {plan} plan and get extra 2GB data daily. Recharge on the {operator} app.",
            "Your {shop} reward points: you have 340 points. Redeem them on your next visit.",
            # friends and family chat
            "Happy birthday {name}! Party at our place at {clock}, don't be late.",
            "Reached the station, will call you after dinner.",
            "Hey {name}, can you send me the notes from today's class?",
            "Can you pick up {item} on your way back?",
            "Running late, will be there by {clock}. Start without me.",
            "Movie tickets booked for {day} {clock}. See you at the mall.",
            "{name}, I sent you {small} for the cab. Check your UPI.",
            "Congrats on the new job {name}! Treat pending.",
            "Mom's flight lands at {clock}. Can you pick her up from the airport?",
            "Don't forget the electricity bill, I paid last month. Your turn this time.",
            "Meeting got over early. Shall we go for lunch at {clock}?",
            "Thanks for coming yesterday {name}, the kids loved it.",
            "Please share the photos from the wedding when you get time.",
            "I've sent the rent for {month}, {amount2}. Please confirm when you see it.",
            "Can we split the dinner bill? It's {small} each.",
            "Good morning! Hope you're feeling better today.",
            "{name}, the plumber is coming {day} at {clock}. Can you be home?",
            "Sending you the address of {clinic}. The appointment is at {clock}.",
            "Booked the train for {date}. PNR sent on WhatsApp. Carry your ID.",
            "Your table for 4 at {clock} on {date} is confirmed. See you soon!",
            "Your {airline} flight on {date} is on time. Web check-in is open in the app.",
            "Your {airline} booking is confirmed for {date}. Boarding starts 45 minutes before departure.",
            "Your cab is arriving in {mins} minutes. Share OTP {otp} with the driver to start the ride.",
            "Your {shop} bill of {small} is paid. Thank you for shopping with us.",
            "Your gas cylinder booking is confirmed. Delivery expected by {day}. Pay the delivery person on arrival.",
            "{bank}: your new debit card has been dispatched by {courier} and will reach you in 5 to 7 days.",
            "Your account statement for {month} has been sent to your registered email. -{bank}",
            "Dear customer, your {bank} credit card bill of {amount2} is due on {date}. Ignore if already paid.",
            "{name} has requested {small} for the dinner bill. Approve or decline in your UPI app.",
            "Auto-pay of {small} for your {ott} subscription is scheduled for {date}.",
            "Hi {name}, the {school} picnic is on {day}. Please send {small} with your child by Friday.",
            "Blood donation camp at the {society} clubhouse on {day}, {clock}. Volunteers welcome.",
            "Reminder: your car service is due. Book a slot at your nearest service centre this {day}.",
            "{name}, I reached {city}. The hotel is nice, will call you at {clock}.",
            # more look-alikes: scam words in honest messages
            "Your refund request for order {order} is approved. {amount2} will reach your bank account in 5 to 7 days. No action is needed.",
            "{company}: we have initiated a refund of {small} to your UPI ID. You never need a PIN or a QR code to receive money.",
            "Your GST refund application has been processed. Check the status on the official GST portal.",
            "Your security deposit refund will be adjusted in your next electricity bill.",
            "Dear customer, your KYC is due for renewal by {date}. Update it in the {bank} app under Profile, or at any branch.",
            "Video KYC for your new {bank} account is scheduled at {clock}. We will never ask for your OTP, PIN or password.",
            "Your Aadhaar is now linked with your {bank} account. Subsidy payments will be credited directly. -{bank}",
            "{name} has requested {small} on UPI for movie tickets. Pay only if you know this person.",
            "Hi {name}, can you send {small} for the cab? Will return it tonight.",
            "Police helpline: if you get a call about a parcel with drugs in your name, it is a scam. Hang up and dial 1930.",
            "Awareness message from {bank}: fraudsters pose as CBI or customs officers. No officer will ever ask you to transfer money.",
            "Traffic Police: a challan of {small} for vehicle {vehicle} is pending. Pay at the traffic office or the official app; ignore links from unknown numbers.",
            "{courier}: delivery of shipment {ref} is rescheduled to {day} as you requested.",
            "EMI reminder: {amount2} will be debited on {date}. Please keep sufficient balance in your account. -{bank}",
            "Your personal loan of {amount} has been disbursed to your account XX{acct}. -{bank}",
            "{insurer}: your policy bonus statement is available in the app. No payment is needed.",
            "Thank you for registering on the {company} careers portal. We never charge any fee for interviews or joining.",
            "{stock} has reached your price alert. Open the {broker} app to view. Investments are subject to market risk.",
            "{broker}: margin shortfall of {small} in your account. Add funds in the app to avoid square-off.",
            "Auto-debit for your electricity bill failed. Please pay on the official app by {date} to avoid a late fee.",
            "Lucky draw results at {shop}: coupon holders can check the winners at the store counter on {day}.",
            "Thank you for your donation of {small} to the temple trust. Your 80G receipt has been emailed to you.",
            "Your income tax return is processed and a refund of {amount2} is determined. It will be credited to your validated bank account.",
            "KYC update: your documents were verified at the {city} branch on {date}. Your account is fully active. -{bank}",
            "As per RBI rules, your account needs a KYC refresh this year. Visit any {bank} branch or use the official app; staff will never call you for it.",
            "Your mobile number is updated in your {bank} account. If you did not request this, visit your branch.",
            "Refund of {small} credited to your {bank} account for the returned item from {shop}.",
            "Your cancelled order's money, {small}, is back in your account. Sorry for the trouble. -{company}",
            "{name} sent you a request for {small} for the trip expenses. Open your UPI app to pay or decline.",
            "Bro, can you send {small}? My card isn't working at the shop. Will pay you back tonight.",
            "Hi {relation}, please send {amount2} for the hostel fees, the last date is {date}.",
            "Cyber Crime Wing: do not trust calls claiming your Aadhaar is in a money laundering case. Real police will never demand money.",
            "Stay safe: never scan a QR code or enter your UPI PIN to receive money. Report fraud at 1930.",
            "Planned power shutdown on {date} from {clock} for line work. Inconvenience regretted. -Power Dept",
            "{company} HR: your offer letter is attached in your email. Joining is on {date}. No payment is required at any stage.",
            "{insurer}: premium of {amount2} received for your policy. Thank you for staying insured.",
        ],
        "hi": [
            "आपका ओटीपी {otp} है। इसे किसी के साथ साझा न करें। -{bank}",
            "{otp} आपका लॉगिन ओटीपी है। बैंक कर्मचारी कभी ओटीपी नहीं मांगते।",
            "आपके खाते XX{acct} से {amount} यूपीआई द्वारा कटे। संदर्भ {ref}। -{bank}",
            "आपके खाते में {amount} जमा हुए हैं। -{bank}",
            "आपके खाते XX{acct} में {name} से {small} प्राप्त हुए। संदर्भ {ref}।",
            "आपकी लोन की किस्त {amount2} {date} को कट गई है। धन्यवाद। -{bank}",
            "आपका बिजली बिल {amount2} देय है। अंतिम तिथि {date} है।",
            "धन्यवाद! आपके बिजली बिल का {small} भुगतान प्राप्त हुआ।",
            "{date} को सुबह 10 से दोपहर 2 बजे तक रखरखाव के लिए बिजली बंद रहेगी।",
            "आपका {plan} का रिचार्ज सफल रहा। वैधता 28 दिन।",
            "पुलिस कभी वीडियो कॉल पर गिरफ्तार नहीं करती। धोखाधड़ी की शिकायत 1930 पर करें।",
            "डिजिटल अरेस्ट जैसी कोई चीज़ नहीं होती। कोई सरकारी एजेंसी फोन पर पैसे नहीं मांगती।",
            "आरबीआई कहता है: ओटीपी, पिन या सीवीवी किसी को न बताएं। बैंक कभी सुरक्षित खाते में पैसा भेजने को नहीं कहता।",
            "प्रिय ग्राहक, आपके खाते का केवाईसी अपडेट होना है। कृपया अपनी शाखा में पहचान पत्र के साथ आएं। बैंक कभी ओटीपी नहीं मांगता।",
            "आपका केवाईसी सफलतापूर्वक अपडेट हो गया है। अब कुछ करने की ज़रूरत नहीं। -{bank}",
            "आपका रिफंड {amount} आपके खाते में भेज दिया गया है। 3 से 5 दिन लग सकते हैं।",
            "आपका {date} का फेल हुआ यूपीआई लेनदेन {small} वापस खाते में आ गया है।",
            "आपका आयकर रिफंड {amount} आपके बैंक खाते में जमा हो गया है।",
            "आपका पार्सल आज डिलीवर होगा। कृपया फोन चालू रखें।",
            "आपका ऑर्डर भेज दिया गया है और {day} तक पहुँच जाएगा।",
            "आपका पार्सल डाकघर में है। पहचान पत्र के साथ सुबह 10 से शाम 5 बजे के बीच ले जाएं।",
            "{date} को {clock} डॉक्टर के साथ आपकी अपॉइंटमेंट पक्की है।",
            "आपकी जांच रिपोर्ट तैयार है, क्लिनिक से ले जाएं।",
            "स्कूल की अभिभावक-शिक्षक बैठक {day} {clock} है। कृपया आएं।",
            "भारी बारिश के कारण स्कूल {day} बंद रहेगा।",
            "सोसाइटी: {day} सुबह 10 से 1 बजे तक टंकी सफाई के कारण पानी बंद रहेगा।",
            "सोसाइटी का {month} का मेंटेनेंस {amount2} बाकी है, 10 तारीख से पहले सोसाइटी खाते में जमा करें।",
            "ट्रैफिक ई-चालान: वाहन {vehicle} पर {small} का चालान जारी हुआ है। केवल आधिकारिक परिवहन पोर्टल पर देखें और भरें।",
            "आपकी बीमा पॉलिसी का प्रीमियम {amount2} {date} को देय है। आधिकारिक ऐप या शाखा में भरें।",
            "दिवाली सेल: सभी कपड़ों पर 40% तक छूट। इस हफ्ते अपने नज़दीकी स्टोर पर आएं।",
            "{relation}, सब्जी के लिए {small} भेज दो, शाम को लौटा दूँगी।",
            "कल सुबह 10 बजे मीटिंग है, समय पर आ जाना।",
            "{relation}, घर पहुँच गया हूँ, खाना खा लिया।",
            "{name}, लौटते समय {item} लेते आना।",
            "जन्मदिन मुबारक हो {name}! {clock} घर पर पार्टी है।",
            "मैं {clock} तक पहुँच जाऊँगा, तुम लोग शुरू करो।",
            "{relation}, किराए के {amount2} भेज दिए हैं, देख लेना।",
            "शादी की फोटो भेज देना जब समय मिले।",
            "{day} मंदिर चलेंगे, सुबह जल्दी तैयार रहना।",
            "{name}, आज की क्लास के नोट्स भेज दो।",
            "नानी की तबीयत अब ठीक है, चिंता मत करो।",
            "शुभ प्रभात! आपका दिन अच्छा हो।",
            "ट्रेन दो घंटे लेट है, पहुँचकर फोन करूँगा।",
            "{relation}, दवाई ले ली? डॉक्टर ने {clock} बुलाया है।",
            "बधाई हो {name}, नई नौकरी के लिए! मिठाई कब खिला रहे हो?",
            "{name}, {day} {clock} प्लंबर आएगा, घर पर रहना।",
            "आपकी {date} की ट्रेन टिकट बुक हो गई है। यात्रा में पहचान पत्र साथ रखें।",
            "आपका गैस सिलेंडर बुक हो गया है। डिलीवरी {day} तक होगी, भुगतान डिलीवरी पर करें।",
            "आपके क्रेडिट कार्ड का बिल {amount2} {date} तक देय है। भुगतान कर दिया हो तो ध्यान न दें। -{bank}",
            "{shop} पर आपका {small} का बिल भुगतान हो गया। खरीदारी के लिए धन्यवाद।",
            "आपकी कैब {mins} मिनट में पहुँच रही है। सवारी शुरू करने के लिए ड्राइवर को ओटीपी {otp} बताएं।",
            "{relation}, {city} पहुँच गया हूँ, होटल अच्छा है। {clock} फोन करूँगा।",
            "सोसाइटी क्लबहाउस में {day} {clock} रक्तदान शिविर है। सभी आमंत्रित हैं।",
            "आपके खाते का {month} का स्टेटमेंट ईमेल पर भेज दिया गया है। -{bank}",
            "{name} ने खाने के बिल के लिए {small} का अनुरोध भेजा है। यूपीआई ऐप में स्वीकार या अस्वीकार करें।",
            # more look-alikes
            "आपका रिफंड अनुरोध मंजूर हो गया है, {amount2} 5 से 7 दिन में खाते में आएंगे। कुछ करने की ज़रूरत नहीं।",
            "{company}: {small} का रिफंड आपके यूपीआई में भेजा गया है। पैसे पाने के लिए कभी पिन या क्यूआर नहीं चाहिए।",
            "आपके ऑर्डर का रिफंड {small} आपके खाते में जमा हो गया है।",
            "आपकी आयकर रिटर्न प्रोसेस हो गई है, रिफंड {amount2} जल्द खाते में आएगा।",
            "आपका केवाईसी {date} तक नवीनीकरण के लिए देय है। बैंक ऐप में या किसी भी शाखा में अपडेट करें।",
            "आपका आधार आपके {bank} खाते से लिंक हो गया है। सब्सिडी सीधे खाते में आएगी।",
            "आपका ई-केवाईसी पूरा हो गया है, धन्यवाद। -{bank}",
            "{name}, किराने के लिए {small} भेज देना, कल लौटा दूंगा।",
            "{relation}, फीस के लिए {amount2} भेज दिए हैं, रसीद ले लेना।",
            "{name} ने यूपीआई पर {small} मांगे हैं। जानते हों तभी भुगतान करें।",
            "पुलिस हेल्पलाइन: ड्रग्स वाले पार्सल के नाम पर कॉल आए तो वह धोखा है। फोन काटें और 1930 डायल करें।",
            "सावधान: ठग सीबीआई या कस्टम अधिकारी बनकर फोन करते हैं। कोई अधिकारी पैसे ट्रांसफर करने को नहीं कहता।",
            "ट्रैफिक पुलिस: वाहन {vehicle} पर {small} का चालान बाकी है। ट्रैफिक कार्यालय या आधिकारिक ऐप पर भरें, अनजान लिंक पर नहीं।",
            "आपका पर्सनल लोन {amount} खाते XX{acct} में जमा कर दिया गया है। -{bank}",
            "आपकी ईएमआई {amount2} {date} को कटेगी, खाते में बैलेंस रखें।",
            "ऑटो-डेबिट से बिजली बिल नहीं कट सका। {date} तक आधिकारिक ऐप पर भुगतान करें।",
            "मंदिर ट्रस्ट को {small} दान के लिए धन्यवाद। रसीद ईमेल पर भेज दी गई है।",
            "आपके नौकरी के आवेदन की समीक्षा हो रही है। हमारी भर्ती में कोई शुल्क नहीं लिया जाता।",
            "{stock} आपके तय भाव पर पहुँच गया है। देखने के लिए {broker} ऐप खोलें।",
            "आपकी बीमा पॉलिसी का बोनस विवरण ऐप में उपलब्ध है, कोई भुगतान नहीं करना है।",
            "केवाईसी अपडेट: आपके दस्तावेज़ {date} को शाखा में सत्यापित हो गए। आपका खाता पूरी तरह चालू है। -{bank}",
            "आरबीआई नियम के अनुसार इस साल आपके खाते का केवाईसी नवीनीकरण होना है। किसी भी शाखा में जाएं, बैंक इसके लिए फोन नहीं करता।",
            "आपका मोबाइल नंबर {bank} खाते में अपडेट हो गया है। अगर आपने अनुरोध नहीं किया तो शाखा में संपर्क करें।",
            "लौटाए गए सामान का {small} रिफंड आपके खाते में जमा हो गया है।",
            "रद्द ऑर्डर के {small} आपके खाते में वापस आ गए हैं। असुविधा के लिए खेद है।",
            "{name} ने यात्रा के खर्च के लिए {small} का अनुरोध भेजा है। भुगतान या अस्वीकार करने के लिए यूपीआई ऐप खोलें।",
            "{relation}, हॉस्टल फीस के लिए {amount2} भेज दो, आखिरी तारीख {date} है।",
            "भाई, {small} भेज दे, दुकान पर कार्ड नहीं चल रहा। रात को लौटा दूंगा।",
            "साइबर क्राइम सेल: आधार के मनी लॉन्ड्रिंग केस वाले कॉल पर भरोसा न करें। असली पुलिस कभी पैसे नहीं मांगती।",
            "सावधान रहें: पैसे पाने के लिए कभी क्यूआर स्कैन न करें या यूपीआई पिन न डालें। धोखाधड़ी की शिकायत 1930 पर करें।",
            "{date} को {clock} से लाइन के काम के लिए बिजली बंद रहेगी। असुविधा के लिए खेद है।",
            "आपका ऑफर लेटर ईमेल पर भेज दिया गया है। जॉइनिंग {date} को है, किसी भी चरण में कोई भुगतान नहीं।",
            "आपकी पॉलिसी का प्रीमियम {amount2} प्राप्त हुआ। धन्यवाद।",
        ],
        "hinglish": [
            "Aapka OTP {otp} hai, kisi ke saath share mat karna. -{bank}",
            "{otp} aapka login OTP hai, bank kabhi OTP nahi maangta.",
            "Bhai kal match dekhne chalega? {clock} milte hain.",
            "{relation} main ghar pahunch gaya, khana kha liya.",
            "Didi rent ke {amount2} bhej diye hain, check kar lo.",
            "Sir aapka order out for delivery hai, ghar pe rahiye.",
            "Office me aaj late hoga, tum kha lena.",
            "Plumber ko {small} de dena, kaam ho gaya hai.",
            "Kal se online class 9 baje start hogi, link group me daal diya hai.",
            "Mandir ke liye {small} chanda dena hai, society group me details hain.",
            "Bhaiya paise mil gaye, thank you. Shaam ko call karta hoon.",
            "{name} aate time {item} le aana please.",
            "Yaar {clock} tak pahunch jaunga, tum log start karo.",
            "Happy birthday {name}! {clock} ghar pe party hai, late mat hona.",
            "Movie ke tickets {day} ke book kar diye, mall pe milte hain.",
            "{name} cab ke liye {small} bhej diya hai, UPI check kar.",
            "Mummy ki flight {clock} land hogi, airport se pick kar lena.",
            "Dinner ka bill split kar lete hain, {small} each.",
            "Shaadi ki photos bhej dena jab time mile.",
            "Nani ki tabiyat ab theek hai, tension mat lo.",
            "Train 2 ghante late hai, pahunch ke call karta hoon.",
            "{relation} dawai le li? Doctor ne {clock} bulaya hai.",
            "Congrats {name} nayi job ke liye! Party kab de raha hai?",
            "Aaj ki class ke notes bhej de yaar.",
            "{day} mandir chalna hai, subah jaldi ready rehna.",
            "Kal PTM hai {clock}, tum aa jaoge na?",
            "Bijli ka bill maine bhar diya, {small} aaya tha is baar.",
            "Gas cylinder book kar diya, {day} tak aa jayega.",
            "Ghar ka wifi recharge kar diya, {plan} wala plan liya.",
            "Society ka maintenance {amount2} bhar diya hai, receipt group me daal di.",
            "Aapke account XX{acct} se {small} UPI se kate, ref {ref}. -{bank}",
            "Aapke account me {amount} credit hue hain. -{bank}",
            "Aapka {date} ka failed UPI transaction {small} wapas account me aa gaya hai.",
            "Aapka refund {amount} process ho gaya hai, 3-5 din me account me aa jayega.",
            "Bhai mera income tax refund aa gaya, {amount} account me credit hua.",
            "Order cancel kar diya tha, refund original payment method me aa gaya.",
            "Bank ka message aaya tha KYC ka, kal branch jaake documents de aaunga.",
            "Mera KYC update ho gaya, branch me 10 minute laga bas.",
            "Police kabhi video call pe arrest nahi karti, aisa call aaye to kaat do aur 1930 pe report karo.",
            "Koi bhi QR scan karke paise nahi milte, sirf dene ke liye scan hota hai. Dhyan rakhna.",
            "Gaadi ka e-challan aaya hai {small} ka, Parivahan site pe check karke bhar dunga.",
            "{company} ka interview {day} hai, resume print karwa liya.",
            "Bhai {stock} ka IPO apply kiya, allotment {date} ko aayega.",
            "Aaj market me {stock} upar gaya, maine 10 shares liye the {broker} pe.",
            "Doctor ka appointment {day} {clock} ka hai, yaad dila dena.",
            "School {day} band rahega baarish ki wajah se, message aaya hai.",
            "Recharge ho gaya, 28 din validity mili.",
            "Parcel aaj aa jayega, ghar pe koi rehna.",
            "Sale chal rahi hai {shop} me, {day} chalte hain.",
            "Good morning ji, aaj ka din shubh ho.",
            "{name} plumber {day} {clock} aayega, ghar pe rehna.",
            "{date} ki train ki ticket book ho gayi, PNR WhatsApp pe bheja hai.",
            "Cab {mins} minute me aa rahi hai, driver ko OTP {otp} batana.",
            "{shop} ka bill {small} pay ho gaya, thank you message aaya.",
            "{name} ne dinner bill ke liye {small} ki request bheji hai, approve kar dena.",
            "{relation} {city} pahunch gaya, hotel accha hai. {clock} call karta hoon.",
            "Credit card ka bill {amount2} {date} tak bharna hai, yaad dila dena.",
            "{school} ki picnic {day} hai, bacche ke haath {small} bhej dena.",
            "Gaadi ki servicing {day} karwani hai, slot book kar liya.",
            "Society clubhouse me {day} {clock} blood donation camp hai, aana zaroor.",
            # more look-alikes
            "Refund request approve ho gayi, {amount2} 5-7 din me bank me aa jayega, kuch karna nahi hai.",
            "{company} ne {small} refund UPI pe bhej diya, paise lene ke liye koi PIN ya QR nahi lagta.",
            "Mera {company} order ka refund {small} aa gaya, ab dusra order kar diya.",
            "Income tax return process ho gaya, refund {amount2} jaldi aayega.",
            "KYC {date} tak renew karna hai, bank app me profile me jaake kar lo ya branch chale jao.",
            "Aadhaar bank account se link ho gaya, ab subsidy direct aayegi.",
            "Account ka video KYC ho gaya, 5 minute laga bas.",
            "{name} kiraane ke liye {small} bhej de, kal wapas kar dunga.",
            "{relation} fees ke {amount2} bhej diye, receipt le lena.",
            "{name} ne UPI pe {small} maange hain movie ke, bhej deta hoon.",
            "Bhai koi bhi CBI ya customs wala call kare to kaat dena, 1930 pe complaint karna. Sab fraud hai.",
            "Parcel me drugs wale fraud call aate hain aajkal, {relation} ko bata diya hai uthana mat.",
            "Gaadi {vehicle} pe {small} ka traffic challan aaya tha, official app pe bhar diya.",
            "Personal loan {amount} account me aa gaya, EMI {date} se shuru hogi.",
            "EMI {amount2} {date} ko kategi, account me balance rakhna.",
            "Bijli ka bill auto debit nahi hua, {date} tak app pe jaake bhar dena.",
            "Mandir trust ko {small} daan diya, receipt mail pe aa gayi.",
            "{company} me job ke liye apply kiya hai, unhone bola koi fees nahi lagti.",
            "{stock} ka price alert aaya, {broker} app me dekh le.",
            "Policy ka bonus statement app me aa gaya, kuch bharna nahi hai.",
            "Delivery wale ne bola parcel {day} aayega, ghar pe rehna.",
            "Branch gaya tha, KYC documents verify ho gaye, account ab poora active hai.",
            "RBI rule ke hisaab se is saal KYC refresh karna hai, branch jaana padega. Bank waale phone nahi karte iske liye.",
            "Bank me mobile number update ho gaya, ab OTP naye number pe aayega.",
            "Return kiye saaman ka {small} refund account me aa gaya.",
            "Cancel order ke {small} wapas aa gaye account me, koi tension nahi.",
            "{name} ne trip ke kharche ke liye {small} ki request bheji hai, UPI app me dekh lo.",
            "{relation} hostel fees ke liye {amount2} bhej do, last date {date} hai.",
            "Bhai {small} bhej de, shop pe card nahi chal raha. Raat ko lauta dunga.",
            "Aadhaar money laundering wale call pe bharosa mat karna, asli police kabhi paise nahi maangti.",
            "Paise lene ke liye kabhi QR scan nahi karna aur PIN nahi daalna. Fraud ho to 1930 pe call karo.",
            "{date} ko line ke kaam ke liye bijli band rahegi {clock} se, message aaya hai.",
            "Offer letter mail pe aa gaya, joining {date} ko hai. Koi payment nahi maanga.",
            "Policy ka premium {amount2} bhar diya, receipt aa gayi.",
        ],
    },
}

TEMPLATES: list[tuple[str, str, str]] = [(tag, lang, tpl) for tag in CLASSES for lang, tpls in T[tag].items() for tpl in tpls]

# Made-up links on reserved names: scam and honest messages both carry them, so the domain is no clue.
LINKS = ["kyc-update-now.example/verify", "rbi-safe-account.example/kyc", "t-me.example/earn_daily_vip",
         "wa-me.example/91980000123", "sbi-kyc-update.example", "netbank-verify.test/login", "short.example/Rk7Tq",
         "lnk.test/Qx2kL", "vip-trade-group.example/join", "echallan-pay.test/fine", "parcel-redeliver.example/fee",
         "claim-prize.example/win", "bill-update.test/pay"]
NORMAL_LINKS = ["track.example/AB12cd", "shop.example/orders", "short.example/T9xQ", "lnk.test/ord77",
                "app.example/open", "bank.example/statement"]


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
        if lang == "hinglish" and k in HINGLISH_FILL and r.random() < 0.7:
            return r.choice(HINGLISH_FILL[k])
        if k in FILL:
            return r.choice(FILL[k])
        if k == "amount":
            return _amount(r, 1_000, 200_000)
        if k == "amount2":
            return _amount(r, 2_000, 90_000)
        if k == "small":
            return _amount(r, 50, 1_500)
        if k == "link":
            return r.choice(LINKS)
        if k == "nlink":
            return r.choice(NORMAL_LINKS)
        if k == "phone":  # obviously made up: four zeros in the middle
            return r.choice(["+91 ", "", "0"]) + f"{r.choice(['98', '97', '88', '79', '70'])}0000{r.randrange(1000, 9999)}"
        if k == "case":
            return r.choice(["CR/2026/", "FIR No. ", "Case ID "]) + str(r.randrange(1000, 99999))
        if k == "upi":
            return (f"{r.choice(['refund.desk', 'help.center', 'rahul.k', 'cs.support', 'neha.s', 'kirana.store', 'pay.society'])}"
                    f"{r.randrange(10, 99)}@{r.choice(['ybl', 'okaxis', 'paytm', 'ibl', 'oksbi'])}")
        if k == "otp":
            return f"{r.randrange(10**5, 10**6)}"
        if k == "acct":
            return f"{r.randrange(1000, 9999)}"
        if k == "ref":
            return f"{r.randrange(10**11, 10**12)}"
        if k == "order":
            return f"OD{r.randrange(10**9, 10**10)}"
        if k == "date":
            return f"{r.randrange(1, 29):02d}-{r.choice(['10', '11', '12'])}-26"
        if k == "vehicle":
            return f"{r.choice(['MH12', 'DL3C', 'KA05', 'UP32', 'RJ14'])} {r.choice(['AB', 'CK', 'MX', 'PT'])} {r.randrange(1000, 9999)}"
        if k == "hours":
            return r.choice(["2", "3", "6", "12", "24"])
        if k == "mins":
            return r.choice(["5", "10", "15", "20"])
        raise KeyError(k)
    return re.sub(r"\{(\w+)\}", slot, text)


LOOKALIKE = str.maketrans({"o": "0", "i": "1", "a": "@", "e": "3", "s": "$"})
EMOJI = ["🚨", "⚠️", "✅", "💰", "📦", "🙏", "👉", "🔥", "😊", "👍"]


def _vary(text: str, tag: str, r: random.Random) -> str:
    """Surface changes real messages have: casing, emoji, spacing, scammers' look-alike letters."""
    if r.random() < 0.06:
        text = text.upper()
    if tag != "normal" and r.random() < 0.05:
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


def generate(seed: int = 7, per_scam_template: int = 40, per_normal_template: int = 58) -> pd.DataFrame:
    """Up to `per_*_template` distinct messages per template (fewer when a template has few slots)."""
    r = random.Random(seed)
    rows, seen = [], set()
    for tid, (tag, lang, tpl) in enumerate(TEMPLATES):
        want = per_normal_template if tag == "normal" else per_scam_template
        got = 0
        for _ in range(want * 4):
            if got >= want:
                break
            text = _vary(_fill(tpl, lang, r), tag, r)
            if text in seen:
                continue
            seen.add(text)
            got += 1
            rows.append({"text": text, "tag": tag, "lang": lang, "template_id": tid, "synthetic": True})
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    df = generate(a.seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False, encoding="utf-8")
    print(f"{len(df):,} messages from {df.template_id.nunique()} templates -> {a.out}")
    print(f"normal share {(df.tag == 'normal').mean():.1%}")
    print(df.groupby(["tag", "lang"]).size().unstack(fill_value=0).to_string())
    print("templates per class:")
    print(df.groupby(["tag", "lang"]).template_id.nunique().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main()

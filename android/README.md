# android: Manjeet Singh (Android app)

The phone part of RUKO (zone 1). Branches: `android/*`. Kotlin, Jetpack Compose, Retrofit and kotlinx.serialization.
It is a demo only: no real money moves.

## Run it

1. Open this `android` folder in Android Studio and let Gradle sync.
2. In `local.properties`, set `PAYEE_SALT` to the same value as the backend `.env` (ask Jagdeep).
3. Plug in the phone with USB debugging on, then forward the API port:
   `adb reverse tcp:8000 tcp:8000`
4. Press Run. On the home screen, "Check server" calls `GET /health`.

From the command line: `./gradlew assembleDebug testDebugUnitTest`

## What is here

| Area | Files |
|---|---|
| Request models (mirror `schema/events.py`) | `net/Models.kt` |
| Payee hash (must equal the Python one) | `net/PayeeHash.kt` |
| Request builder (IST timestamps) | `net/RequestBuilder.kt` |
| Retrofit client, 1 s timeout, fail open | `net/RukoApi.kt` |
| Home, Pay, decision, PIN, Success | `ui/` |
| Contract tests | `app/src/test/.../ContractTest.kt` |

## Not built yet (guide steps 6 to 9)

Consent screen, ContextSensor (the request sends `"context": null` until then), debug panel,
the T1 to T4 alert screens, feedback calls, the lure scorer and Hindi strings.
`DecideResponse` field names are a guess until Jagdeep publishes `schema/events.py`.

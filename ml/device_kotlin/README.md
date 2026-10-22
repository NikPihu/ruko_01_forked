# On-device model for Cache Pay (for Manjeet)

| File | Goes to |
|---|---|
| `ml/model/artifacts/v0/device_model.json` | `android/app/src/main/assets/device_model.json` |
| `DeviceModel.kt` | `android/app/src/main/java/com/ruko/demo/signals/DeviceModel.kt` |
| `DeviceModelTest.kt` | `android/app/src/test/java/com/ruko/demo/signals/DeviceModelTest.kt` |

The test reads `device_model.json` and `device_vectors.json` straight from `ml/model/artifacts/v0`
(like `ContractTest` reads `contracts/`), and checks that every case scores exactly like Python
(`ml/model/device/score.py`). Needs only `kotlinx-serialization-json` and JUnit 4, both already in
the app.

## Using it
```kotlin
val model = DeviceModel.parse(context.assets.open("device_model.json").bufferedReader().use { it.readText() })
val result = model.score(features)   // Map<String, Double?>, null = could not measure
if (result.warn) { /* gentle local warning; never block the payment (CLAUDE.md rule 10) */ }
```

`features` are defined in `ml/dataset/device_features.py` (names, units, null rules). Most come from
readings the app already has: `CallReading`, `DeviceReading`, the lure hits, the watcher's episode
summary, the Pay-screen `SessionSignal`, and the payment history. Two rules matter most:
- a feature the phone could not measure is `null`, never `0` (CLAUDE.md rule 1);
- the device model runs only when at least one Scam Shield group is on.

Nothing in `result` leaves the phone today. Sending `p`, the family scores and the reasons needs a
contract field (`context.device_model`, ml/PLAN.md §12, Jagdeep).

Retrain and re-export: `python -m model.device.train --table ml/data/tables/dev.parquet` (see ml/PLAN.md).

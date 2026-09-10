# ShopMate buyer Android

Native Kotlin / Jetpack Compose app for the retailer's customers. The merchant workspace remains a separate Web client in this repository. Both connect to ShopMate API; CityBuddy owns accounts, inventory, orders, payments and refund receipts.

## Run

Install JDK 21 and Android SDK 36, set `JAVA_HOME` and `ANDROID_HOME`, then:

```sh
cd android
./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n io.shopmate.buyer/.MainActivity
```

Start the existing isolated ShopMate runtime and API first. In the Android emulator, the host API is `http://10.0.2.2:8101`. Use the demo buyer identity prepared by `scripts/local_runtime.py`; its password stays in the ignored runtime directory. Do not embed model keys, service credentials or buyer passwords in the app. Login offers a server URL field. Remote servers require HTTPS; debug cleartext access is limited to emulator/loopback hosts. Release builds have no cleartext exception.

## Shared core

`../shared` is a Kotlin Multiplatform module. Android consumes its JVM artifact; iOS consumes `BuyerCore.framework`. Both use the same SSE frame parser, message/card reducer, integer checkout contract and pending-write recovery policy. HTTP cancellation, UI state ownership and durable credential storage stay platform-specific.

Run shared tests with `./gradlew :shared:jvmTest`; on macOS, also run `:shared:iosSimulatorArm64Test :shared:linkDebugFrameworkIosSimulatorArm64`. The Swift interoperability check is in `../ios/Tests/CoreInterop.swift`.

## Client boundaries

- Normal shopping uses the buyer bearer without a conversation. The assistant creates a conversation only when a message is sent.
- A ViewModel owns screen state and the active stream through activity recreation. Wide windows show an assistant alongside shopping; compact windows use the assistant tab. Explicit stop cancels the HTTP stream. Process death restores saved server history rather than pretending generation continued.
- Checkout submits the exact integer-minor-unit quote and versions the customer reviewed. Price or inventory conflicts require a fresh quote and another confirmation.
- Before an idempotent write, the client durably saves its original key and body, scoped by server and authenticated owner. Unknown outcomes can retry that original intent. Payment and refund confirmation use the existing checkout/action identifier and server receipts.
- Bearer tokens are encrypted with an Android Keystore key; app backup is disabled. Passwords are never stored. Conversation content and long-term memory remain on the server.
- Product images use the existing API assets. Source notices remain in `web/public/products/IMAGE-CREDITS.md`.

This app does not claim that backend benchmark throughput measures mobile rendering or concurrent Agent capacity. Payment is the existing simulated payment flow.

# ShopMate buyer iOS

SwiftUI buyer client sharing the Kotlin Multiplatform `BuyerCore` with Android. The supported loop is login, product consultation/recommendations, explicit add-to-cart, reviewed checkout, simulated payment and saved receipts. Android remains the full buyer client, including seckill, refunds, profile/memory editing and deeper window/lifecycle coverage.

## Build on Apple Silicon

Install Xcode, JDK 21 and XcodeGen. Set `JAVA_HOME` to JDK 21, start the existing ShopMate API, then:

```sh
xcodegen generate --spec ios/project.yml
xcodebuild -project ios/ShopMate.xcodeproj -scheme ShopMate -configuration Debug -destination 'generic/platform=iOS Simulator' build
```

The pre-build phase compiles the matching Kotlin/Native framework. This project targets ARM64 simulator and device architectures. Open the generated `ios/ShopMate.xcodeproj` to choose an iPhone simulator and run. The local API defaults to `http://localhost:8101`; remote origins require HTTPS. Use the existing private demo credentials. Normal simulator ad-hoc signing is needed for Keychain; `CODE_SIGNING_ALLOWED=NO` is only for compile-only checks. For a physical iPhone, choose your own signing team and provide a reachable HTTPS endpoint; a simulator build is not a physical-device acceptance result.

Run `BuyerTests` on an iPhone simulator with the ShopMate scheme. Tests exercise actual Swift/Kotlin stream interoperability, truncated-stream handling, endpoint policy, and Keychain/pending-intent isolation.

## Shared and native responsibilities

- KMP owns SSE frame decoding, message/card reduction, exact checkout payloads and original-write recovery policy. Swift's byte-to-line adapter preserves empty lines (Foundation's convenience line sequence removes them); it does not implement a second SSE parser.
- SwiftUI owns presentation. Conversation updates are separate from shopping state. URLSession owns native cancellation; Keychain stores the bearer and a scoped atomic file preserves pending intents before sending.
- The model is remote. The phone contains no model, service or payment-signing credentials. The shopping and checkout endpoints use the same backend as Android.
- Unknown writes retain the original key/body. Explicit retry replays that intent; payment retries use the original checkout. Stopping generation does not undo committed business actions. Restart restores saved history, not an event-offset stream or a background model job.
- No full iOS feature parity or iOS rendering-capacity claim is made. Existing Java performance measurements remain server-only evidence.

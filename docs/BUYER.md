# Buyer Android app

The buyer entry point is a native Kotlin/Jetpack Compose app; merchants use the React/Vite Web app. These are the customer and staff interfaces for the same official store. They share the ShopMate API, with transactions and identity provided by CityBuddy. The old `/buyer` browser page has been retired.

## Start and sign in

Start the services using the [runtime guide](RUNTIME.md#run-locally), then install the app using the [Android build instructions](../android/README.md). The Android emulator connects to `http://10.0.2.2:8101`; the sign-in screen allows the API address to be configured.

| Demo account | Local password file |
| --- | --- |
| `shopmate-retail-buyer` | `.run/buyer_1_password` |
| `shopmate-retail-buyer-2` | `.run/buyer_2_password` |

Shopping is available after sign-in without creating a conversation. The first message creates the buyer conversation. The phone stores only the Keystore-encrypted token, current conversation identifier, and pending recovery requests scoped by service address and subject; passwords and model credentials are not stored on the phone.

## Suggested walkthrough

The quoted Chinese prompt and UI labels below are retained verbatim from the demo.

1. Browse the home page and categories, search for products, open details, and select a specific variant. The ACME demo catalog primarily uses English names; the assistant also accepts Chinese questions about uses, budgets, and combinations.
2. Ask “帮我比较两款咖啡机” and inspect streaming tool progress and the comparison card. You can also plan a bundle within a budget, read policies, or ask about fulfillment. Prices in recommendations and descriptions are not payment quotes.
3. Add available SKUs to the cart, adjust quantities, review the version, stock, and quote in integer minor units, then explicitly confirm order creation. A changed quote must be read and confirmed again.
4. Confirm simulated payment from the checkout record. Order, payment, and fulfillment states are displayed separately; successful payment does not imply shipment.
5. Review the amount and expiry in your own order or an assistant-prepared refund card, then confirm the refund request. `REQUESTED` means the request was accepted, not that funds arrived.
6. Open “我的” to view your profile, memory, and operation history. Memory supports corrections, forgetting individual entries, and clearing all entries after explicit confirmation. Clearing memory does not delete orders or the cart.

Delivery estimates use actual SKU quantities and separately display currency, cost, and timing. Product payments currently do not charge delivery fees; a consultation estimate is not a purchased delivery service.

## Interruption and recovery

The ViewModel retains the current task across view reconstruction. Wide windows can show shopping and the assistant together; narrow windows use a separate assistant page. Stopping generation cancels the HTTP stream without undoing committed cart changes, orders, or refund requests. After a process restart, saved conversations are read from the server; continued background generation is not assumed.

Before an idempotent write, the phone saves the original key and request body. If the response is missing, the operation remains marked “待核对” (verbatim UI label: pending verification). Recovery first queries the original receipt; only after the user confirms continuation does it retry the original intent with the same key. Payment follows the original checkout, and refund confirmation replays the original pending action. Switching chats does not change command ownership.

## Data boundaries

Java/MySQL is authoritative for orders, prices, stock, payment, and approvals. ShopMate SQLite stores single-instance conversations, memory, runtime state, and recovery records; it is not the seckill order database. Conversations, commands, and memory are isolated between both buyers and the merchant identity.

Historical backend throughput does not establish phone frame rates, concurrent agent capacity, or production user scale. Android builds, device tests, and interaction records are separate from historical model-quality evaluations.

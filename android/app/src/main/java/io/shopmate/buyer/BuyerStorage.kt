package io.shopmate.buyer

/** Device-owned state; conversations and authoritative business receipts remain on the server. */
interface BuyerStorage {
    var endpoint: String
    var commerceEndpoint: String
    val owner: String
    var conversation: String?
    fun token(): String?
    fun login(owner: String, token: String)
    fun logout()
    fun tickets(): List<SeckillTicket>
    fun saveTickets(values: List<SeckillTicket>)
    fun pending(): List<PendingWrite>
    fun savePending(values: List<PendingWrite>)
}

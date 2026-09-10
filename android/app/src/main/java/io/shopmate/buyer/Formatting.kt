package io.shopmate.buyer

import java.math.BigDecimal
import java.text.NumberFormat
import java.util.Currency
import java.util.Locale

fun money(minor: Long?, currency: String? = "CNY"): String {
    if (minor == null || currency == null) return "金额待确认"
    return NumberFormat.getCurrencyInstance(Locale.CHINA)
        .apply { this.currency = Currency.getInstance(currency) }
        .format(BigDecimal.valueOf(minor, 2))
}

fun decimalMoney(value: Double, currency: String = "CNY") =
    money(BigDecimal.valueOf(value).movePointRight(2).longValueExact(), currency)

fun refundMinor(raw: String): Long {
    require(Regex("(0|[1-9][0-9]*)(\\.[0-9]{1,2})?").matches(raw)) { "金额最多两位小数" }
    return BigDecimal(raw).movePointRight(2).longValueExact().also { require(it > 0) { "请输入正数金额" } }
}

fun localTime(raw: String): String =
    try {
        java.time.OffsetDateTime.parse(raw)
            .atZoneSameInstant(java.time.ZoneId.systemDefault())
            .format(java.time.format.DateTimeFormatter.ofPattern("MM-dd HH:mm"))
    } catch (_: java.time.format.DateTimeParseException) {
        raw
    }

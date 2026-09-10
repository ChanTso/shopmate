package io.shopmate.buyer

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlinx.serialization.encodeToString

/**
 * Business receipts remain on the server. Local intent survives process death before a response.
 */
class DeviceStore(context: Context) {
    private val prefs = context.getSharedPreferences("buyer", Context.MODE_PRIVATE)
    private val key: SecretKey by lazy {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("buyer-token", null) as? SecretKey)
            ?: KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
                .apply {
                    init(
                        KeyGenParameterSpec.Builder(
                                "buyer-token",
                                KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
                            )
                            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                            .build()
                    )
                }
                .generateKey()
    }
    var endpoint: String
        get() = prefs.getString("endpoint", "http://10.0.2.2:8101")!!
        set(value) {
            check(prefs.edit().putString("endpoint", value).commit())
        }

    val owner: String
        get() = prefs.getString("owner", "")!!

    fun token(): String? {
        val raw = prefs.getString("token", null) ?: return null
        return try {
            val bytes = Base64.decode(raw, Base64.NO_WRAP)
            Cipher.getInstance("AES/GCM/NoPadding")
                .apply {
                    init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, bytes.copyOfRange(0, 12)))
                }
                .doFinal(bytes.copyOfRange(12, bytes.size))
                .toString(Charsets.UTF_8)
        } catch (_: java.security.GeneralSecurityException) {
            logout()
            null
        }
    }

    fun login(owner: String, token: String) {
        val cipher =
            Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
        val encoded =
            Base64.encodeToString(cipher.iv + cipher.doFinal(token.toByteArray()), Base64.NO_WRAP)
        check(prefs.edit().putString("owner", owner).putString("token", encoded).commit())
    }

    fun logout() {
        check(prefs.edit().remove("token").remove("owner").commit())
    }

    private fun scoped(name: String) = "$endpoint|$owner|$name"

    var conversation: String?
        get() = prefs.getString(scoped("conversation"), null)
        set(value) {
            check(prefs.edit().putString(scoped("conversation"), value).commit())
        }

    fun pending(): List<PendingWrite> =
        prefs.getString(scoped("pending"), null)?.let { wireJson.decodeFromString(it) }
            ?: emptyList()

    fun savePending(values: List<PendingWrite>) {
        check(prefs.edit().putString(scoped("pending"), wireJson.encodeToString(values)).commit()) {
            "无法保存操作，请检查设备存储"
        }
    }
}

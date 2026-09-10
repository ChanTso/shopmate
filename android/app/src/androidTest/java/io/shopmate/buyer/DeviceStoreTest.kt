package io.shopmate.buyer

import android.content.Context
import android.content.ContextWrapper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DeviceStoreTest {
    @Test
    fun pendingIntentSurvivesRecreationAndRemainsOwnerScoped() {
        val base = InstrumentationRegistry.getInstrumentation().targetContext
        val isolated =
            object : ContextWrapper(base) {
                override fun getSharedPreferences(name: String, mode: Int) =
                    base.getSharedPreferences("test-$name", mode)
            }
        isolated.getSharedPreferences("buyer", Context.MODE_PRIVATE).edit().clear().commit()
        try {
            val store = DeviceStore(isolated)
            store.login("buyer-a", "noncredential-unit-token")
            val intent =
                PendingWrite(
                    "original-key",
                    "/checkouts",
                    buildJsonObject {
                        put("request_key", "original-key")
                        put("expectedCartVersion", 12)
                    },
                )
            store.savePending(listOf(intent))
            store.conversation = "conversation-a"
            val restored = DeviceStore(isolated)
            assertEquals("noncredential-unit-token", restored.token())
            assertEquals(listOf(intent), restored.pending())
            assertEquals("conversation-a", restored.conversation)
            restored.logout()
            restored.login("buyer-b", "other-noncredential")
            assertTrue(restored.pending().isEmpty())
            assertNull(restored.conversation)
            restored.logout()
            restored.login("buyer-a", "new-noncredential")
            assertEquals(listOf(intent), restored.pending())
            assertEquals("conversation-a", restored.conversation)
        } finally {
            isolated.getSharedPreferences("buyer", Context.MODE_PRIVATE).edit().clear().commit()
        }
    }
}

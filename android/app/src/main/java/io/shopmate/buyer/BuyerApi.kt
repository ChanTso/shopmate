package io.shopmate.buyer

import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.*
import okhttp3.*
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.toRequestBody

private fun serviceRoot(value: String): String {
            val parsed = value.trim().trimEnd('/').toHttpUrl()
            require(
                parsed.username.isEmpty() &&
                    parsed.password.isEmpty() &&
                    parsed.query == null &&
                    parsed.fragment == null &&
                    parsed.encodedPath == "/"
            ) {
                "请输入不含路径的服务地址"
            }
            require(parsed.isHttps || parsed.host in setOf("10.0.2.2", "localhost", "127.0.0.1")) {
                "远程服务须使用 HTTPS"
            }
    return value.trim().trimEnd('/')
}

class ApiFailure(val status: Int, val category: String, message: String) : IOException(message)

class BuyerApi(
    private val client: OkHttpClient =
        OkHttpClient.Builder()
            .connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(45, TimeUnit.SECONDS)
            .build()
) {
    var root = "http://10.0.2.2:8101"
        set(value) { field = serviceRoot(value) }
    var commerceRoot = "http://10.0.2.2:9082"
        set(value) { field = serviceRoot(value) }

    var token: String? = null

    fun asset(path: String?) = path?.let { if (it.startsWith('/')) root + it else it }

    private fun request(path: String, body: JsonObject?, method: String): Request =
        Request.Builder()
            .url("$root/api/buyer$path")
            .apply { token?.let { header("Authorization", "Bearer $it") } }
            .method(method, body?.toString()?.toRequestBody("application/json".toMediaType()))
            .build()

    private fun failure(response: Response): ApiFailure {
        val payload = runCatching {
            wireJson.parseToJsonElement(response.body?.string().orEmpty()).jsonObject
        }.getOrDefault(JsonObject(emptyMap()))
        val message =
            when (response.code) {
                401 -> "账号密码不正确或登录已过期，请重新登录"
                403 -> "当前账号无权执行此操作"
                404 -> "记录不存在，请刷新后核对"
                429 -> "助手当前繁忙，请稍后再试"
                409 -> when (payload.text("category")) {
                    "stale_cart" -> "购物车已更新，请刷新后重新核对商品和数量。"
                    "stale_quote" -> "商品报价已变化，请刷新后重新确认价格。"
                    "unknown_cart" -> "上次购物车操作尚待核对，请先恢复原操作。"
                    else -> payload.text("detail", payload.text("message", "操作与当前状态冲突，请刷新核对"))
                }
                else ->
                    payload.text("detail", payload.text("message", "请求未完成（${response.code}），请刷新核对"))
            }
        return ApiFailure(response.code, payload.text("category"), message.take(600))
    }

    suspend fun json(
        path: String,
        body: JsonObject? = null,
        method: String = if (body == null) "GET" else "POST",
    ): JsonObject = execute(request(path, body, method))

    suspend fun seckill(path: String, body: JsonObject? = null, key: String? = null): JsonObject =
        execute(Request.Builder().url("$commerceRoot/api$path")
            .apply {
                token?.let { header("Authorization", "Bearer $it") }
                key?.let { header("Idempotency-Key", it) }
            }
            .method(if (body == null) "GET" else "POST",
                body?.toString()?.toRequestBody("application/json".toMediaType()))
            .build(), allowRejectedReservation = key != null)

    private suspend fun execute(request: Request, allowRejectedReservation: Boolean = false): JsonObject = suspendCancellableCoroutine { continuation ->
        val call = client.newCall(request)
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(
            object : Callback {
                override fun onFailure(call: Call, e: IOException) {
                    if (!continuation.isCancelled) continuation.resumeWithException(e)
                }

                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        val result = runCatching {
                            if (!it.isSuccessful) {
                                val rejected = if (allowRejectedReservation && it.code == 409)
                                    runCatching { wireJson.parseToJsonElement(it.peekBody(65536).string()).jsonObject }.getOrNull()
                                    else null
                                if (rejected?.text("state") != "REJECTED" || rejected.text("reservationId").isBlank())
                                    throw failure(it)
                            }
                            wireJson
                                .parseToJsonElement(it.body?.string() ?: throw IOException("响应为空"))
                                .jsonObject
                        }
                        if (!continuation.isCancelled)
                            result.fold(continuation::resume, continuation::resumeWithException)
                    }
                }
            }
        )
    }

    fun chat(id: String, message: String, page: JsonObject): Flow<StreamEvent> = callbackFlow {
        val streamClient = client.newBuilder().readTimeout(0, TimeUnit.SECONDS).build()
        val call =
            streamClient.newCall(
                request(
                    "/conversations/$id/chat",
                    buildJsonObject {
                        put("message", message)
                        put("page", page)
                    },
                    "POST",
                )
            )
        val reader =
            launch(Dispatchers.IO) {
                try {
                    call.execute().use { response ->
                        if (!response.isSuccessful) throw failure(response)
                        val source = response.body?.source() ?: throw IOException("流式响应为空")
                        val decoder = StreamDecoder()
                        while (!source.exhausted()) {
                            val line = source.readUtf8Line() ?: break
                            decoder.line(line)?.let { send(it) }
                        }
                        try {
                            decoder.finish()
                        } catch (e: IllegalStateException) {
                            throw IOException(e.message, e)
                        }
                    }
                    close()
                } catch (e: IOException) {
                    close(e)
                } catch (e: kotlinx.serialization.SerializationException) {
                    close(IOException("助手响应格式异常，请恢复对话", e))
                }
            }
        awaitClose {
            call.cancel()
            reader.cancel()
        }
    }
}

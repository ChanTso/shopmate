package io.shopmate.buyer

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
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

class ApiFailure(val status: Int, val category: String, message: String) : IOException(message)

class BuyerApi(private val client: OkHttpClient = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(45, TimeUnit.SECONDS).build()) {
    var root = "http://10.0.2.2:8101"
        set(value) {
            val parsed = value.trim().trimEnd('/').toHttpUrl()
            require(parsed.username.isEmpty() && parsed.password.isEmpty() && parsed.query == null && parsed.fragment == null && parsed.encodedPath == "/") { "请输入不含路径的服务地址" }
            require(parsed.isHttps || parsed.host in setOf("10.0.2.2", "localhost", "127.0.0.1")) { "远程服务须使用 HTTPS" }
            field = value.trim().trimEnd('/')
        }
    var token: String? = null
    fun asset(path: String?) = path?.let { if (it.startsWith('/')) root + it else it }
    private fun request(path: String, body: JsonObject?, method: String): Request = Request.Builder()
        .url("$root/api/buyer$path")
        .apply { token?.let { header("Authorization", "Bearer $it") } }
        .method(method, body?.toString()?.toRequestBody("application/json".toMediaType())).build()
    private fun failure(response: Response): ApiFailure {
        val payload = runCatching { wireJson.parseToJsonElement(response.body?.string().orEmpty()).jsonObject }.getOrDefault(JsonObject(emptyMap()))
        val message = when(response.code) {
            401 -> "账号密码不正确或登录已过期，请重新登录"
            403 -> "当前账号无权执行此操作"
            404 -> "记录不存在，请刷新后核对"
            429 -> "助手当前繁忙，请稍后再试"
            else -> payload.text("detail", payload.text("message", "请求未完成（${response.code}），请刷新核对"))
        }
        return ApiFailure(response.code, payload.text("category"), message.take(600))
    }
    suspend fun json(path: String, body: JsonObject? = null, method: String = if (body == null) "GET" else "POST"): JsonObject =
        suspendCancellableCoroutine { continuation ->
            val call = client.newCall(request(path, body, method))
            continuation.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) { if (!continuation.isCancelled) continuation.resumeWithException(e) }
                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        val result = runCatching {
                            if (!it.isSuccessful) throw failure(it)
                            wireJson.parseToJsonElement(it.body?.string() ?: throw IOException("响应为空")).jsonObject
                        }
                        if (!continuation.isCancelled) result.fold(continuation::resume, continuation::resumeWithException)
                    }
                }
            })
        }

    fun chat(id: String, message: String, page: JsonObject): Flow<StreamEvent> = callbackFlow {
        val streamClient = client.newBuilder().readTimeout(0, TimeUnit.SECONDS).build()
        val call = streamClient.newCall(request("/conversations/$id/chat", buildJsonObject { put("message", message); put("page", page) }, "POST"))
        val reader = launch(Dispatchers.IO) {
            try {
                call.execute().use { response ->
                    if (!response.isSuccessful) throw failure(response)
                    val source = response.body?.source() ?: throw IOException("流式响应为空")
                    var type = ""
                    val data = mutableListOf<String>()
                    var terminal = false
                    while (!source.exhausted()) {
                        val line = source.readUtf8Line() ?: break
                        when {
                            line.startsWith("event:") -> type = line.substringAfter(':').trim()
                            line.startsWith("data:") -> data.add(line.substringAfter(':').trimStart())
                            line.isEmpty() && data.isNotEmpty() -> {
                                val event = StreamEvent(type, wireJson.parseToJsonElement(data.joinToString("\n")).jsonObject)
                                send(event)
                                if (type == "turn_complete" || type == "error") terminal = true
                                type = ""; data.clear()
                            }
                        }
                    }
                    if (!terminal) throw IOException("连接中断，请恢复对话并核对订单或购物车")
                }
                close()
            } catch (e: IOException) { close(e) }
              catch (e: kotlinx.serialization.SerializationException) { close(IOException("助手响应格式异常，请恢复对话", e)) }
        }
        awaitClose { call.cancel(); reader.cancel() }
    }
}

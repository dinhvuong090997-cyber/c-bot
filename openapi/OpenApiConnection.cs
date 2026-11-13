using System.Net.WebSockets;
using System.Text.Json;

// One owner per connection. Unsolicited quotes/executions are observed while requests drain the socket.
interface IExecutionConnection : IDisposable
{
    Action<int, JsonElement>? Received { get; set; }
    Task Connect(AppCredentials app, TokenSet tokens, long accountId = 48463366L, bool live = false);
    Task<JsonElement> Request(int type, object payload, int expected);
}

sealed class OpenApiConnection : IExecutionConnection
{
    readonly ClientWebSocket socket = new();
    DateTime nextRequest, lastHeartbeat;
    public Action<int, JsonElement>? Received { get; set; }
    public async Task Connect(AppCredentials app, TokenSet tokens, long accountId = 48463366L, bool live = false)
    {
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        await socket.ConnectAsync(new Uri(live ? "wss://live.ctraderapi.com:5036/" : "wss://demo.ctraderapi.com:5036/"), deadline.Token);
        await Request(2100, new { clientId = app.ClientId, clientSecret = app.ClientSecret }, 2101);
        if (accountId != 0) await Request(2102, new { ctidTraderAccountId = accountId, accessToken = tokens.AccessToken }, 2103);
    }
    public async Task<JsonElement> Request(int type, object payload, int expected)
    {
        var delay = nextRequest - DateTime.UtcNow;
        if (delay > TimeSpan.Zero) await Task.Delay(delay);
        nextRequest = DateTime.UtcNow.AddMilliseconds(250); // below the 5 historical requests/sec limit
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        var id = Guid.NewGuid().ToString("N");
        if (DateTime.UtcNow - lastHeartbeat >= TimeSpan.FromSeconds(8))
        {
            await socket.SendAsync(JsonSerializer.SerializeToUtf8Bytes(new { payloadType = 51, payload = new { } }).AsMemory(), WebSocketMessageType.Text, true, deadline.Token);
            lastHeartbeat = DateTime.UtcNow;
        }
        var body = JsonSerializer.SerializeToUtf8Bytes(new { clientMsgId = id, payloadType = type, payload });
        await socket.SendAsync(body.AsMemory(), WebSocketMessageType.Text, true, deadline.Token);
        while (true)
        {
            using var message = new MemoryStream();
            var buffer = new byte[32768];
            ValueWebSocketReceiveResult frame;
            do
            {
                frame = await socket.ReceiveAsync(buffer.AsMemory(), deadline.Token);
                if (frame.MessageType == WebSocketMessageType.Close) throw new IOException("cTrader closed the connection.");
                if (frame.MessageType != WebSocketMessageType.Text || message.Length + frame.Count > 32 * 1024 * 1024)
                    throw new IOException("Invalid API message.");
                message.Write(buffer, 0, frame.Count);
            } while (!frame.EndOfMessage);
            using var document = JsonDocument.Parse(message.ToArray());
            var root = document.RootElement;
            var messageType = root.GetProperty("payloadType").GetInt32();
            var eventPayload = root.TryGetProperty("payload", out var ep) ? ep : JsonSerializer.SerializeToElement(new { });
            Received?.Invoke(messageType, eventPayload);
            if (messageType is 2147 or 2148 or 2164) throw new IOException("cTrader authorization disconnected. Reconnect before restarting.");
            if (!root.TryGetProperty("clientMsgId", out var responseId) || responseId.GetString() != id) continue;
            if (root.GetProperty("payloadType").GetInt32() != expected)
            {
                var error = root.TryGetProperty("payload", out var p) && p.TryGetProperty("errorCode", out var c) ? c.GetString() : "UNKNOWN";
                throw new IOException("cTrader request " + type + " rejected: " + error);
            }
            return root.TryGetProperty("payload", out var response) ? response.Clone() : JsonSerializer.SerializeToElement(new { });
        }
    }
    public void Dispose() => socket.Dispose();
}

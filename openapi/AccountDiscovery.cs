using System.Net.WebSockets;
using System.Text.Json;

static class AccountDiscovery
{
    public static async Task List(AppCredentials credentials, TokenSet tokens)
    {
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        using var socket = new ClientWebSocket();
        await socket.ConnectAsync(new Uri("wss://demo.ctraderapi.com:5036/"), timeout.Token);
        async Task<JsonElement> Request(int type, object payload, int expected)
        {
            var id = Guid.NewGuid().ToString("N");
            var body = JsonSerializer.SerializeToUtf8Bytes(new { clientMsgId = id, payloadType = type, payload });
            await socket.SendAsync(body.AsMemory(), WebSocketMessageType.Text, true, timeout.Token);
            while (true)
            {
                using var message = new MemoryStream();
                var buffer = new byte[8192];
                ValueWebSocketReceiveResult frame;
                do
                {
                    frame = await socket.ReceiveAsync(buffer.AsMemory(), timeout.Token);
                    if (frame.MessageType == WebSocketMessageType.Close)
                        throw new IOException("cTrader đã đóng kết nối.");
                    if (frame.MessageType != WebSocketMessageType.Text || message.Length + frame.Count > 1024 * 1024)
                        throw new IOException("Invalid API message.");
                    message.Write(buffer, 0, frame.Count);
                } while (!frame.EndOfMessage);
                using var document = JsonDocument.Parse(message.ToArray());
                var root = document.RootElement;
                if (root.TryGetProperty("clientMsgId", out var messageId) && messageId.GetString() == id)
                {
                    if (root.GetProperty("payloadType").GetInt32() != expected)
                        throw new IOException("cTrader từ chối yêu cầu. Kiểm tra quyền của ứng dụng và token.");
                    return root.TryGetProperty("payload", out var responsePayload)
                        ? responsePayload.Clone() : JsonSerializer.SerializeToElement(new { });
                }
            }
        }
        await Request(2100, new { clientId = credentials.ClientId, clientSecret = credentials.ClientSecret }, 2101);
        var result = await Request(2149, new { accessToken = tokens.AccessToken }, 2150);
        Console.WriteLine("Danh sách tài khoản được cấp quyền:");
        if (result.TryGetProperty("ctidTraderAccount", out var accounts))
            foreach (var account in accounts.EnumerateArray())
            {
                // Access token in the response must never reach stdout.
                Console.WriteLine(JsonSerializer.Serialize(new
                {
                    ctidTraderAccountId = account.GetProperty("ctidTraderAccountId").ToString(),
                    traderLogin = account.TryGetProperty("traderLogin", out var login) ? login.ToString() : "",
                    broker = account.TryGetProperty("brokerTitleShort", out var broker) ? broker.GetString() : "",
                    isLive = account.TryGetProperty("isLive", out var live) && live.GetBoolean()
                }));
            }
    }
}

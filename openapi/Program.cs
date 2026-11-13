using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

[assembly: System.Runtime.Versioning.SupportedOSPlatform("linux")]

const string Redirect = "http://localhost:8787/callback";
var directory = Environment.GetEnvironmentVariable("XAU_CONFIG_DIR")
    ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".config", "fxpro-openapi");
Directory.CreateDirectory(directory);
File.SetUnixFileMode(directory, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
var configPath = Path.Combine(directory, "app.json");
var tokenPath = Path.Combine(directory, "tokens.json");
var jsonOptions = new JsonSerializerOptions { WriteIndented = true };
void SavePrivate(string path, object data)
{
    var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
    using (var file = new FileStream(temporary, new FileStreamOptions
    {
        Mode = FileMode.CreateNew, Access = FileAccess.Write,
        UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite
    }))
    {
        JsonSerializer.Serialize(file, data, jsonOptions);
        file.Flush(true);
    }
    File.Move(temporary, path, true);
}
string ReadSecret()
{
    var result = new StringBuilder();
    while (true)
    {
        var key = Console.ReadKey(true);
        if (key.Key == ConsoleKey.Enter) break;
        if (key.Key == ConsoleKey.Backspace)
        {
            if (result.Length > 0) result.Length--;
        }
        else if (!char.IsControl(key.KeyChar)) result.Append(key.KeyChar);
    }
    Console.WriteLine();
    return result.ToString();
}

if (args.FirstOrDefault() == "setup")
{
    Console.Write("Client ID: ");
    var id = Console.ReadLine()?.Trim();
    Console.Write("Client Secret (ẩn ký tự): ");
    var secret = ReadSecret();
    if (string.IsNullOrWhiteSpace(id) || string.IsNullOrWhiteSpace(secret))
        throw new InvalidOperationException("Client ID và Client Secret cần có giá trị.");
    SavePrivate(configPath, new AppCredentials(id, secret));
    Console.WriteLine("Đã lưu thông tin ứng dụng. Redirect URI cần đăng ký: " + Redirect);
    return;
}
if (args.FirstOrDefault() == "inspect-execution")
{
    var selected = JsonSerializer.Deserialize<ExecutionConfig>(File.ReadAllText(Path.Combine(directory, "execution-config.json")), ExecutionFiles.Json)!;
    using var broker = await ExecutionBroker.Open(directory, selected.Account.Id);
    var now = DateTimeOffset.UtcNow;
    var reconcile = await broker.Reconcile();
    var orders = await broker.Api.Request(2175, new { ctidTraderAccountId = broker.Account.Id, fromTimestamp = now.AddHours(-1).ToUnixTimeMilliseconds(), toTimestamp = now.ToUnixTimeMilliseconds() }, 2176);
    var deals = await broker.Api.Request(2133, new { ctidTraderAccountId = broker.Account.Id, fromTimestamp = now.AddHours(-1).ToUnixTimeMilliseconds(), toTimestamp = now.ToUnixTimeMilliseconds(), maxRows = 100 }, 2134);
    Console.WriteLine(JsonSerializer.Serialize(new { capturedUtc = now, broker.Account.Login, broker.Balance, reconcile, orders, deals }));
    return;
}
if (args.FirstOrDefault() == "check-execution-history")
{
    var selected = JsonSerializer.Deserialize<ExecutionConfig>(File.ReadAllText(Path.Combine(directory, "execution-config.json")), ExecutionFiles.Json)!;
    selected.Validate();
    using var broker = await ExecutionBroker.Open(directory, selected.Account.Id);
    var signal = new ExecutionSignal(selected);
    long count = await TickHistory.Warmup(broker, selected, DateTime.UtcNow,
        q => signal.Observe(q.Time, q.Bid, q.Ask), Console.WriteLine, () => false);
    Console.WriteLine(JsonSerializer.Serialize(new { quotes = count, profileDate = signal.Profile(DateTime.UtcNow)?.Date.ToString("yyyy-MM-dd"), preflight = "history only; no orders sent" }));
    return;
}
if (args.FirstOrDefault() == "check-execution-account")
{
    using var broker = await ExecutionBroker.Open(directory, args.Length > 1 ? long.Parse(args[1]) : 48463366L);
    var positions = await broker.Reconcile();
    int quotes = 0; bool timestamped = false;
    broker.Api.Received = (type, payload) => { if (type == 2131) { quotes++; timestamped |= payload.TryGetProperty("timestamp", out _); } };
    await broker.Api.Request(2127, new { ctidTraderAccountId = broker.Account.Id, symbolId = new[] { broker.SymbolId }, subscribeToSpotTimestamp = true }, 2128);
    for (int i = 0; i < 4; i++) { await Task.Delay(500); await broker.Reconcile(); }
    var margin = await broker.Api.Request(2139, new { ctidTraderAccountId = broker.Account.Id, symbolId = broker.SymbolId, volume = new[] { ExecutionFiles.Integer(broker.Symbol, "minVolume") } }, 2140);
    Console.WriteLine(JsonSerializer.Serialize(new { broker.Account.Login, broker.Account.Broker, broker.SymbolId, broker.Balance, hasExposure = ExecutionBroker.HasExposure(positions), quotes, timestamped, marginAvailable = ExecutionFiles.Items(margin, "margin").Any(), preflight = "read-only; no order sent" }));
    return;
}
if (args.FirstOrDefault() == "check-execution")
{
    await ExecutionChecks.Run();
    return;
}
if (args.FirstOrDefault() == "check-market")
{
    await MarketChecks.Run();
    return;
}
if (args.FirstOrDefault() == "check-backtest")
{
    BacktestChecks.Run();
    return;
}
if (args.FirstOrDefault() == "backtest")
{
    BacktestRunner.Run(args);
    return;
}
if (args.FirstOrDefault() == "worker")
{
    await ExecutionService.Run(directory);
    return;
}
if (args.FirstOrDefault() == "check-execution-service")
{
    await ExecutionServiceChecks.Run();
    return;
}
if (args.FirstOrDefault() == "dashboard-preview")
{
    await DashboardServer.Run(directory,8791,true);
    return;
}
if (args.FirstOrDefault() == "dashboard")
{
    await DashboardServer.Run(directory);
    return;
}
AppCredentials? credentials = File.Exists(configPath)
    ? JsonSerializer.Deserialize<AppCredentials>(File.ReadAllText(configPath)) : null;
using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(20) };
async Task<TokenSet> Exchange(Dictionary<string, string> fields)
{
    if (credentials is null) throw new InvalidOperationException("Configure app first.");
    fields["client_id"] = credentials.ClientId;
    fields["client_secret"] = credentials.ClientSecret;
    var query = string.Join("&", fields.Select(pair =>
        Uri.EscapeDataString(pair.Key) + "=" + Uri.EscapeDataString(pair.Value)));
    using var request = new HttpRequestMessage(HttpMethod.Post, "https://openapi.ctrader.com/apps/token?" + query);
    request.Headers.Accept.ParseAdd("application/json");
    using var response = await http.SendAsync(request);
    using var doc = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
    var root = doc.RootElement;
    if (!response.IsSuccessStatusCode || !root.TryGetProperty("accessToken", out var access) ||
        string.IsNullOrEmpty(access.GetString()))
        throw new InvalidOperationException("cTrader từ chối cấp token. Kiểm tra app, redirect URI và quyền đã cấp.");
    var tokens = new TokenSet(access.GetString()!, root.GetProperty("refreshToken").GetString()!,
        DateTimeOffset.UtcNow.AddSeconds(root.GetProperty("expiresIn").GetInt64()));
    SavePrivate(tokenPath, tokens);
    return tokens;
}
if (args.FirstOrDefault() is "accounts" or "export")
{
    if (!File.Exists(tokenPath))
        throw new InvalidOperationException("Chạy ./api connect trước.");
    var tokens = JsonSerializer.Deserialize<TokenSet>(File.ReadAllText(tokenPath))!;
    if (tokens.ExpiresAt <= DateTimeOffset.UtcNow.AddMinutes(5))
        tokens = await Exchange(new() { ["grant_type"] = "refresh_token", ["refresh_token"] = tokens.RefreshToken });
    if (credentials is null) throw new InvalidOperationException("Chạy ./api setup trước.");
    if (args[0] == "export") await DataExport.Run(credentials, tokens, args);
    else await AccountDiscovery.List(credentials, tokens);
    return;
}

if (args.FirstOrDefault() != "connect")
{
    Console.WriteLine("Dùng ./api setup, connect, start, accounts, export START END, backtest START END hoặc check-backtest.");
    return;
}
using var listener = new HttpListener();
listener.Prefixes.Add("http://+:8787/");
listener.Start();
var nonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
string? authorizationSession = null;
var authorizationExpires = DateTimeOffset.MinValue;
Console.WriteLine("Trang kết nối đang chạy tại http://localhost:8787/");
while (true)
{
    var context = await listener.GetContextAsync();
    var request = context.Request;
    var response = context.Response;
    response.Headers["Cache-Control"] = "no-store";
    response.Headers["Referrer-Policy"] = "no-referrer";
    response.Headers["X-Content-Type-Options"] = "nosniff";
    response.Headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'";
    string message;
    var html = false;
    try
    {
        if (request.Url?.Host != "localhost")
        {
            response.StatusCode = 403;
            message = "Host không hợp lệ.";
        }
        else
        {
            var path = request.Url.AbsolutePath;
            var validSession = request.Cookies["setup_session"]?.Value == nonce;
            if (path == "/" && request.HttpMethod == "GET")
            {
                response.Headers.Add("Set-Cookie", $"setup_session={nonce}; Path=/; HttpOnly; SameSite=Strict");
                message = ConnectionPage.Render(nonce, credentials is not null, File.Exists(tokenPath));
                html = true;
            }
            else if (path == "/setup" && request.HttpMethod == "POST" && validSession
                     && request.ContentLength64 is > 0 and <= 8192)
            {
                using var reader = new StreamReader(request.InputStream);
                var fields = (await reader.ReadToEndAsync()).Split('&')
                    .Select(part => part.Split('=', 2))
                    .Where(part => part.Length == 2)
                    .ToDictionary(part => WebUtility.UrlDecode(part[0]), part => WebUtility.UrlDecode(part[1]));
                if (fields.GetValueOrDefault("csrf") != nonce)
                    throw new InvalidOperationException("Invalid session.");
                var id = fields.GetValueOrDefault("clientId")?.Trim();
                var secret = fields.GetValueOrDefault("clientSecret")?.Trim();
                if (string.IsNullOrWhiteSpace(id) || string.IsNullOrWhiteSpace(secret))
                    throw new InvalidOperationException("Missing credentials.");
                credentials = new(id, secret);
                SavePrivate(configPath, credentials);
                response.Redirect("/");
                response.Close();
                continue;
            }
            else if (path == "/connect" && request.HttpMethod == "POST" && validSession && credentials is not null)
            {
                using var reader = new StreamReader(request.InputStream);
                if (request.ContentLength64 is <= 0 or > 256 ||
                    await reader.ReadToEndAsync() != "csrf=" + nonce)
                    throw new InvalidOperationException("Invalid session.");
                authorizationSession = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
                authorizationExpires = DateTimeOffset.UtcNow.AddMinutes(10);
                response.Headers.Add("Set-Cookie", $"oauth_session={authorizationSession}; Path=/; HttpOnly; SameSite=Lax");
                var url = "https://id.ctrader.com/my/settings/openapi/grantingaccess/"
                    + "?client_id=" + Uri.EscapeDataString(credentials.ClientId)
                    + "&redirect_uri=" + Uri.EscapeDataString(Redirect) + "&scope=trading&product=web";
                response.Redirect(url);
                response.Close();
                continue;
            }
            else if (path == "/callback" && request.HttpMethod == "GET" &&
                     authorizationSession is not null && DateTimeOffset.UtcNow < authorizationExpires &&
                     request.Cookies["oauth_session"]?.Value == authorizationSession &&
                     request.QueryString["code"] is { Length: > 0 } code)
            {
                authorizationSession = null;
                await Exchange(new() { ["grant_type"] = "authorization_code", ["code"] = code, ["redirect_uri"] = Redirect });
                response.Redirect("/");
                response.Close();
                Console.WriteLine("Đã lưu token OAuth vào file riêng trên máy.");
                continue;
            }
            else if (path == "/callback")
            {
                message = "Mở trang kết nối để bắt đầu cấp quyền từ đầu. <a href='/'>Mở trang kết nối</a>";
                html = true;
            }
            else
            {
                response.StatusCode = 403;
                message = "Phiên không hợp lệ. Mở http://localhost:8787/ để bắt đầu.";
            }
        }
    }
    catch
    {
        response.StatusCode = 400;
        message = "Kết nối chưa hoàn tất. Kiểm tra Client ID, Client Secret và Redirect URI rồi mở lại http://localhost:8787/.";
    }
    response.ContentType = html ? "text/html; charset=utf-8" : "text/plain; charset=utf-8";
    try
    {
        await response.OutputStream.WriteAsync(Encoding.UTF8.GetBytes(message));
    }
    catch (IOException) { }
    finally { response.Close(); }
}
record AppCredentials(string ClientId, string ClientSecret);
record TokenSet(string AccessToken, string RefreshToken, DateTimeOffset ExpiresAt);

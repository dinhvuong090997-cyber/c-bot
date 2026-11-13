using System.Diagnostics;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

static class DashboardServer
{
    static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, PropertyNameCaseInsensitive = true };
    static readonly string Nonce = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
    static readonly SemaphoreSlim AccountLock = new(1, 1);
    static readonly SemaphoreSlim JobLock = new(1, 1);
    static object? AccountSnapshot;
    static DateTime AccountAt;
    static ExecutionAccount? SnapshotAccount;
    static readonly Dictionary<string, object> Jobs = new();
    static string PrivateDirectory = "";
    static ExecutionClient Bot = null!;
    static MarketMonitor Market = null!;
    static string Assets = "dashboard";
    static bool ReadOnly;
    static readonly string Reports = Path.GetFullPath("reports");
    static async Task Send(HttpListenerResponse response, object value, int status = 200)
    {
        response.StatusCode = status; response.ContentType = "application/json; charset=utf-8";
        await response.OutputStream.WriteAsync(JsonSerializer.SerializeToUtf8Bytes(value, Json));
    }
    static List<(string Id, JsonElement Data)> ListReports()
    {
        Directory.CreateDirectory(Reports);
        var list = new List<(string, JsonElement)>();
        foreach (var path in Directory.EnumerateDirectories(Reports))
        {
            var id = Path.GetFileName(path);
            if (!Regex.IsMatch(id, @"^(fxpro-\d{8}-\d{8}|custom-[a-f0-9]{32})$")) continue;
            var file = Path.Combine(path, "results.json");
            if (!File.Exists(file)) continue;
            try
            {
                using var doc = JsonDocument.Parse(File.ReadAllText(file));
                if (doc.RootElement.TryGetProperty("dataVersion", out var version) && version.GetInt32() == 2)
                    list.Add((id, doc.RootElement.Clone()));
            }
            catch (IOException) { } catch (JsonException) { }
        }
        return list.OrderByDescending(r => r.Item2.GetProperty("generatedUtc").GetDateTimeOffset()).ToList();
    }
    static async Task<object> Status()
    {
        var files = Directory.Exists("data/fxpro-v2") ? Directory.GetFiles("data/fxpro-v2", "XAUUSD-*.csv.gz").Where(p => Regex.IsMatch(Path.GetFileName(p), @"^XAUUSD-\d{4}-\d{2}-\d{2}\.csv\.gz$")).Order().ToArray() : Array.Empty<string>();
        string? lastExport = File.Exists("export-v2.log") ? File.ReadLines("export-v2.log").LastOrDefault() : null;
        string? lastReplay = File.Exists("backtest-full.log") ? File.ReadLines("backtest-full.log").LastOrDefault() : null;
        bool authorized = false;
        try
        {
            var file = Path.Combine(PrivateDirectory, "tokens.json");
            if (File.Exists(file)) authorized = JsonSerializer.Deserialize<TokenSet>(File.ReadAllText(file))?.ExpiresAt > DateTimeOffset.UtcNow;
        }
        catch (IOException) { } catch (JsonException) { }
        object[] jobs;
        lock (Jobs) jobs = Jobs.Values.ToArray();
        var execution = await Bot.Snapshot();
        return new { readOnly=ReadOnly, serverUtc = DateTimeOffset.UtcNow, bot = execution.Active ? "running" : "idle", ordersEnabled = execution.Active && execution.Status.State == "running", execution,
            authorized,
            dataDays = files.Length, targetDays = 120, firstDay = files.FirstOrDefault() is { } f ? Path.GetFileName(f)[7..17] : null,
            lastDay = files.LastOrDefault() is { } l ? Path.GetFileName(l)[7..17] : null,
            fullReportReady = File.Exists(Path.Combine(Reports, "fxpro-20260101-20260501", "results.json")),
            lastExport, lastReplay, jobs };
    }
    static async Task<object> Account()
    {
        await AccountLock.WaitAsync();
        try
        {
            var selected = (await Bot.Snapshot()).Config?.Account;
            if (AccountSnapshot is not null && selected == SnapshotAccount && DateTime.UtcNow - AccountAt < TimeSpan.FromSeconds(60)) return AccountSnapshot;
            var app = JsonSerializer.Deserialize<AppCredentials>(await File.ReadAllTextAsync(Path.Combine(PrivateDirectory, "app.json")))!;
            var token = JsonSerializer.Deserialize<TokenSet>(await File.ReadAllTextAsync(Path.Combine(PrivateDirectory, "tokens.json")))!;
            if (token.ExpiresAt < DateTimeOffset.UtcNow.AddMinutes(1)) throw new InvalidOperationException("Reconnect cTrader to refresh account access.");
            long accountId = selected?.Id ?? 48463366L;
            using var api = new OpenApiConnection(); await api.Connect(app, token, accountId, selected?.Live ?? false);
            var data = await api.Request(2121, new { ctidTraderAccountId = accountId }, 2122);
            var positions = await api.Request(2124, new { ctidTraderAccountId = accountId }, 2125);
            var pnl = await api.Request(2187, new { ctidTraderAccountId = accountId }, 2188);
            var trader = data.GetProperty("trader");
            double digits = trader.TryGetProperty("moneyDigits", out var md) ? md.GetInt32() : 2;
            double balance = double.Parse(trader.GetProperty("balance").ToString(), System.Globalization.CultureInfo.InvariantCulture) / Math.Pow(10, digits);
            double unrealized = 0;
            if (pnl.TryGetProperty("positionUnrealizedPnL", out var pp))
                foreach (var p in pp.EnumerateArray()) unrealized += double.Parse(p.GetProperty("netUnrealizedPnL").ToString(), System.Globalization.CultureInfo.InvariantCulture) / Math.Pow(10, pnl.GetProperty("moneyDigits").GetInt32());
            if ((await Bot.Snapshot()).Config?.Account != selected)
                throw new ArgumentException("Selected account changed. Refresh the account snapshot.");
            AccountSnapshot = new { balance, equity = balance + unrealized, unrealized,
                login = trader.GetProperty("traderLogin").ToString(), broker = "FxPro", currency = "USD",
                positions = positions.TryGetProperty("position", out var ps) ? ps.GetArrayLength() : 0,
                capturedUtc = DateTimeOffset.UtcNow };
            SnapshotAccount = selected;
            AccountAt = DateTime.UtcNow;
            return AccountSnapshot;
        }
        finally { AccountLock.Release(); }
    }
    static async Task StartJob(ResearchConfig config, HttpListenerResponse response)
    {
        config.Validate();
        if (!await JobLock.WaitAsync(0)) { await Send(response, new { error = "A backtest is already running. Wait for it to finish." }, 409); return; }
        var id = "custom-" + Guid.NewGuid().ToString("N");
        var path = Path.Combine(Reports, id);
        var configPath = Path.Combine(path, "config.json");
        void Update(string state) { lock (Jobs) Jobs[id] = new { id, state, start = config.Start, end = config.End, config.RR, config.Capital }; }
        try
        {
            Directory.CreateDirectory(path);
            await File.WriteAllTextAsync(configPath, JsonSerializer.Serialize(config));
            Update("running");
        }
        catch { JobLock.Release(); throw; }
        _ = Task.Run(async () =>
        {
            try
            {
                var info = new ProcessStartInfo("dotnet") { RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false };
                foreach (var arg in new[] { Assembly.GetExecutingAssembly().Location, "backtest", config.Start, config.End, "--config", configPath, "--output", path }) info.ArgumentList.Add(arg);
                await using var log = File.Create(Path.Combine(path, "run.log"));
                await using var errors = File.Create(Path.Combine(path, "error.log"));
                using var process = Process.Start(info) ?? throw new IOException("Could not start replay.");
                await Task.WhenAll(process.StandardOutput.BaseStream.CopyToAsync(log), process.StandardError.BaseStream.CopyToAsync(errors), process.WaitForExitAsync());
                Update(process.ExitCode == 0 ? "completed" : "failed");
            }
            catch { Update("failed"); }
            finally { JobLock.Release(); }
        });
        await Send(response, new { id, state = "running" }, 202);
    }
    static async Task Handle(HttpListenerContext context)
    {
        var request = context.Request; var response = context.Response;
        response.Headers["Cache-Control"] = "no-store";
        response.Headers["X-Content-Type-Options"] = "nosniff";
        response.Headers["Referrer-Policy"] = "no-referrer";
        response.Headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'";
        try
        {
            if (request.Url?.Host is not ("localhost" or "127.0.0.1")) { await Send(response, new { error = "Invalid host." }, 403); return; }
            var path = request.Url.AbsolutePath;
            if (request.HttpMethod == "POST")
            {
                if(ReadOnly){await Send(response,new {error="Read-only preview. Bot controls and saved data are unchanged."},403);return;}
                var origin = request.Headers["Origin"];
                if (request.Headers["X-CSRF-Token"] != Nonce || origin != request.Url.GetLeftPart(UriPartial.Authority) || request.ContentType?.Split(';')[0] != "application/json")
                { await Send(response, new { error = "Invalid request origin or session." }, 403); return; }
                if (request.ContentLength64 is <= 0 or > 8192) { await Send(response, new { error = "Invalid request size." }, 400); return; }
                if (path.StartsWith("/api/execution/", StringComparison.Ordinal))
                {
                    using var body = await JsonDocument.ParseAsync(request.InputStream);
                    var fields = body.RootElement;
                    object result;
                    if (path == "/api/execution/apply")
                    {
                        var id = fields.GetProperty("report").GetString();
                        var report = ListReports().SingleOrDefault(r => r.Id == id);
                        if (report.Id is null) throw new ArgumentException("Unknown report.");
                        result = await Bot.Apply(report.Id, report.Data, fields.GetProperty("run").GetString()!, ExecutionFiles.Integer(fields, "accountId"));
                        AccountSnapshot = null;
                    }
                    else if (path is "/api/execution/start" or "/api/execution/stop")
                    {
                        var action = path.EndsWith("/stop") ? "stop" : "start";
                        Console.WriteLine(JsonSerializer.Serialize(new { eventType = "execution_control_requested", utc = DateTimeOffset.UtcNow, action }));
                        result = action == "stop" ? await Bot.Stop() : await Bot.Start(fields.GetProperty("revision").GetString()!, fields.GetProperty("accountLogin").GetString()!);
                        var snapshot = JsonSerializer.SerializeToElement(result, Json);
                        Console.WriteLine(JsonSerializer.Serialize(new { eventType = "execution_control_ack", utc = DateTimeOffset.UtcNow, action,
                            state = snapshot.GetProperty("status").GetProperty("state").GetString(), active = snapshot.GetProperty("active").GetBoolean() }));
                    }
                    else { await Send(response, new { error = "Unknown endpoint." }, 404); return; }
                    await Send(response, result); return;
                }
                var config = await JsonSerializer.DeserializeAsync<ResearchConfig>(request.InputStream, Json) ?? throw new ArgumentException("Invalid config.");
                config.Validate();
                if (path == "/api/backtests") await StartJob(config, response);
                else if (path == "/api/presets")
                {
                    var file = Path.Combine(PrivateDirectory, "research-preset.json");
                    var temporary = file + ".tmp";
                    await using (var stream = new FileStream(temporary, new FileStreamOptions { Mode = FileMode.Create, Access = FileAccess.Write, UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite }))
                        await JsonSerializer.SerializeAsync(stream, config, Json);
                    File.Move(temporary, file, true);
                    await Send(response, new { saved = true, applied = false });
                }
                else await Send(response, new { error = "Unknown endpoint." }, 404);
                return;
            }
            if (request.HttpMethod != "GET") { await Send(response, new { error = "Method not allowed." }, 405); return; }
            if (path == "/api/status") { await Send(response, await Status()); return; }
            if (path == "/api/session") { await Send(response, new { csrf = Nonce }); return; }
            if (path == "/api/execution/accounts") { await Send(response, await Bot.Accounts()); return; }
            if (path == "/api/execution") { await Send(response, await Bot.Snapshot()); return; }
            if (path == "/api/account") { await Send(response, await Account()); return; }
            if (path is "/api/market" or "/api/market/history")
            {
                var selected=(await Bot.Snapshot()).Config?.Account;
                await Send(response,Market.Snapshot(selected,path.EndsWith("/history")));return;
            }
            if (path == "/api/preset")
            {
                var file = Path.Combine(PrivateDirectory, "research-preset.json");
                await Send(response, File.Exists(file) ? JsonSerializer.Deserialize<JsonElement>(await File.ReadAllTextAsync(file)) : null!); return;
            }
            var reports = ListReports();
            if (path == "/api/reports")
            {
                await Send(response, reports.Select(r => new { id = r.Id, data = r.Data })); return;
            }
            if (path == "/api/backtest-bars")
            {
                var id=request.QueryString["report"];var runName=request.QueryString["run"];
                var report=reports.SingleOrDefault(r=>r.Id==id);
                if(report.Id is null)throw new ArgumentException("Unknown report.");
                var run=report.Data.GetProperty("results").EnumerateArray().SingleOrDefault(r=>r.GetProperty("name").GetString()==runName);
                if(run.ValueKind!=JsonValueKind.Object)throw new ArgumentException("Unknown run.");
                if(!int.TryParse(request.QueryString["trade"],out var trade))trade=-1;
                if(!int.TryParse(request.QueryString["period"],out var period))period=5;
                var trades=JsonSerializer.Deserialize<JsonElement[]>(await File.ReadAllTextAsync(Path.Combine(Reports,id!,runName+"-trades.json")))!;
                await Send(response,await ChartHistory.Load(id+":"+runName,run,trades,trade,period));return;
            }
            if (path is "/api/curve" or "/api/trades")
            {
                var id = request.QueryString["report"]; var run = request.QueryString["run"];
                var report = reports.SingleOrDefault(r => r.Id == id);
                if (report.Id is null || !report.Data.GetProperty("results").EnumerateArray().Any(r => r.GetProperty("name").GetString() == run))
                { await Send(response, new { error = "Unknown report or run." }, 404); return; }
                var file = Path.Combine(Reports, id!, run + (path == "/api/curve" ? "-daily.json" : "-trades.json"));
                await Send(response, JsonSerializer.Deserialize<JsonElement>(await File.ReadAllTextAsync(file))); return;
            }
            if(path.StartsWith("/assets/",StringComparison.Ordinal))
            {
                var name=path[8..];
                if(!Regex.IsMatch(name,@"^[a-zA-Z0-9_.-]+$")||!File.Exists(Path.Combine(Assets,"assets",name))){await Send(response,new {error="Unknown asset."},404);return;}
                response.ContentType=Path.GetExtension(name) switch {".js"=>"text/javascript",".css"=>"text/css",".svg"=>"image/svg+xml",".png"=>"image/png",".woff2"=>"font/woff2",".ttf"=>"font/ttf",_=>"text/plain"};
                await response.OutputStream.WriteAsync(await File.ReadAllBytesAsync(Path.Combine(Assets,"assets",name)));return;
            }
            var staticFiles = new Dictionary<string, (string File, string Type)> {
                ["/"] = ("index.html", "text/html"), ["/financial-chart.js"]=("financial-chart.js","text/javascript"), ["/dashboard.css"] = ("dashboard.css", "text/css"), ["/dashboard.js"] = ("dashboard.js", "text/javascript") };
            if (staticFiles.TryGetValue(path, out var asset))
            {
                response.ContentType = asset.Type + "; charset=utf-8";
                await response.OutputStream.WriteAsync(await File.ReadAllBytesAsync(Path.Combine(Assets, asset.File))); return;
            }
            await Send(response, new { error = "Not found." }, 404);
        }
        catch (ArgumentException ex) { await Send(response, new { error = ex.Message }, 400); }
        catch { await Send(response, new { error = "This request could not be completed. Check the local service or reconnect cTrader." }, 503); }
        finally { response.Close(); }
    }
    public static async Task Run(string privateDirectory,int port=8788,bool readOnly=false)
    {
        PrivateDirectory = privateDirectory;
        ReadOnly=readOnly;
        Bot = new ExecutionClient(privateDirectory);
        Market = new MarketMonitor(privateDirectory);
        using var listener = new HttpListener(); listener.Prefixes.Add($"http://+:{port}/"); listener.Start();
        Console.WriteLine($"Dashboard: http://localhost:{port}/");
        while (true) { var context = await listener.GetContextAsync(); _ = Handle(context); }
    }
}

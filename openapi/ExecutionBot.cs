using System.Text.Json;
using Xauusd;
using static ExecutionFiles;

sealed record ExecutionView(string State = "idle", string Message = "Select a backtest and account. Apply does not start trading.",
    DateTime? HeartbeatUtc = null, DateTime? LastQuoteUtc = null, double? Balance = null,
    double? DrawdownPercent = null, int Positions = 0, string? LastOrder = null, string? ProfileDate = null);

sealed class ExecutionBroker : IDisposable
{
    public required IExecutionConnection Api;
    public required ExecutionAccount Account;
    public required JsonElement Symbol;
    public required JsonElement Trader;
    public long SymbolId => Integer(Symbol, "symbolId");
    public double Balance => Number(Trader, "balance") / Math.Pow(10, Number(Trader, "moneyDigits", 2));
    public void Dispose() => Api.Dispose();
    public Task<JsonElement> Reconcile() => Api.Request(2124, new { ctidTraderAccountId = Account.Id }, 2125);
    public async Task RefreshTrader()
    {
        Trader = (await Api.Request(2121, new { ctidTraderAccountId = Account.Id }, 2122)).GetProperty("trader").Clone();
        ValidateTrader(Trader);
    }
    static (AppCredentials App, TokenSet Token) Credentials(string directory)
    {
        var app = JsonSerializer.Deserialize<AppCredentials>(File.ReadAllText(Path.Combine(directory, "app.json")), Json)!;
        var token = JsonSerializer.Deserialize<TokenSet>(File.ReadAllText(Path.Combine(directory, "tokens.json")), Json)!;
        if (token.ExpiresAt <= DateTimeOffset.UtcNow.AddMinutes(1)) throw new ArgumentException("Reconnect cTrader before starting: account access is expiring.");
        return (app, token);
    }
    public static async Task<ExecutionAccount[]> Accounts(string directory, Func<IExecutionConnection>? factory = null)
    {
        var (app, token) = Credentials(directory);
        using var api = factory?.Invoke() ?? new OpenApiConnection();
        await api.Connect(app, token, 0);
        var result = await api.Request(2149, new { accessToken = token.AccessToken }, 2150);
        if (Number(result, "permissionScope", -1) != 1) throw new ArgumentException("Reconnect cTrader and grant trading permission.");
        return Items(result, "ctidTraderAccount").Select(a => new ExecutionAccount(Integer(a, "ctidTraderAccountId"),
            a.TryGetProperty("traderLogin", out var login) ? login.ToString() : "",
            a.TryGetProperty("brokerTitleShort", out var broker) ? broker.GetString() ?? "" : "", Flag(a, "isLive")))
            .Where(a => a.Broker.Contains("FxPro", StringComparison.OrdinalIgnoreCase)).ToArray();
    }
    public static void ValidateTrader(JsonElement trader)
    {
        if (Number(trader, "accessRights") != 0 || Number(trader, "accountType") is not (0 or 1) || Flag(trader, "isLimitedRisk"))
            throw new ArgumentException("This account is not supported: full-access USD gold trading without guaranteed-stop requirements is needed.");
    }
    public static async Task<ExecutionBroker> Open(string directory, long id, Func<IExecutionConnection>? factory = null)
    {
        var account = (await Accounts(directory, factory)).SingleOrDefault(a => a.Id == id)
            ?? throw new ArgumentException("Choose an authorized FxPro account.");
        var (app, token) = Credentials(directory);
        var api = factory?.Invoke() ?? new OpenApiConnection();
        try
        {
            await api.Connect(app, token, account.Id, account.Live);
            var trader = (await api.Request(2121, new { ctidTraderAccountId = account.Id }, 2122)).GetProperty("trader").Clone();
            ValidateTrader(trader);
            var assets = await api.Request(2112, new { ctidTraderAccountId = account.Id }, 2113);
            var usd = Items(assets, "asset").SingleOrDefault(a => a.GetProperty("name").GetString() == "USD");
            if (usd.ValueKind != JsonValueKind.Object || Integer(usd, "assetId") != Integer(trader, "depositAssetId"))
                throw new ArgumentException("Select a USD account.");
            var symbols = await api.Request(2114, new { ctidTraderAccountId = account.Id }, 2115);
            var candidates = Items(symbols, "symbol").Where(s => s.GetProperty("symbolName").GetString() is "XAUUSD" or "GOLD" or "GOLDoz").ToArray();
            var light = candidates.FirstOrDefault(s => s.GetProperty("symbolName").GetString() == "XAUUSD");
            if (light.ValueKind != JsonValueKind.Object && candidates.Length == 1) light = candidates[0];
            if (light.ValueKind != JsonValueKind.Object || Integer(light, "quoteAssetId") != Integer(usd, "assetId") || !Flag(light, "enabled"))
                throw new ArgumentException("A unique enabled USD gold symbol was not found.");
            var symbolId = Integer(light, "symbolId");
            var spec = await api.Request(2116, new { ctidTraderAccountId = account.Id, symbolId = new[] { symbolId } }, 2117);
            var symbol = Items(spec, "symbol").Single(s => Integer(s, "symbolId") == symbolId).Clone();
            if (Number(symbol, "tradingMode") != 0) throw new ArgumentException("Gold is not enabled for opening orders.");
            return new() { Api = api, Account = account, Trader = trader, Symbol = symbol };
        }
        catch { api.Dispose(); throw; }
    }
    public static bool HasExposure(JsonElement reconcile) => Items(reconcile, "position").Any() || Items(reconcile, "order").Any();
    public static bool Protected(JsonElement p) => Number(p, "stopLoss") > 0 && Number(p, "takeProfit") > 0;
}

sealed class ExecutionBot
{
    const string Label = "AurumMomentum";
    readonly string directory;
    readonly SemaphoreSlim commands = new(1, 1);
    readonly Func<IExecutionConnection> factory;
    ExecutionConfig? config;
    Task? running;
    volatile bool stopRequested;
    ExecutionView view = new();
    public ExecutionBot(string directory, Func<IExecutionConnection>? factory = null)
    {
        this.directory = directory; this.factory = factory ?? (() => new OpenApiConnection());
        var path = Path.Combine(directory, "execution-config.json");
        if (File.Exists(path)) { config = JsonSerializer.Deserialize<ExecutionConfig>(File.ReadAllText(path), Json); config?.Validate(); if (config is not null) view = new("ready", "Saved config loaded. Press Start to download history and enable orders."); }
    }
    public ExecutionSnapshot Snapshot() => new(config, view, running is { IsCompleted: false });
    public ExecutionAccount? Account => config?.Account;
    public bool OrdersEnabled => IsRunning && view.State == "running" && !stopRequested;
    public bool IsRunning => running is { IsCompleted: false };
    public Task<ExecutionAccount[]> Accounts() => ExecutionBroker.Accounts(directory, factory);
    public async Task<object> Apply(string reportId, JsonElement report, string run, long accountId)
    {
        await commands.WaitAsync();
        try
        {
            if (IsRunning) throw new ArgumentException("Stop the bot before changing its config or account.");
            using var broker = await ExecutionBroker.Open(directory, accountId, factory);
            var selected = ExecutionConfig.FromReport(reportId, report, run, broker.Account);
            Save(Path.Combine(directory, "execution-config.json"), selected);
            config = selected;
            view = new("ready", "Config applied. Press Start to enable orders.", Balance: broker.Balance);
            return Snapshot();
        }
        finally { commands.Release(); }
    }
    public async Task<object> Start(string revision, string accountLogin)
    {
        await commands.WaitAsync();
        try
        {
            if (IsRunning) throw new ArgumentException("The bot is already starting or running.");
            var selected = config ?? throw new ArgumentException("Apply a completed backtest config first.");
            if (selected.Revision != revision || selected.Account.Login != accountLogin)
                throw new ArgumentException("The selected account or configuration changed. Review it again.");
            selected.Validate();
            stopRequested = false;
            view = new("starting", "Connecting and checking account protection.");
            running = Task.Run(() => Run(selected));
            return Snapshot();
        }
        finally { commands.Release(); }
    }
    public async Task<object> Stop()
    {
        stopRequested = true;
        await commands.WaitAsync();
        try
        {
            stopRequested = true; // A concurrent Start may have reset the early stop signal while holding this lock.
            if (IsRunning) view = view with { State = "stopping", Message = "Stopping new entries. Checking any in-flight order; existing SL/TP stay at the broker." };
            return Snapshot();
        }
        finally { commands.Release(); }
    }
    // Protocol values: volume is hundredths of an ounce, protection distances are price * 100000.
    internal static object OrderPayload(ExecutionConfig c, long symbol, ExecutionOrder order, bool buy, string id) => new
    {
        ctidTraderAccountId = c.Account.Id, symbolId = symbol, orderType = 1, tradeSide = buy ? 1 : 2,
        volume = order.Volume, relativeStopLoss = order.RelativeStopLoss, relativeTakeProfit = order.RelativeTakeProfit,
        label = Label, clientOrderId = id
    };
    internal static async Task Submit(IExecutionConnection api, ExecutionConfig config, long symbol, ExecutionOrder order,
        bool buy, ExecutionRisk risk, string riskFile)
    {
        if (risk.Halted || risk.PendingOrder is not null) throw new ArgumentException("A halt or unresolved order blocks submission.");
        risk.PendingOrder = "aurum-" + Guid.NewGuid().ToString("N");
        Save(riskFile, risk); // The intent must reach disk before any broker request.
        await api.Request(2106, OrderPayload(config, symbol, order, buy, risk.PendingOrder), 2126);
    }
    internal static bool IsTerminalOpeningOrder(JsonElement payload, string? pending) =>
        pending is not null && payload.TryGetProperty("order", out var order) &&
        !Flag(order, "closingOrder") && Number(order, "orderType") == 1 &&
        order.TryGetProperty("clientOrderId", out var id) && id.GetString() == pending &&
        Number(payload, "executionType") is 3 or 5 or 6 or 7;
    // Called only after a fresh reconcile and protection check.
    internal static void ConfirmPending(ExecutionRisk risk, string riskFile)
    {
        if (risk.PendingOrder is null) return;
        risk.PendingOrder = null; Save(riskFile, risk);
    }
    internal static async Task CheckProtection(ExecutionBroker broker, ExecutionRisk risk, string riskFile,
        JsonElement reconcile, Dictionary<long, long> failures)
    {
        var positions = Items(reconcile, "position").ToArray();
        foreach (var p in positions)
        {
            var td = p.GetProperty("tradeData");
            if (td.TryGetProperty("label", out var label) && label.GetString() == Label && !ExecutionBroker.Protected(p))
                failures[Integer(p, "positionId")] = Integer(td, "volume");
        }
        if (failures.Count == 0) return;
        risk.Halted = true; Save(riskFile, risk);
        foreach (var failure in failures)
        {
            var p = positions.SingleOrDefault(p => Integer(p, "positionId") == failure.Key);
            if (p.ValueKind != JsonValueKind.Object || ExecutionBroker.Protected(p)) continue;
            await broker.Api.Request(2111, new { ctidTraderAccountId = broker.Account.Id, positionId = failure.Key, volume = Integer(p.GetProperty("tradeData"), "volume") }, 2126);
        }
        throw new ArgumentException("A bot position lacked SL/TP. Emergency close requested where still needed and new entries halted. Verify closure in cTrader.");
    }
    async Task Run(ExecutionConfig selected)
    {
        string riskFile = Path.Combine(directory, $"execution-risk-{selected.Account.Live}-{selected.Account.Id}.json");
        ExecutionRisk? risk = null;
        bool bootstrapping = true;
        try
        {
            // A second dashboard/process must never control the same execution workspace.
            using var lease = new FileStream(Path.Combine(directory, "execution.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
            risk = File.Exists(riskFile) ? JsonSerializer.Deserialize<ExecutionRisk>(File.ReadAllText(riskFile), Json)! : new();
            if (risk.PendingOrder is not null) throw new ArgumentException("An earlier order has an unknown outcome. Review the broker account and execution risk journal before restarting; it will not be resent.");
            if (risk.Halted) throw new ArgumentException("The saved drawdown/protection halt needs review before this account can restart.");
            using var broker = await ExecutionBroker.Open(directory, selected.Account.Id, factory);
            if (broker.Account != selected.Account) throw new ArgumentException("Account identity changed. Apply the config again.");
            var api = broker.Api;
            var signal = new ExecutionSignal(selected) { LastAttempt = risk.LastAttempt };
            double bid = 0, ask = 0;
            DateTime bidAt = DateTime.MinValue, askAt = DateTime.MinValue, quoteAt = DateTime.MinValue;
            DateTime sentAt = DateTime.MinValue;
            var protectiveFailures = new Dictionary<long, long>();
            bool terminal = false, warming = true;
            var bufferedSpots = new List<JsonElement>();
            void Spot(JsonElement payload)
            {
                if (!payload.TryGetProperty("timestamp", out _)) return;
                var time = DateTimeOffset.FromUnixTimeMilliseconds(Integer(payload, "timestamp")).UtcDateTime;
                if (time < quoteAt || time > DateTime.UtcNow.AddSeconds(1)) return;
                if (!warming && DateTime.UtcNow - time > TimeSpan.FromSeconds(5)) return;
                if (payload.TryGetProperty("bid", out _)) { bid = Number(payload, "bid") / 1e5; bidAt = time; }
                if (payload.TryGetProperty("ask", out _)) { ask = Number(payload, "ask") / 1e5; askAt = time; }
                if (bid > 0 && ask >= bid && time - bidAt <= TimeSpan.FromSeconds(5) && time - askAt <= TimeSpan.FromSeconds(5))
                { quoteAt = time; signal.Observe(time, bid, ask); }
            }
            void ObserveHistory(BacktestRunner.Quote q)
            {
                if (q.Time < quoteAt) throw new IOException("Out-of-order bootstrap history.");
                signal.Observe(q.Time, q.Bid, q.Ask);
                bid = q.Bid; ask = q.Ask; quoteAt = q.Time;
                // Merged history has no per-side freshness provenance. Only actual spot updates may arm entries.
                bidAt = askAt = DateTime.MinValue;
            }
            void Progress(string message)
            {
                view = view with { State = "warming", Message = message, HeartbeatUtc = DateTime.UtcNow };
                Console.WriteLine(JsonSerializer.Serialize(new { eventType = "history_progress", utc = DateTimeOffset.UtcNow, account = selected.Account.Id, message }));
            }
            api.Received = (type, payload) =>
            {
                if (Integer(payload, "ctidTraderAccountId") != selected.Account.Id) return;
                if (warming) view = view with { HeartbeatUtc = DateTime.UtcNow };
                if (type == 2131 && Integer(payload, "symbolId") == broker.SymbolId)
                {
                    if (warming)
                    {
                        if (bufferedSpots.Count >= 200000) throw new IOException("Live quote buffer exceeded during bootstrap.");
                        bufferedSpots.Add(payload.Clone());
                    }
                    else Spot(payload);
                }
                if (type == 2126)
                {
                    // Execution events can precede SL/TP attachment. Only a fresh reconcile proves missing protection.
                    terminal |= IsTerminalOpeningOrder(payload, risk.PendingOrder);
                }
            };
            risk.Update(broker.Balance, selected.MaxDrawdownPercent); Save(riskFile, risk);
            await CheckProtection(broker, risk, riskFile, await broker.Reconcile(), protectiveFailures);
            if (!risk.Halted && !stopRequested)
            {
                var cutoff = DateTime.UtcNow;
                var count = await TickHistory.Warmup(broker, selected, cutoff, ObserveHistory, Progress, () => stopRequested);
                Progress("Connecting live quotes and filling the startup gap.");
                await api.Request(2127, new { ctidTraderAccountId = selected.Account.Id, symbolId = new[] { broker.SymbolId }, subscribeToSpotTimestamp = true }, 2128);
                var bridgeEnd = DateTime.UtcNow;
                foreach (var q in await TickHistory.Quotes(api, selected.Account.Id, broker.SymbolId, cutoff, bridgeEnd, () => stopRequested, bid > 0 && ask >= bid ? new BacktestRunner.Quote(new DateTimeOffset(quoteAt).ToUnixTimeMilliseconds(), bid, ask) : null))
                { ObserveHistory(q); count++; }
                foreach (var spot in bufferedSpots.OrderBy(p => Integer(p, "timestamp")))
                    if (Integer(spot, "timestamp") >= new DateTimeOffset(bridgeEnd).ToUnixTimeMilliseconds()) Spot(spot);
                bufferedSpots.Clear();
                if (stopRequested) throw new OperationCanceledException();
                Console.WriteLine(JsonSerializer.Serialize(new { eventType = "history_ready", utc = DateTimeOffset.UtcNow, account = selected.Account.Id, quotes = count,
                    profileDate = signal.Profile(DateTime.UtcNow)?.Date.ToString("yyyy-MM-dd") }));
            }
            warming = false; bootstrapping = false;
            while (true)
            {
                await broker.RefreshTrader();
                var oldPeak = risk.Peak; var oldHalt = risk.Halted;
                risk.Update(broker.Balance, selected.MaxDrawdownPercent);
                if (oldPeak != risk.Peak || oldHalt != risk.Halted) Save(riskFile, risk);
                var reconcile = await broker.Reconcile();
                var positions = Items(reconcile, "position").ToArray();
                await CheckProtection(broker, risk, riskFile, reconcile, protectiveFailures);
                if (terminal) { ConfirmPending(risk, riskFile); terminal = false; }
                if (risk.PendingOrder is not null && DateTime.UtcNow - sentAt > TimeSpan.FromSeconds(15))
                    throw new ArgumentException("Order outcome is uncertain. New entries stopped; no automatic resubmission. Check cTrader.");
                var now = DateTime.UtcNow;
                bool fresh = now - quoteAt <= TimeSpan.FromSeconds(5) && now - bidAt <= TimeSpan.FromSeconds(5) && now - askAt <= TimeSpan.FromSeconds(5);
                var exposure = ExecutionBroker.HasExposure(reconcile);
                view = new(risk.Halted ? "halted" : stopRequested ? "stopping" : "running",
                    risk.Halted ? "Drawdown limit reached. Existing positions keep their broker SL/TP." : exposure ? "Position/order open. Waiting for SL or TP." : !fresh ? "Waiting for fresh gold quotes." : "Receiving quotes. Waiting for a complete Asia profile or an eligible entry.",
                    now, quoteAt == DateTime.MinValue ? null : quoteAt, broker.Balance, 100 * (1 - broker.Balance / risk.Peak), positions.Length, view.LastOrder, signal.Profile(now)?.Date.ToString("yyyy-MM-dd"));
                if (stopRequested && risk.PendingOrder is null) break;
                var profile = signal.Ready(quoteAt, bid, ask, stopRequested || risk.Halted || exposure || risk.PendingOrder is not null || !fresh);
                if (signal.LastAttempt != risk.LastAttempt) { risk.LastAttempt = signal.LastAttempt; Save(riskFile, risk); }
                if (profile is not null)
                {
                    var signalAt = quoteAt;
                    if (!profile.IsLong && !Flag(broker.Symbol, "enableShortSelling")) throw new ArgumentException("Short selling is not enabled for this symbol.");
                    var order = ExecutionOrder.Size(selected, broker.Balance, profile.IsLong ? ask : bid, profile.StopDistance, broker.Symbol);
                    if (order is not null)
                    {
                        var margin = await api.Request(2139, new { ctidTraderAccountId = selected.Account.Id, symbolId = broker.SymbolId, volume = new[] { order.Volume } }, 2140);
                        var expected = Items(margin, "margin").Single(m => Integer(m, "volume") == order.Volume);
                        double required = Number(expected, profile.IsLong ? "buyMargin" : "sellMargin") / Math.Pow(10, Number(margin, "moneyDigits", 2));
                        await broker.RefreshTrader();
                        var beforePeak = risk.Peak; var beforeHalt = risk.Halted;
                        risk.Update(broker.Balance, selected.MaxDrawdownPercent);
                        if (beforePeak != risk.Peak || beforeHalt != risk.Halted) Save(riskFile, risk);
                        var final = await broker.Reconcile();
                        now = DateTime.UtcNow;
                        // Recheck after network calls; never execute a stale, newly exposed or stopped signal.
                        var currentSize = ExecutionOrder.Size(selected, broker.Balance, profile.IsLong ? ask : bid, profile.StopDistance, broker.Symbol);
                        if (!stopRequested && !risk.Halted && signal.Eligible(profile, now) && now - signalAt <= TimeSpan.FromSeconds(5) && currentSize is not null && order.Volume <= currentSize.Volume && !ExecutionBroker.HasExposure(final) && now - quoteAt <= TimeSpan.FromSeconds(5) &&
                            now - bidAt <= TimeSpan.FromSeconds(5) && now - askAt <= TimeSpan.FromSeconds(5) && ask - bid <= profile.SpreadLimit + 1e-9 &&
                            required > 0 && required <= broker.Balance * .99)
                        {
                            await commands.WaitAsync();
                            try
                            {
                                if (stopRequested) continue;
                                sentAt = now; terminal = false;
                                await Submit(api, selected, broker.SymbolId, order, profile.IsLong, risk, riskFile);
                                view = view with { LastOrder = risk.PendingOrder };
                            }
                            finally { commands.Release(); }
                        }
                    }
                }
                await Task.Delay(500);
            }
            view = view with { State = "idle", Message = "Stopped. No new orders. Existing positions retain broker SL/TP.", HeartbeatUtc = DateTime.UtcNow };
        }
        catch (OperationCanceledException) when (stopRequested && bootstrapping && risk?.PendingOrder is null)
        {
            view = view with { State = "idle", Message = "Startup cancelled. No new order was sent.", HeartbeatUtc = DateTime.UtcNow };
            Console.WriteLine(JsonSerializer.Serialize(new { eventType = "history_cancelled", utc = DateTimeOffset.UtcNow, account = selected.Account.Id }));
        }
        catch (Exception ex)
        {
            var error = ex is ArgumentException ? ex.Message : ex is IOException && System.Text.RegularExpressions.Regex.IsMatch(ex.Message, @"^cTrader request \d+ rejected: [A-Za-z0-9_]+$") ? ex.Message : ex.GetType().Name;
            Console.Error.WriteLine(JsonSerializer.Serialize(new { eventType = "execution_fault", utc = DateTimeOffset.UtcNow, account = selected.Account.Id, error, pendingOrder = risk?.PendingOrder }));
            // Exception bodies from the broker/transport never include credentials.
            view = view with { State = "fault", Message = ex is ArgumentException ? ex.Message : "Execution stopped after a connection, broker or journal error. Check cTrader before restarting. No order is retried automatically.", HeartbeatUtc = DateTime.UtcNow };
        }
    }
}

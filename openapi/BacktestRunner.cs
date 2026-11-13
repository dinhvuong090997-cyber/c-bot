using System.Globalization;
using System.IO.Compression;
using System.Text.Json;
using System.Security.Cryptography;
using Xauusd;

static class BacktestRunner
{
    internal sealed record Quote(long Milliseconds, double Bid, double Ask)
    {
        public DateTime Time { get; } = DateTimeOffset.FromUnixTimeMilliseconds(Milliseconds).UtcDateTime;
    }
    internal sealed record Settings(double Initial, double RR, double Slippage, bool Swap, DateTime Start, DateTime End, double RiskPercent = 0.25, double MaxDrawdownPercent = 5);
    internal sealed class Position
    {
        public required DateTime EntryTime;
        public required bool Long;
        public required double Entry, Stop, Target, Volume, EntryCommission;
        public required string Session;
        public double Swap;
        public required DateTime NextRollover;
    }
    internal sealed class Simulation
    {
        public readonly Settings Config;
        readonly JsonElement symbol;
        readonly double commissionRate, minimumCommission;
        public readonly List<object> Trades = new();
        public readonly List<object> Daily = new();
        Position? position;
        (DateTime Due, EntrySession Session, AsiaProfile Profile)? pending;
        DateTime lastAttempt = DateTime.MinValue;
        public double Balance, ClosedPeak, EquityPeak, MaxClosedDD, MaxEquityDD;
        public double TotalCommission, TotalSwap, GrossProfit, GrossLoss;
        public int Wins, Losses, MaxLossStreak, LossStreak, SkippedVolume;
        public bool Halted;
        public DateTime? HaltedAt;
        Quote? last;
        public string Name => $"{Config.Start:yyyyMMdd}-{Config.End:yyyyMMdd}-{Config.Initial:0}-rr{Config.RR.ToString(CultureInfo.InvariantCulture)}-slip{Config.Slippage.ToString(CultureInfo.InvariantCulture)}-swap{Config.Swap}";
        double Number(string key, double fallback = 0) => symbol.TryGetProperty(key, out var value) ? double.Parse(value.ToString(), CultureInfo.InvariantCulture) : fallback;
        public Simulation(Settings config, JsonElement spec)
        {
            Config = config; symbol = spec;
            if (Number("commissionType") != 1 || Number("swapCalculationType") != 0)
                throw new InvalidOperationException("Unsupported cost convention.");
            commissionRate = Number("preciseTradingCommissionRate") / 1e8 / 1e6;
            minimumCommission = Number("preciseMinCommission") / 1e8;
            Balance = ClosedPeak = EquityPeak = config.Initial;
        }
        double Commission(double price, double volume) => Math.Max(minimumCommission, commissionRate * price * volume);
        static readonly TimeZoneInfo London = TimeZoneInfo.FindSystemTimeZoneById("Europe/London");
        static DateTime Rollover(DateTime day)
        {
            // FxPro publishes rollover at 21:59 UK time; DST conversion is historical.
            return TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(day.Date.AddHours(21).AddMinutes(59), DateTimeKind.Unspecified), London);
        }
        void ApplySwap(DateTime time)
        {
            if (position is not { } p) return;
            while (p.NextRollover <= time)
            {
                var rollover = p.NextRollover;
                if (rollover > p.EntryTime && rollover.DayOfWeek is not (DayOfWeek.Saturday or DayOfWeek.Sunday) && Config.Swap)
                {
                    var days = (int)rollover.DayOfWeek == (int)Number("swapRollover3Days") ? 3 : 1;
                    var fee = Number(p.Long ? "swapLong" : "swapShort") * Math.Pow(10, -Number("pipPosition")) * p.Volume * days;
                    p.Swap += fee; TotalSwap += fee;
                }
                p.NextRollover = Rollover(rollover.Date.AddDays(1));
            }
        }
        double LiquidationEquity(Quote q)
        {
            if (position is not { } p) return Balance;
            double exit = p.Long ? q.Bid : q.Ask;
            return Balance + (p.Long ? exit - p.Entry : p.Entry - exit) * p.Volume + p.Swap - Commission(exit, p.Volume);
        }
        void Drawdown(Quote q)
        {
            var equity = LiquidationEquity(q);
            EquityPeak = Math.Max(EquityPeak, equity);
            MaxEquityDD = Math.Max(MaxEquityDD, 100 * (1 - equity / EquityPeak));
            ClosedPeak = Math.Max(ClosedPeak, Balance);
            MaxClosedDD = Math.Max(MaxClosedDD, 100 * (1 - Balance / ClosedPeak));
            if (!Halted && Balance <= ClosedPeak * (1 - Config.MaxDrawdownPercent / 100)) { Halted = true; HaltedAt = q.Time; }
        }
        void Exit(Quote q, double exit, string reason)
        {
            var p = position!;
            var commission = Commission(exit, p.Volume);
            var gross = (p.Long ? exit - p.Entry : p.Entry - exit) * p.Volume;
            var net = gross + p.Swap - p.EntryCommission - commission;
            Balance += gross + p.Swap - commission;
            TotalCommission += commission;
            if (net > 0) { Wins++; GrossProfit += net; LossStreak = 0; }
            else { Losses++; GrossLoss -= net; MaxLossStreak = Math.Max(MaxLossStreak, ++LossStreak); }
            Trades.Add(new { entryUtc = p.EntryTime, exitUtc = q.Time, session = p.Session,
                side = p.Long ? "BUY" : "SELL", volumeOz = p.Volume, p.Entry, exit,
                p.Stop, p.Target, gross, commission = commission + p.EntryCommission, swap = p.Swap, net, reason,
                hours = (q.Time - p.EntryTime).TotalHours, balance = Balance });
            position = null;
        }
        public void Observe(Quote q, EntrySession session, AsiaProfile? profile)
        {
            if (q.Time < Config.Start || q.Time >= Config.End) return;
            if (last is { } previous && previous.Time.Date != q.Time.Date)
                Daily.Add(new { date = previous.Time.ToString("yyyy-MM-dd"), balance = Balance, equity = LiquidationEquity(previous) });
            if (Halted && position is null) { last = q; return; }
            ApplySwap(q.Time);
            if (position is { } p)
            {
                var executable = p.Long ? q.Bid : q.Ask;
                if (p.Long ? executable <= p.Stop : executable >= p.Stop)
                    Exit(q, executable + (p.Long ? -Config.Slippage : Config.Slippage), "SL");
                else if (p.Long ? executable >= p.Target : executable <= p.Target)
                    Exit(q, p.Target, "TP"); // limit fill, no positive slippage
            }
            Drawdown(q);
            last = q;
            if (Halted || profile is null || position is not null) { pending = null; return; }
            if (pending is { } entry)
            {
                if (q.Time >= entry.Due)
                {
                    pending = null;
                    if (q.Time - entry.Due <= TimeSpan.FromSeconds(5) && entry.Session == session && entry.Profile == profile &&
                        q.Ask - q.Bid <= profile.SpreadLimit + 1e-9)
                        Open(q, profile, session);
                }
                return;
            }
            var minute = q.Time.AddTicks(-(q.Time.Ticks % TimeSpan.TicksPerMinute));
            if (minute == lastAttempt || q.Ask - q.Bid > profile.SpreadLimit + 1e-9) return;
            lastAttempt = minute;
            pending = (q.Time.AddSeconds(1), session, profile);
        }
        void Open(Quote q, AsiaProfile profile, EntrySession session)
        {
            double tickSize = Math.Pow(10, -Number("digits"));
            double stop = Math.Ceiling(profile.StopDistance / tickSize - 1e-9) * tickSize;
            double quoted = profile.IsLong ? q.Ask : q.Bid;
            double volume = Math.Min(Number("maxVolume") / 100, Math.Min(Balance * Config.RiskPercent / 100 / (stop + 0.17), Balance / (quoted * 1.01)));
            double step = Number("stepVolume") / 100;
            volume = Math.Floor(volume / step) * step;
            if (volume < Number("minVolume") / 100) { SkippedVolume++; return; }
            double price = quoted + (profile.IsLong ? Config.Slippage : -Config.Slippage);
            double commission = Commission(price, volume);
            Balance -= commission;
            TotalCommission += commission;
            var rollover = Rollover(q.Time);
            if (rollover <= q.Time) rollover = Rollover(q.Time.Date.AddDays(1));
            position = new Position { EntryTime = q.Time, Long = profile.IsLong, Entry = price,
                Stop = Math.Round(price + (profile.IsLong ? -stop : stop), (int)Number("digits"), MidpointRounding.AwayFromZero),
                Target = Math.Round(price + (profile.IsLong ? 1 : -1) * Config.RR * stop, (int)Number("digits"), MidpointRounding.AwayFromZero),
                Volume = volume, EntryCommission = commission, Session = session.ToString(), NextRollover = rollover };
            Drawdown(q);
        }
        public object Result() => new
        {
            name = Name, startUtc = Config.Start, endUtcExclusive = Config.End, initial = Config.Initial,
            rr = Config.RR, riskPercent = Config.RiskPercent, maxDrawdownPercent = Config.MaxDrawdownPercent, slippageUsdOz = Config.Slippage, swapEnabled = Config.Swap,
            trades = Trades.Count, wins = Wins, losses = Losses, winRate = Trades.Count > 0 ? 100.0 * Wins / Trades.Count : 0,
            closedNet = Balance - Config.Initial, equityNet = last is null ? 0 : LiquidationEquity(last) - Config.Initial,
            closedReturnPct = 100 * (Balance / Config.Initial - 1), maxClosedDDPct = MaxClosedDD, maxEquityDDPct = MaxEquityDD,
            profitFactor = GrossLoss > 0 ? (double?)(GrossProfit / GrossLoss) : null,
            commission = TotalCommission, swap = TotalSwap, halted = Halted, haltUtc = HaltedAt, maxLossStreak = MaxLossStreak,
            openPositions = position is null ? 0 : 1, openEntryUtc = position?.EntryTime, skippedVolume = SkippedVolume,
            approxTradesPerWeekday = Trades.Count / Math.Max(1.0, Enumerable.Range(0, (Config.End - Config.Start).Days).Count(d => Config.Start.AddDays(d).DayOfWeek is not (DayOfWeek.Saturday or DayOfWeek.Sunday)))
        };
        public void Save(string directory)
        {
            if (last is { } q) Daily.Add(new { date = q.Time.ToString("yyyy-MM-dd"), balance = Balance, equity = LiquidationEquity(q) });
            File.WriteAllText(Path.Combine(directory, Name + "-trades.json"), JsonSerializer.Serialize(Trades));
            File.WriteAllText(Path.Combine(directory, Name + "-daily.json"), JsonSerializer.Serialize(Daily));
        }
    }
    internal static IEnumerable<Quote> ReadQuotes(string path)
    {
        IEnumerable<(long Time, int Side, long Price)> Read()
        {
            using var file = File.OpenRead(path);
            using var gzip = new GZipStream(file, CompressionMode.Decompress);
            using var reader = new StreamReader(gzip);
            reader.ReadLine();
            while (reader.ReadLine() is { } line)
            {
                var parts = line.Split(',');
                yield return (long.Parse(parts[0], CultureInfo.InvariantCulture), int.Parse(parts[1], CultureInfo.InvariantCulture), long.Parse(parts[2], CultureInfo.InvariantCulture));
            }
        }
        return MergeQuotes(Read());
    }
    internal static IEnumerable<Quote> MergeQuotes(IEnumerable<(long Time, int Side, long Price)> ticks, double initialBid = 0, double initialAsk = 0)
    {
        long time = -1;
        double bid = initialBid, ask = initialAsk, groupBid = 0, groupAsk = 0;
        Quote? Flush()
        {
            if (groupBid > 0) bid = groupBid;
            if (groupAsk > 0) ask = groupAsk;
            groupBid = groupAsk = 0;
            return bid > 0 && ask > 0 ? new Quote(time, bid, ask) : null;
        }
        foreach (var tick in ticks)
        {
            var stamp = tick.Time;
            var side = tick.Side;
            var price = tick.Price / 1e5;
            if (stamp < time) throw new IOException("Unsorted ticks.");
            if (time >= 0 && stamp != time) { var quote = Flush(); if (quote is not null) yield return quote; }
            time = stamp;
            // Cross-side event ordering within a millisecond is not available.
            // Conservative executable quote: lowest bid / highest ask within each tied group.
            if (side == 1) groupBid = groupBid == 0 ? price : Math.Min(groupBid, price);
            else if (side == 2) groupAsk = Math.Max(groupAsk, price);
            else throw new IOException("Unknown quote side.");
        }
        if (time >= 0) { var quote = Flush(); if (quote is not null) yield return quote; }
    }
    public static void Run(string[] args)
    {
        if (args.Length < 3) throw new ArgumentException("backtest START END (complete UTC days, end exclusive)");
        ResearchConfig? custom = null;
        var configIndex = Array.IndexOf(args, "--config");
        if (configIndex >= 0)
        {
            custom = JsonSerializer.Deserialize<ResearchConfig>(File.ReadAllText(args[configIndex + 1]));
            if (custom is null) throw new ArgumentException("Invalid research config.");
            custom.Validate();
        }
        var start = DateTime.Parse(args[1], CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);
        var end = DateTime.Parse(args[2], CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal);
        if (custom is not null && (custom.Start != args[1] || custom.End != args[2]))
            throw new ArgumentException("CLI dates must match the research config.");
        var directory = Path.Combine("data", "fxpro-v2");
        using var metadata = JsonDocument.Parse(File.ReadAllText(Path.Combine(directory, "metadata.json")));
        var root = metadata.RootElement;
        var asset = root.GetProperty("assets").EnumerateArray().Single(a => a.GetProperty("assetId").ToString() == root.GetProperty("account").GetProperty("depositAssetId").ToString());
        if (asset.GetProperty("name").GetString() != "USD" || root.GetProperty("account").GetProperty("swapFree").GetBoolean())
            throw new InvalidOperationException("Simulator requires a USD account with normal swaps.");
        var simulations = new List<Simulation>();
        var periods = new List<(DateTime Start, DateTime End)> { (start, end) };
        if (custom is null && (end - start).Days > 32)
            for (var month = new DateTime(start.Year, start.Month, 1, 0, 0, 0, DateTimeKind.Utc); month < end; month = month.AddMonths(1))
                periods.Add((month < start ? start : month, month.AddMonths(1) > end ? end : month.AddMonths(1)));
        foreach (var period in periods)
        foreach (double initial in custom is null ? new[] { 50000.0, 100000.0 } : new[] { custom.Capital })
        foreach (double rr in custom is null ? new[] { 1.5, 2.0 } : new[] { custom.RR })
        foreach (double slip in custom is null ? new[] { 0.0, 0.1 } : new[] { custom.Slippage })
        foreach (bool swap in custom is null ? new[] { true, false } : new[] { custom.Swap })
            simulations.Add(new Simulation(new Settings(initial, rr, slip, swap, period.Start, period.End, custom?.RiskPercent ?? 0.25, custom?.MaxDrawdownPercent ?? 5), root.GetProperty("symbol")));
        var asia = new AsiaSession();
        long quotes = 0;
        int profiles = 0;
        DateOnly? lastProfile = null;
        double spreadSum = 0;
        long crossed = 0;
        var files = new List<object>();
        var warmupFiles = new List<object>();
        for (var day = start.AddDays(-4); day < start; day = day.AddDays(1))
        {
            var path = Path.Combine(directory, $"XAUUSD-{day:yyyy-MM-dd}.csv.gz");
            if (!File.Exists(path)) continue;
            foreach (var q in ReadQuotes(path))
                if (q.Ask >= q.Bid && q.Bid > 0)
                    asia.Observe(q.Time, q.Bid, q.Ask, custom?.SpreadMultiplier ?? 1.5, custom?.MinimumStop ?? 2.0);
            using var source = File.OpenRead(path);
            warmupFiles.Add(new { date = day.ToString("yyyy-MM-dd"), sha256 = Convert.ToHexString(SHA256.HashData(source)).ToLowerInvariant() });
        }

        for (var day = start; day < end; day = day.AddDays(1))
        {
            var path = Path.Combine(directory, $"XAUUSD-{day:yyyy-MM-dd}.csv.gz");
            if (!File.Exists(path) && args.Contains("--wait-data"))
            {
                Console.WriteLine("Waiting for complete UTC day: " + day.ToString("yyyy-MM-dd"));
                var deadline = DateTime.UtcNow.AddMinutes(30);
                while (!File.Exists(path) && DateTime.UtcNow < deadline) Thread.Sleep(500);
            }
            if (!File.Exists(path)) throw new IOException("Missing complete day: " + day.ToString("yyyy-MM-dd"));
            long count = 0;
            var active = simulations.Where(sim => day >= sim.Config.Start && day < sim.Config.End).ToArray();
            foreach (var q in ReadQuotes(path))
            {
                if (!double.IsFinite(q.Bid) || !double.IsFinite(q.Ask) || q.Bid <= 0 || q.Ask < q.Bid) { crossed++; continue; }
                asia.Observe(q.Time, q.Bid, q.Ask, custom?.SpreadMultiplier ?? 1.5, custom?.MinimumStop ?? 2.0);
                var session = AsiaSession.GetEntrySession(q.Time, custom?.Asia ?? true, custom?.NewYork ?? true);
                var profile = asia.GetProfile(session, q.Time);
                if (profile is not null && profile.Date != lastProfile) { profiles++; lastProfile = profile.Date; }
                foreach (var simulation in active) simulation.Observe(q, session, profile);
                count++; spreadSum += q.Ask - q.Bid;
            }
            quotes += count;
            using (var source = File.OpenRead(path))
                files.Add(new { date = day.ToString("yyyy-MM-dd"), quotes = count, bytes = new FileInfo(path).Length,
                    sha256 = Convert.ToHexString(SHA256.HashData(source)).ToLowerInvariant() });
            Console.WriteLine($"{day:yyyy-MM-dd}: {count} quote snapshots; baseline trades {simulations[0].Trades.Count}");
        }
        var outputIndex = Array.IndexOf(args, "--output");
        var reportDirectory = outputIndex >= 0 ? args[outputIndex + 1] : Path.Combine("reports", $"fxpro-{start:yyyyMMdd}-{end:yyyyMMdd}");
        Directory.CreateDirectory(reportDirectory);
        File.WriteAllText(Path.Combine(reportDirectory, "metadata-used.json"), root.GetRawText());
        var auditPath = Path.Combine(directory, "audit-result.json");
        if (File.Exists(auditPath)) File.Copy(auditPath, Path.Combine(reportDirectory, "data-audit.json"), true);
        foreach (var simulation in simulations) simulation.Save(reportDirectory);
        var results = simulations.Select(s => s.Result()).ToArray();
        var options = new JsonSerializerOptions { WriteIndented = true };
        File.WriteAllText(Path.Combine(reportDirectory, "results.json"), JsonSerializer.Serialize(new
        {
            source = "FxPro cTrader demo historical bid/ask ticks", dataVersion = 2, generatedUtc = DateTimeOffset.UtcNow,
            config = custom, quotes, meanSpread = quotes > 0 ? spreadSum / quotes : 0, profiles, crossed, files, warmupFiles, results,
            limitations = new[] { "Commission and swap use today's broker metadata, not historical rate schedules.",
                "Swap time uses FxPro published 21:59 UK time; exact historical platform billing not independently verified.",
                "Slippage is a fixed scenario; quote replay cannot prove available liquidity or live fill quality.",
                "Within-millisecond quote ties use minimum bid and maximum ask, a conservative approximation.",
                "Independent M1 bars differ from direct FxPro tick data by up to 0.04 USD/oz in three audited minutes; see data-audit.json.",
                "One-second entry delay; SL exits on next available executable quote, TP at limit. No forced end-of-period close.",
                "Reuses cBot AsiaSession rules. Initial days need warm-up. No optimizer. Earlier research also inspected this calendar period, so it is not a pristine unseen holdout." }
        }, options));
        Console.WriteLine(JsonSerializer.Serialize(results, options));
        Console.WriteLine("Report: " + reportDirectory);
    }
}

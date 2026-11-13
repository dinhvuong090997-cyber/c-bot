using System.Globalization;
using System.Text.Json;
using Xauusd;

sealed record ExecutionAccount(long Id, string Login, string Broker, bool Live);
sealed record ExecutionConfig(string Revision, string Report, string Run, ExecutionAccount Account,
    double RR, double RiskPercent, double MaxDrawdownPercent, double MinimumStop,
    double SpreadMultiplier, bool Asia, bool NewYork)
{
    public static ExecutionConfig FromReport(string id, JsonElement report, string runName, ExecutionAccount account)
    {
        var run = report.GetProperty("results").EnumerateArray().SingleOrDefault(r => r.GetProperty("name").GetString() == runName);
        if (run.ValueKind != JsonValueKind.Object) throw new ArgumentException("Select a completed backtest run.");
        var custom = report.TryGetProperty("config", out var c) ? JsonSerializer.Deserialize<ResearchConfig>(c.GetRawText(), ExecutionFiles.Json) : null;
        // Default reports predate custom configs and use the original fixed strategy settings.
        var result = new ExecutionConfig(Guid.NewGuid().ToString("N"), id, runName, account,
            ExecutionFiles.Number(run, "rr"), custom?.RiskPercent ?? .25, custom?.MaxDrawdownPercent ?? 5,
            custom?.MinimumStop ?? 2, custom?.SpreadMultiplier ?? 1.5, custom?.Asia ?? true, custom?.NewYork ?? true);
        result.Validate();
        return result;
    }
    public void Validate()
    {
        var values = new[] { RR, RiskPercent, MaxDrawdownPercent, MinimumStop, SpreadMultiplier };
        if (Account.Id <= 0 || string.IsNullOrWhiteSpace(Account.Login) || values.Any(v => !double.IsFinite(v)) ||
            RR is < .5 or > 5 || RiskPercent is < .01 or > 1 || MaxDrawdownPercent is < 1 or > 20 ||
            MinimumStop is < .1 or > 100 || SpreadMultiplier is < .1 or > 3 || !(Asia || NewYork))
            throw new ArgumentException("Invalid execution configuration.");
    }
}
static class ExecutionFiles
{
    public static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, PropertyNameCaseInsensitive = true, WriteIndented = true };
    public static double Number(JsonElement p, string name, double fallback = 0) =>
        p.TryGetProperty(name, out var v) ? double.Parse(v.ToString(), CultureInfo.InvariantCulture) : fallback;
    public static long Integer(JsonElement p, string name) => p.TryGetProperty(name, out var v) ? long.Parse(v.ToString(), CultureInfo.InvariantCulture) : 0;
    public static bool Flag(JsonElement p, string name) => p.TryGetProperty(name, out var v) && v.GetBoolean();
    public static IEnumerable<JsonElement> Items(JsonElement p, string name) => p.TryGetProperty(name, out var v) ? v.EnumerateArray() : Enumerable.Empty<JsonElement>();
    public static void Save(string path, object value)
    {
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        using (var file = new FileStream(temporary, new FileStreamOptions { Mode = FileMode.CreateNew, Access = FileAccess.Write, UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite }))
        { JsonSerializer.Serialize(file, value, Json); file.Flush(true); }
        File.Move(temporary, path, true);
    }
}
sealed class ExecutionRisk
{
    public double Peak { get; set; }
    public bool Halted { get; set; }
    public string? PendingOrder { get; set; }
    public DateTime LastAttempt { get; set; }
    public bool Update(double balance, double limit)
    {
        if (!double.IsFinite(balance) || balance <= 0) throw new InvalidOperationException("Invalid account balance.");
        Peak = Math.Max(Peak, balance);
        Halted |= balance <= Peak * (1 - limit / 100);
        return Halted;
    }
}
sealed class ExecutionSignal
{
    readonly AsiaSession asia = new();
    readonly ExecutionConfig config;
    (DateTime Due, EntrySession Session, AsiaProfile Profile)? pending;
    public DateTime LastAttempt;
    public ExecutionSignal(ExecutionConfig config) => this.config = config;
    public void Observe(DateTime time, double bid, double ask) => asia.Observe(time, bid, ask, config.SpreadMultiplier, config.MinimumStop);
    public AsiaProfile? Profile(DateTime time) => asia.GetProfile(AsiaSession.GetEntrySession(time, config.Asia, config.NewYork), time);
    public bool Eligible(AsiaProfile profile, DateTime time) => asia.GetProfile(AsiaSession.GetEntrySession(time, config.Asia, config.NewYork), time) == profile;
    public AsiaProfile? Ready(DateTime time, double bid, double ask, bool blocked)
    {
        var session = AsiaSession.GetEntrySession(time, config.Asia, config.NewYork);
        var profile = asia.GetProfile(session, time);
        if (blocked || profile is null) { pending = null; return null; }
        if (pending is { } p)
        {
            if (time < p.Due) return null;
            pending = null;
            return time - p.Due <= TimeSpan.FromSeconds(5) && p.Session == session && p.Profile == profile && ask - bid <= profile.SpreadLimit + 1e-9 ? profile : null;
        }
        var minute = time.AddTicks(-(time.Ticks % TimeSpan.TicksPerMinute));
        if (minute <= LastAttempt || ask - bid > profile.SpreadLimit + 1e-9) return null;
        LastAttempt = minute;
        pending = (time.AddSeconds(1), session, profile);
        return null;
    }
}
sealed record ExecutionOrder(long Volume, long RelativeStopLoss, long RelativeTakeProfit)
{
    public static ExecutionOrder? Size(ExecutionConfig c, double balance, double price, double distance, JsonElement symbol)
    {
        var digits = (int)ExecutionFiles.Number(symbol, "digits", -1);
        var min = ExecutionFiles.Integer(symbol, "minVolume"); var max = ExecutionFiles.Integer(symbol, "maxVolume"); var step = ExecutionFiles.Integer(symbol, "stepVolume");
        if (digits is < 0 or > 5 || min <= 0 || max < min || step <= 0 || balance <= 0 || price <= 0 || distance <= 0 ||
            !double.IsFinite(balance + price + distance)) throw new ArgumentException("Unsupported symbol sizing metadata.");
        double scale = Math.Pow(10, digits), stop = Math.Ceiling(distance * scale) / scale;
        double units = Math.Min(balance * c.RiskPercent / 100 / (stop + .17), balance / (price * 1.01));
        long volume = checked((long)Math.Floor(Math.Min(max, units * 100) / step) * step);
        if (volume < min) return null;
        return new(volume, checked((long)Math.Round(stop * 1e5)), checked((long)Math.Round(Math.Round(stop * c.RR, digits, MidpointRounding.AwayFromZero) * 1e5)));
    }
}

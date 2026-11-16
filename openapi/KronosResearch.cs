using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using Xauusd;

static class KronosResearch
{
    public static void Export(string[] args)
    {
        if (args.Length != 4) throw new ArgumentException("export-kronos START END OUTPUT.json");
        new ResearchConfig(Start: args[1], End: args[2]).Validate();
        var start = DateTime.ParseExact(args[1], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var end = DateTime.ParseExact(args[2], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var asia = new AsiaSession();
        var profiles = new SortedDictionary<DateOnly, AsiaProfile>();
        var bars = new List<object>(); var files = new List<object>();
        DateTime bucket = default, first = default, last = default;
        double open = 0, high = 0, low = 0, close = 0; long count = 0; int partial = 0;
        void Flush()
        {
            if (count == 0) return;
            if (first <= bucket.AddMinutes(1) && last >= bucket.AddMinutes(59) && count >= 100)
                bars.Add(new { time = DateTime.SpecifyKind(bucket, DateTimeKind.Utc), end = DateTime.SpecifyKind(bucket.AddHours(1), DateTimeKind.Utc), open, high, low, close });
            else partial++;
        }
        for (var day = start.AddDays(-10); day < end; day = day.AddDays(1))
        {
            var path = Path.Combine("data", "fxpro-v2", $"XAUUSD-{day:yyyy-MM-dd}.csv.gz");
            if (!File.Exists(path)) continue;
            foreach (var q in BacktestRunner.ReadQuotes(path))
            {
                if (!double.IsFinite(q.Bid + q.Ask) || q.Bid <= 0 || q.Ask < q.Bid) continue;
                var hour = q.Time.AddTicks(-(q.Time.Ticks % TimeSpan.TicksPerHour));
                if (hour != bucket) { Flush(); bucket = hour; first = q.Time; open = high = low = q.Bid; count = 0; }
                last = q.Time; close = q.Bid; high = Math.Max(high, q.Bid); low = Math.Min(low, q.Bid); count++;
                asia.Observe(q.Time, q.Bid, q.Ask, 1.5, 3);
                if (asia.GetProfile(EntrySession.NewYork, q.Time) is { } p) profiles[p.Date] = p;
            }
            using var file = File.OpenRead(path);
            files.Add(new { date = day.ToString("yyyy-MM-dd"), sha256 = Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant() });
        }
        Flush();
        var sessions = new List<object>(); var ny = TimeZoneInfo.FindSystemTimeZoneById("America/New_York");
        for (var day = start; day < end; day = day.AddDays(1))
        {
            if (day.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday) continue;
            var date = DateOnly.FromDateTime(day);
            var previous = profiles.Values.LastOrDefault(p => p.Date < date && date.DayNumber - p.Date.DayNumber <= 4);
            if (previous is not null) sessions.Add(new { cutoffUtc = DateTime.SpecifyKind(day, DateTimeKind.Utc), untilUtc = DateTime.SpecifyKind(day.AddHours(8), DateTimeKind.Utc), session = "Asia", bias = previous.IsLong ? 1 : -1, horizon = 8 });
            if (profiles.TryGetValue(date, out var today))
                sessions.Add(new { cutoffUtc = TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(day.AddHours(8), DateTimeKind.Unspecified), ny), untilUtc = TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(day.AddHours(17), DateTimeKind.Unspecified), ny), session = "NewYork", bias = today.IsLong ? 1 : -1, horizon = 9 });
        }
        File.WriteAllText(args[3], JsonSerializer.Serialize(new { schemaVersion = 1, source = "FxPro cached bid/ask merged ticks; bid H1", start = args[1], end = args[2], partialHoursExcluded = partial, bars, sessions, files }));
        Console.WriteLine($"Exported {bars.Count} H1 bars, {sessions.Count} session cutoffs; excluded {partial} incomplete hours.");
    }
}

sealed record KronosForecast(DateTimeOffset CutoffUtc, DateTimeOffset AvailableUtc, DateTimeOffset UntilUtc,
    string Session, int PredictedDirection, DateTimeOffset MaxInputCloseUtc)
{
    public bool Allows(DateTime time, EntrySession session, bool isLong, bool agreement) =>
        time >= AvailableUtc.UtcDateTime && time < UntilUtc.UtcDateTime && session.ToString() == Session &&
        (!agreement || PredictedDirection == (isLong ? 1 : -1));
    public static Dictionary<(DateOnly, EntrySession), KronosForecast> Load(string path)
    {
        if (new FileInfo(path).Length > 4_000_000) throw new ArgumentException("Forecast file too large.");
        var rows = JsonSerializer.Deserialize<KronosForecast[]>(File.ReadAllText(path), ExecutionFiles.Json) ?? throw new ArgumentException("Missing forecasts.");
        if (rows.Length is < 1 or > 732) throw new ArgumentException("Invalid forecast count.");
        var result = new Dictionary<(DateOnly, EntrySession), KronosForecast>();
        foreach (var row in rows)
        {
            if (row.Session is not ("Asia" or "NewYork") || row.PredictedDirection is < -1 or > 1 || row.MaxInputCloseUtc != row.CutoffUtc ||
                row.AvailableUtc < row.CutoffUtc || row.AvailableUtc >= row.UntilUtc ||
                row.UntilUtc - row.CutoffUtc != TimeSpan.FromHours(row.Session == "Asia" ? 8 : 9))
                throw new ArgumentException("Invalid or noncausal forecast window.");
            if (!result.TryAdd((DateOnly.FromDateTime(row.CutoffUtc.UtcDateTime), Enum.Parse<EntrySession>(row.Session)), row))
                throw new ArgumentException("Duplicate forecast window.");
        }
        return result;
    }
}

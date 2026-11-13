using System.Globalization;
using System.IO.Compression;
using System.Text.Json;

static class DataExport
{
    const long Account = 48463366;
    public static async Task Run(AppCredentials app, TokenSet tokens, string[] args)
    {
        using var api = new OpenApiConnection();
        await api.Connect(app, tokens);
        var symbols = await api.Request(2114, new { ctidTraderAccountId = Account }, 2115);
        var light = symbols.GetProperty("symbol").EnumerateArray().Single(s => s.GetProperty("symbolName").GetString() == "XAUUSD");
        long symbolId = long.Parse(light.GetProperty("symbolId").ToString());
        var details = await api.Request(2116, new { ctidTraderAccountId = Account, symbolId = new[] { symbolId } }, 2117);
        var trader = await api.Request(2121, new { ctidTraderAccountId = Account }, 2122);
        var assets = await api.Request(2112, new { ctidTraderAccountId = Account }, 2113);
        var t = trader.GetProperty("trader");
        var metadata = new { source = "FxPro cTrader demo Open API", capturedUtc = DateTimeOffset.UtcNow,
            lightSymbol = light, symbol = details.GetProperty("symbol")[0], assets = assets.GetProperty("asset"),
            account = new { depositAssetId = t.GetProperty("depositAssetId"),
                swapFree = t.TryGetProperty("swapFree", out var sf) && sf.GetBoolean() } };
        var directory = Path.Combine("data", "fxpro-v2");
        Directory.CreateDirectory(directory);
        await File.WriteAllTextAsync(Path.Combine(directory, "metadata.json"), JsonSerializer.Serialize(metadata, new JsonSerializerOptions { WriteIndented = true }));
        Console.WriteLine("XAUUSD symbol " + symbolId + "; metadata saved.");
        if (args.Length == 2 && args[1] == "probe")
        {
            var endProbe = new DateTimeOffset(2026, 11, 11, 8, 1, 0, TimeSpan.Zero).ToUnixTimeMilliseconds();
            var probe = await api.Request(2145, new { ctidTraderAccountId = Account, symbolId, type = 1, fromTimestamp = endProbe - 86400000, toTimestamp = endProbe - 1 }, 2146);
            Console.WriteLine("hasMore=" + probe.GetProperty("hasMore"));
            if (probe.TryGetProperty("tickData", out var raw))
            { Console.WriteLine("count=" + raw.GetArrayLength()); foreach (var tick in raw.EnumerateArray().Take(3)) Console.WriteLine(tick); }
            return;
        }
        if (args.Length == 2 && args[1] == "audit")
        {
            var auditStart = new DateTimeOffset(2026, 1, 2, 0, 0, 0, TimeSpan.Zero).ToUnixTimeMilliseconds();
            var bars = await api.Request(2137, new { ctidTraderAccountId = Account, symbolId, period = 1,
                fromTimestamp = auditStart, toTimestamp = auditStart + 86400000 - 1 }, 2138);
            await File.WriteAllTextAsync(Path.Combine(directory, "audit-bars.json"), bars.GetRawText());
            var checks = new List<object>();
            foreach (var minute in new[] { 124, 152, 170, 263 })
            {
                var raw = await api.Request(2145, new { ctidTraderAccountId = Account, symbolId, type = 1,
                    fromTimestamp = auditStart + minute * 60000, toTimestamp = auditStart + (minute + 1) * 60000 - 1 }, 2146);
                checks.Add(new { minute, response = raw });
            }
            await File.WriteAllTextAsync(Path.Combine(directory, "audit-direct-minutes.json"), JsonSerializer.Serialize(checks));
            Console.WriteLine("Saved independent M1 bars and direct tick minutes for audit.");
            return;
        }
        if (args.Length < 3) return;
        var start = DateTimeOffset.Parse(args[1], CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal).ToUniversalTime();
        var end = DateTimeOffset.Parse(args[2], CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal).ToUniversalTime();
        if (start.TimeOfDay != TimeSpan.Zero || end.TimeOfDay != TimeSpan.Zero || end <= start || end > DateTimeOffset.UtcNow.Date)
            throw new ArgumentException("Use complete UTC days, start inclusive and end exclusive.");
        for (var day = start; day < end; day = day.AddDays(1))
        {
            var path = Path.Combine(directory, "XAUUSD-" + day.ToString("yyyy-MM-dd") + ".csv.gz");
            if (File.Exists(path)) { Console.WriteLine(day.ToString("yyyy-MM-dd") + " cached"); continue; }
            var ticks = new List<(long Time, int Side, long Price)>();
            for (int side = 1; side <= 2; side++)
                ticks.AddRange(await TickHistory.Fetch(api, Account, symbolId, day.ToUnixTimeMilliseconds(), day.AddDays(1).ToUnixTimeMilliseconds(), side));
            ticks.Sort((a, b) => a.Time != b.Time ? a.Time.CompareTo(b.Time) : a.Side.CompareTo(b.Side));
            var temp = path + ".tmp";
            await using (var file = File.Create(temp))
            await using (var gzip = new GZipStream(file, CompressionLevel.Fastest))
            await using (var writer = new StreamWriter(gzip))
            {
                await writer.WriteLineAsync("timestamp_ms,side,price_1e5");
                foreach (var tick in ticks)
                    await writer.WriteLineAsync($"{tick.Time},{tick.Side},{tick.Price}");
            }
            File.Move(temp, path, true);
            Console.WriteLine(day.ToString("yyyy-MM-dd") + " " + ticks.Count + " quote updates");
        }
    }
}

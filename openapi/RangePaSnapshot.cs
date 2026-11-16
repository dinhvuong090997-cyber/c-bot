using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;

static class RangePaSnapshot
{
    public static void Export(string[] args)
    {
        if (args.Length != 4) throw new ArgumentException("export-range-pa START END ASSET_DIR (up to3days, end exclusive)");
        new ResearchConfig(Start: args[1], End: args[2]).Validate();
        var start = DateTime.ParseExact(args[1], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        var end = DateTime.ParseExact(args[2], "yyyy-MM-dd", CultureInfo.InvariantCulture);
        if ((end - start).TotalDays > 3) throw new ArgumentException("Export at most3days at once.");
        Directory.CreateDirectory(args[3]);
        var entries = new List<object>(); var json = ExecutionFiles.Json;
        for (var day = start; day < end; day = day.AddDays(1))
        {
            var path = Path.Combine("data", "fxpro-v2", $"XAUUSD-{day:yyyy-MM-dd}.csv.gz");
            var sizes = new[] { 2, 3, 5 };
            var engines = sizes.Select(r => new RangeSupplyDemand(r, 3, true)).ToArray();
            var bars = sizes.Select(_ => new List<object>()).ToArray();
            var events = sizes.Select(_ => new List<RangeSupplyDemand.PaEvent>()).ToArray();
            for (int i = 0; i < sizes.Length; i++)
            {
                int n = i;
                engines[i].OnBar = (b, index) => bars[n].Add(new { time = index, b.Open, b.High, b.Low, b.Close, startUtc = b.Start, endUtc = b.End });
                engines[i].OnEvent = events[n].Add;
            }
            foreach (var q in BacktestRunner.ReadQuotes(path))
                if (double.IsFinite(q.Bid + q.Ask) && q.Bid > 0 && q.Ask >= q.Bid)
                    foreach (var engine in engines) engine.Observe(q);
            using var input = File.OpenRead(path); var hash = Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant();
            for (int i = 0; i < sizes.Length; i++)
            {
                var name = $"range-pa-{day:yyyy-MM-dd}-r{sizes[i]}.json";
                File.WriteAllText(Path.Combine(args[3], name), JsonSerializer.Serialize(new { schemaVersion = 1, date = day.ToString("yyyy-MM-dd"), rangeUsdOz = sizes[i], source = "Recorded FxPro bid ticks", sourceSha256 = hash, rule = "Base + two departures, first retest, PA rejection; research only", bars = bars[i], events = events[i], diagnostics = engines[i].Diagnostics() }, json));
                entries.Add(new { date = day.ToString("yyyy-MM-dd"), rangeUsdOz = sizes[i], file = name, bars = bars[i].Count });
            }
        }
        File.WriteAllText(Path.Combine(args[3], "range-pa-index.json"), JsonSerializer.Serialize(new { schemaVersion = 1, entries }, json));
        Console.WriteLine($"Exported {entries.Count} read-only PA snapshots; no trading controls.");
    }
}

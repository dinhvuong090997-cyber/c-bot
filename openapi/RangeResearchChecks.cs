using System.Text.Json;
using Xauusd;

static class RangeResearchChecks
{
    static void Check(bool value, string message)
    { if (!value) throw new InvalidOperationException("Range PA check failed: " + message); }
    public static void Run()
    {
        var day = new DateTime(2026, 1, 5, 13, 0, 0, DateTimeKind.Utc);
        var book = new RangeBarBook(2);
        Check(book.Observe(day, 100) is null && book.Observe(day.AddSeconds(1), 101.99) is null, "partial bar not emitted");
        var bar = book.Observe(day.AddSeconds(2), 102);
        Check(bar is { Open: 100, High: 102, Low: 100, Close: 102 }, "threshold closes at actual tick");
        Check(book.Observe(day.AddSeconds(3), 110) is null, "next quote opens next bar without synthetic bridge");
        bar = book.Observe(day.AddSeconds(4), 106);
        Check(bar is { Open: 110, Close: 106 } && book.ClosedBars == 2 && book.Overshoots == 1, "gap overshoot does not invent multiple bars");
        book.Observe(day.AddSeconds(5), 100);
        Check(book.Observe(day.AddMinutes(2), 110) is null && book.Resets == 1, "long quote gap discards partial bar");
        var strategy = new RangeSupplyDemand(2, 3);
        var events = new List<RangeSupplyDemand.PaEvent>(); strategy.OnEvent = events.Add;
        void Bar(int n, double o, double h, double l, double c) => strategy.ObserveBar(new(day.AddSeconds(n * 10), day.AddSeconds(n * 10 + 9), o, h, l, c));
        Bar(0, 100, 101, 99, 100.2);
        Bar(1, 100.3, 102.3, 100.3, 102.3);
        Check(strategy.Zone is null && events.Count == 0, "zone requires second closed departure");
        Bar(2, 102.4, 104.4, 102.4, 104.4);
        Check(strategy.Zone is { Long: true, Low: 99, High: 101 }, "demand zone confirmed causally");
        Check(events.Single().Kind == "created" && events[0].Utc == day.AddSeconds(29) && events[0].ZoneId == 3, "chart zone starts only after departure confirmation");
        strategy.ObserveQuote(day.AddSeconds(30), 101, 101.1);
        Check(events[^1].Kind == "retest" && events[^1].Utc > events[0].Utc, "chart retest retains actual tick timing");
        Bar(3, 102, 102, 100, 101.5);
        Check(strategy.Signal is null, "bearish retest does not confirm buy");
        Bar(4, 100.5, 103.5, 100.5, 103.5);
        Check(strategy.Signal is null, "close too far from zone cannot chase");
        // Use a fresh instance to isolate the qualifying first retest.
        strategy = new RangeSupplyDemand(2, 3);
        Bar(0, 100, 101, 99, 100.2); Bar(1, 100.3, 102.3, 100.3, 102.3); Bar(2, 102.4, 104.4, 102.4, 104.4);
        strategy.ObserveQuote(day.AddSeconds(30), 101, 101.1);
        Bar(3, 100, 102, 100, 102);
        Check(strategy.Signal is { IsLong: true }, "first retest bullish rejection creates buy");
        Check(Math.Abs(strategy.StopDistance(102.1, 102.2, .1) - 3.5) < 1e-8, "stop beyond distal includes actual entry slip and buffer");
        Check(strategy.Profile(day.AddSeconds(46)) is null, "stale signal expires");
        strategy = new RangeSupplyDemand(2, 3);
        Bar(0, 100, 101, 99, 99.8); Bar(1, 99.7, 99.7, 97.7, 97.7); Bar(2, 97.6, 97.6, 95.6, 95.6);
        Check(strategy.Zone is { Long: false }, "supply mirrors demand");
        strategy.ObserveQuote(day.AddSeconds(30), 99, 99.1);
        Bar(3, 100, 100, 98, 98);
        Check(strategy.Signal is { IsLong: false }, "supply retest bearish rejection creates sell");
        Check(strategy.TargetPrice == 95.6, "supply target uses prior departure low");
        var before = strategy.ZonesCreated;
        strategy.ObserveQuote(day.AddMinutes(5), 105, 105.1);
        Check(strategy.Profile(day.AddMinutes(5)) is null && strategy.Zone is null && strategy.ZonesCreated == before, "gap resets signal/zone without generating a trade");
        strategy = new RangeSupplyDemand(2, 3);
        Bar(0, 100, 101, 99, 100.2); Bar(1, 100.3, 102.3, 100.3, 102.3); Bar(2, 102.4, 104.4, 102.4, 104.4);
        strategy.ObserveQuote(day.AddSeconds(30), 98.9, 99);
        Check(strategy.Zone is null && strategy.Invalidated == 1, "distal breach invalidates zone before confirmation");
        strategy = new RangeSupplyDemand(2, 3);
        Bar(0, 100, 101, 99, 100.2); Bar(1, 100.3, 102.3, 100.3, 102.3); Bar(2, 102.4, 104.4, 102.4, 104.4);
        strategy.ObserveQuote(day.AddSeconds(30), 101, 101.1);
        for (int i = 3; i <= 6; i++) Bar(i, 102, 102, 100, 100);
        Check(strategy.Zone is null && strategy.Signal is null && strategy.Expired == 1, "first retest cannot wait indefinitely for a later good bounce");
        strategy = new RangeSupplyDemand(2, 3, true);
        Bar(0, 100, 101, 99, 100.2); Bar(1, 100.3, 102.3, 100.3, 102.3); Bar(2, 102.4, 104.4, 102.4, 104.4);
        strategy.ObserveQuote(day.AddSeconds(30), 101, 101.1); Bar(3, 100, 102, 100, 102);
        Check(strategy.TargetPrice == 104.4 && strategy.Profile(day.AddSeconds(38)) is null, "target known at zone creation; no future confirmation access");
        strategy.ObserveQuote(day.AddSeconds(40), 104.3, 104.4);
        Check(strategy.Signal is null, "do not buy after ask reaches high target");
        Console.WriteLine("Range PA checks PASS: real-price bars, overshoot/gaps, causal zones, mirrored first retests, stops and expiry.");
    }
}

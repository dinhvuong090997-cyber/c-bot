static class SmcResearchChecks
{
    static void Check(bool value, string message)
    { if (!value) throw new InvalidOperationException("SMC check failed: " + message); }
    public static void Run()
    {
        var day = new DateTime(2026, 1, 5, 0, 0, 0, DateTimeKind.Utc);
        var smc = new SmcResearch();
        void Bar(int i, double high, double low, double close) => smc.Observe(new(day.AddMinutes(i * 5), close, high, low, close));
        Bar(0, 102, 99, 100); Bar(1, 104, 98, 101); Bar(2, 110, 90, 100);
        Bar(3, 105, 97, 101);
        Check(smc.SwingHigh is null && smc.SwingLow is null, "pivot cannot confirm before right-hand closes");
        Bar(4, 103, 99, 101);
        Check(smc.SwingHigh == 110 && smc.SwingLow == 90, "two-left two-right pivot confirms causally");
        Bar(5, 111, 99, 109);
        Check(smc.Allows(day.AddMinutes(30), true, "sweep") == false && smc.Allows(day.AddMinutes(30), false, "sweep"), "upper sweep confirms sell, wick is not BOS");
        Check(!smc.Allows(day.AddMinutes(35), false, "sweep"), "event expires after one M5");
        Bar(6, 112, 100, 111);
        Check(smc.Allows(day.AddMinutes(35), true, "structure") && smc.Trend == 1, "close beyond pivot confirms first upward structure break");
        Bar(7, 113, 100, 112);
        Check(!smc.Allows(day.AddMinutes(40), true, "structure"), "same pivot cannot trigger another close break");
        Bar(8, 101, 89, 91);
        Check(smc.Allows(day.AddMinutes(45), true, "sweep"), "lower sweep mirrors upper sweep");
        Bar(9, 100, 88, 89);
        Check(smc.Allows(day.AddMinutes(50), false, "structure") && smc.Trend == -1 && smc.LastChangeOfCharacter, "opposite structure break is CHoCH");
        Bar(12, 103, 99, 101);
        Check(smc.SwingHigh is null && smc.SwingLow is null && smc.Trend == 0, "missing M5 resets stale structure");
        var ambiguous = new SmcResearch();
        foreach (var b in new[] { new M5Confirmation.Bar(day, 100, 102, 99, 100), new(day.AddMinutes(5), 100, 104, 98, 100), new(day.AddMinutes(10), 100, 110, 90, 100), new(day.AddMinutes(15), 100, 105, 97, 100), new(day.AddMinutes(20), 100, 103, 99, 100), new(day.AddMinutes(25), 100, 111, 89, 100) })
            ambiguous.Observe(b);
        Check(!ambiguous.Allows(day.AddMinutes(30), true, "sweep") && !ambiguous.Allows(day.AddMinutes(30), false, "sweep"), "dual-sided sweep does not choose a direction");
        Check(!smc.Allows(day, true, "structure"), "event cannot be read before confirmation time");
        var fvg = new SmcResearch();
        fvg.Observe(new(day, 100, 101, 99, 100));
        fvg.Observe(new(day.AddMinutes(5), 100, 106, 100, 105));
        Check(!fvg.Allows(day.AddMinutes(10), true, "fvg"), "FVG requires third completed candle");
        fvg.Observe(new(day.AddMinutes(10), 104, 107, 103, 106));
        Check(fvg.Allows(day.AddMinutes(15), true, "fvg") && !fvg.Allows(day.AddMinutes(15), false, "fvg"), "bullish three-candle gap");
        fvg.Observe(new(day.AddMinutes(15), 102, 103, 97, 98));
        fvg.Observe(new(day.AddMinutes(20), 98, 99, 95, 96));
        Check(fvg.Allows(day.AddMinutes(25), false, "fvg"), "bearish gap mirrors bullish");
        fvg.Reset();
        Check(!fvg.Allows(day.AddMinutes(25), false, "fvg"), "incomplete candle clears prior signal");
        var aggregate = new M5Confirmation();
        aggregate.Observe(day, 100); aggregate.Observe(day.AddMinutes(2), 105);
        aggregate.Observe(day.AddMinutes(3), 98); aggregate.Observe(day.AddMinutes(4).AddSeconds(59), 102);
        var closed = aggregate.Observe(day.AddMinutes(5), 200);
        Check(closed is { Open: 100, High: 105, Low: 98, Close: 102 }, "OHLC excludes next-candle first tick");
        Check(aggregate.Observe(day.AddMinutes(5).AddSeconds(1), 201) is null, "closed candle emitted once");
        Console.WriteLine("SMC checks PASS: causal pivots, BOS/CHoCH, mirrored sweeps/FVG, expiry, gap reset and tick OHLC.");
    }
}

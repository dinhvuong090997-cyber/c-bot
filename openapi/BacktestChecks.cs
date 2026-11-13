using System.Text.Json;
using Xauusd;

static class BacktestChecks
{
    static void Check(bool condition, string message)
    { if (!condition) throw new InvalidOperationException("Backtest check failed: " + message); }
    public static void Run()
    {
        using var doc = JsonDocument.Parse("""
        {"digits":2,"pipPosition":2,"commissionType":1,"preciseTradingCommissionRate":3500000000,
         "swapCalculationType":0,"swapLong":-10,"swapShort":5,"swapRollover3Days":3,
         "stepVolume":100,"minVolume":100,"maxVolume":5000000}
        """);
        var day = new DateTime(2026, 1, 7, 13, 0, 0, DateTimeKind.Utc); // Wednesday
        BacktestRunner.Simulation New(double slip = 0) => new(new(50000, 1.5, slip, true, day.Date, day.Date.AddDays(2)), doc.RootElement);
        BacktestRunner.Quote Q(DateTime time, double bid, double ask) => new(new DateTimeOffset(time).ToUnixTimeMilliseconds(), bid, ask);
        var profile = new AsiaProfile(DateOnly.FromDateTime(day), true, 2, 1);
        void Start(BacktestRunner.Simulation sim)
        {
            sim.Observe(Q(day, 100, 100.1), EntrySession.NewYork, profile);
            Check(JsonSerializer.SerializeToElement(sim.Result()).GetProperty("openPositions").GetInt32() == 0, "one-second entry delay");
            sim.Observe(Q(day.AddSeconds(1), 100, 100.1), EntrySession.NewYork, profile);
            Check(JsonSerializer.SerializeToElement(sim.Result()).GetProperty("openPositions").GetInt32() == 1, "entry on delayed quote");
        }
        var tp = New(); Start(tp);
        tp.Observe(Q(day.AddSeconds(2), 101, 101.1), EntrySession.NewYork, profile);
        tp.Observe(Q(day.AddSeconds(3), 104, 104.1), EntrySession.Closed, null);
        var fill = JsonSerializer.SerializeToElement(tp.Trades[0]);
        var volume = 57.0;
        var expectedCommission = 35e-6 * volume * (100.1 + 103.1);
        Check(tp.Trades.Count == 1 && Math.Abs(fill.GetProperty("exit").GetDouble() - 103.1) < 1e-9, "single position and TP limit fill");
        Check(Math.Abs(fill.GetProperty("net").GetDouble() - (3 * volume - expectedCommission)) < 1e-8, "USD commission both sides and unit sizing");
        var gap = New(0.1); Start(gap);
        gap.Observe(Q(day.AddSeconds(2), 97, 97.1), EntrySession.Closed, null);
        var gapFill = JsonSerializer.SerializeToElement(gap.Trades[0]);
        Check(Math.Abs(gapFill.GetProperty("exit").GetDouble() - 96.9) < 1e-9, "gap SL with adverse slippage, not idealized stop price");
        var overnight = New(); Start(overnight);
        overnight.Observe(Q(day.Date.AddDays(1).AddHours(1), 100, 100.1), EntrySession.Closed, null);
        overnight.Observe(Q(day.Date.AddDays(1).AddHours(2), 104, 104.1), EntrySession.Closed, null);
        Check(Math.Abs(JsonSerializer.SerializeToElement(overnight.Trades[0]).GetProperty("swap").GetDouble() - (-0.1 * 57 * 3)) < 1e-8, "Wednesday triple swap");
        var stale = New();
        stale.Observe(Q(day, 100, 100.1), EntrySession.NewYork, profile);
        stale.Observe(Q(day.AddSeconds(7), 100, 100.1), EntrySession.NewYork, profile);
        Check(JsonSerializer.SerializeToElement(stale.Result()).GetProperty("openPositions").GetInt32() == 0, "stale pending signal rejected");
        var halted = New();
        for (int i = 0; i < 60; i++)
        {
            var time = day.AddMinutes(i);
            halted.Observe(Q(time, 100, 100.1), EntrySession.NewYork, profile);
            halted.Observe(Q(time.AddSeconds(1), 100, 100.1), EntrySession.NewYork, profile);
            halted.Observe(Q(time.AddSeconds(2), 97.9, 98), EntrySession.NewYork, profile);
        }
        Check(halted.Halted && halted.Trades.Count < 60 && JsonSerializer.SerializeToElement(halted.Result()).GetProperty("openPositions").GetInt32() == 0, "5% drawdown halts re-entry");
        var asia = new AsiaSession();
        var midnight = day.Date;
        for (int i = 0; i <= 478; i++)
            asia.Observe(midnight.AddMinutes(i), 100 + i * 0.01, 100.1 + i * 0.01, 1.5, 2);
        for (int i = 0; i < 60; i++)
            asia.Observe(midnight.AddHours(7).AddMinutes(59).AddSeconds(i), 105, 105.1, 1.5, 2);
        Check(asia.GetProfile(EntrySession.NewYork, midnight.AddHours(7)) is null, "no unfinished same-day profile");
        asia.Observe(midnight.AddHours(8), 106, 106.1, 1.5, 2);
        Check(asia.GetProfile(EntrySession.NewYork, midnight.AddHours(13)) is { IsLong: true }, "complete Asia profile");
        asia.Observe(midnight.AddDays(1), 106, 106.1, 1.5, 2);
        Check(asia.GetProfile(EntrySession.Asia, midnight.AddDays(1))?.Date == DateOnly.FromDateTime(midnight), "Asia uses previous completed day");
        Check(AsiaSession.GetEntrySession(new DateTime(2026, 3, 9, 12, 0, 0, DateTimeKind.Utc), true, true) == EntrySession.NewYork, "New York DST");
        Console.WriteLine("PASS: entry delay, one position, TP limit, SL gap/slippage, commission/sizing, triple swap, stale signals, profile lookahead and DST.");
    }
}

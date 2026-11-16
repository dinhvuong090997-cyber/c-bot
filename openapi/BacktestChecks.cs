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
        using var research = JsonDocument.Parse("""{"researchOnly":true}""");
        bool rejected = false;
        try { ExecutionConfig.FromReport("pa", research.RootElement, "run", new(1, "test", "fake", false)); }
        catch (ArgumentException) { rejected = true; }
        Check(rejected, "research-only PA report cannot change live config");
        var fc = new KronosForecast(day, day.AddMinutes(1), day.AddHours(9), "NewYork", -1, day);
        Check(!fc.Allows(day, EntrySession.NewYork, true, false) && !fc.Allows(day.AddHours(9), EntrySession.NewYork, false, true), "forecast unavailable before inference or after expiry");
        Check(fc.Allows(day.AddMinutes(1), EntrySession.NewYork, true, false) && !fc.Allows(day.AddMinutes(1), EntrySession.NewYork, true, true), "coverage control independent from agreement");
        Check(fc.Allows(day.AddMinutes(1), EntrySession.NewYork, false, true) && !fc.Allows(day.AddMinutes(1), EntrySession.Asia, false, true), "forecast direction and session routing");
        var forecastFile = Path.GetTempFileName();
        try
        {
            File.WriteAllText(forecastFile, JsonSerializer.Serialize(new[] { fc with { MaxInputCloseUtc = day.AddHours(1) } }));
            bool rejectedFuture = false;
            try { KronosForecast.Load(forecastFile); } catch (ArgumentException) { rejectedFuture = true; }
            Check(rejectedFuture, "forecast loader rejects future feature cutoff");
        }
        finally { File.Delete(forecastFile); }
        var disagree = new BacktestRunner.Simulation(new(50000, 5, .1, true, day.Date, day.Date.AddDays(2), KronosGate: "agree"), doc.RootElement);
        disagree.Observe(Q(day.AddMinutes(1), 100, 100.1), EntrySession.NewYork, profile, fc);
        disagree.Observe(Q(day.AddMinutes(1).AddSeconds(1), 100, 100.1), EntrySession.NewYork, profile, fc);
        Check(disagree.TotalCommission == 0 && JsonSerializer.SerializeToElement(disagree.Result()).GetProperty("openPositions").GetInt32() == 0, "Kronos disagreement blocks entry before fee");
        SmcResearchChecks.Run();
        RangeResearchChecks.Run();
        var candle = new M5Confirmation();
        candle.Observe(day, 100);
        candle.Observe(day.AddMinutes(4).AddSeconds(59), 101);
        Check(!candle.Allows(day.AddMinutes(4).AddSeconds(59), true), "unfinished M5 cannot confirm");
        candle.Observe(day.AddMinutes(5), 99);
        Check(candle.Allows(day.AddMinutes(5), true) && !candle.Allows(day.AddMinutes(5), false), "closed bullish M5 only confirms buy");
        candle.Observe(day.AddMinutes(9).AddSeconds(59), 98);
        candle.Observe(day.AddMinutes(10), 102);
        Check(candle.Allows(day.AddMinutes(10), false) && !candle.Allows(day.AddMinutes(10), true), "closed bearish M5 only confirms sell");
        candle.Observe(day.AddMinutes(14).AddSeconds(59), 102);
        candle.Observe(day.AddMinutes(15), 103);
        Check(!candle.Allows(day.AddMinutes(15), true) && !candle.Allows(day.AddMinutes(15), false), "doji blocks both sides");
        candle.Observe(day.AddMinutes(30), 104);
        Check(!candle.Allows(day.AddMinutes(30), true), "gap invalidates stale confirmation");
        var partial = new M5Confirmation();
        partial.Observe(day.AddMinutes(1), 100);
        partial.Observe(day.AddMinutes(4).AddSeconds(59), 101);
        partial.Observe(day.AddMinutes(5), 102);
        Check(!partial.Allows(day.AddMinutes(5), true), "partial first M5 is rejected");
        var filtered = new BacktestRunner.Simulation(new(50000, 1.5, 0, true, day.Date, day.Date.AddDays(2), PaM5: true), doc.RootElement);
        filtered.Observe(Q(day, 100, 100.1), EntrySession.NewYork, profile);
        filtered.Observe(Q(day.AddSeconds(1), 100, 100.1), EntrySession.NewYork, profile);
        Check(JsonSerializer.SerializeToElement(filtered.Result()).GetProperty("openPositions").GetInt32() == 0, "PA blocks entry without closed M5");
        filtered.Observe(Q(day.AddMinutes(4).AddSeconds(59), 101, 101.1), EntrySession.NewYork, profile);
        filtered.Observe(Q(day.AddMinutes(5), 101, 101.1), EntrySession.NewYork, profile);
        filtered.Observe(Q(day.AddMinutes(5).AddSeconds(1), 101, 101.1), EntrySession.NewYork, profile);
        Check(JsonSerializer.SerializeToElement(filtered.Result()).GetProperty("openPositions").GetInt32() == 1, "PA allows delayed entry after matching M5");
        var smcSim = new BacktestRunner.Simulation(new(50000, 1.5, 0, true, day.Date, day.Date.AddDays(2), SmcFilter: "fvg"), doc.RootElement);
        foreach (var (offset, price) in new[] { (0, 100.0), (299, 101.0), (300, 102.0), (599, 106.0), (600, 104.0), (899, 107.0) })
            smcSim.Observe(Q(day.AddSeconds(offset), price, price + .1), EntrySession.NewYork, profile);
        Check(JsonSerializer.SerializeToElement(smcSim.Result()).GetProperty("openPositions").GetInt32() == 0, "SMC cannot enter on unfinished third FVG candle");
        smcSim.Observe(Q(day.AddMinutes(15), 106, 106.1), EntrySession.NewYork, profile);
        Check(JsonSerializer.SerializeToElement(smcSim.Result()).GetProperty("openPositions").GetInt32() == 0, "SMC retains entry delay");
        smcSim.Observe(Q(day.AddMinutes(15).AddSeconds(1), 106, 106.1), EntrySession.NewYork, profile);
        Check(JsonSerializer.SerializeToElement(smcSim.Result()).GetProperty("openPositions").GetInt32() == 1, "SMC gate reaches simulator after closed FVG");
        var rangeSim = new BacktestRunner.Simulation(new(50000, 2, .1, true, day.Date, day.Date.AddDays(2), RangeSize: 2, MinimumStop: 3), doc.RootElement);
        var prices = new[] { 100.0, 98.3, 100.3, 100.4, 102.4, 102.5, 104.5, 104.4, 100.2, 100.1, 102.1 };
        for (int i = 0; i < prices.Length; i++) rangeSim.Observe(Q(day.AddSeconds(i), prices[i], prices[i] + .1), EntrySession.NewYork, null);
        Check(JsonSerializer.SerializeToElement(rangeSim.Result()).GetProperty("openPositions").GetInt32() == 0, "range strategy waits for executable delayed quote");
        rangeSim.Observe(Q(day.AddSeconds(11), 102.1, 102.2), EntrySession.NewYork, null);
        Check(JsonSerializer.SerializeToElement(rangeSim.Result()).GetProperty("openPositions").GetInt32() == 1, "raw ticks produce range PA order independent of Asia direction");
        rangeSim.Observe(Q(day.AddSeconds(12), 98, 98.1), EntrySession.Closed, null);
        var rangeFill = JsonSerializer.SerializeToElement(rangeSim.Trades.Single());
        Check(Math.Abs(rangeFill.GetProperty("Stop").GetDouble() - 98.1) < 1e-8 && Math.Abs(rangeFill.GetProperty("Entry").GetDouble() - 102.3) < 1e-8, "range fill recalculates stop outside demand using actual bid/ask and slip");
        var hlRange = new BacktestRunner.Simulation(new(50000, 5, .1, true, day.Date, day.Date.AddDays(2), RangeSize: 2, MinimumStop: 3, RangeHighLow: true), doc.RootElement);
        for (int i = 0; i < prices.Length; i++) hlRange.Observe(Q(day.AddSeconds(i), prices[i], prices[i] + .1), EntrySession.NewYork, null);
        hlRange.Observe(Q(day.AddSeconds(11), 102.1, 102.2), EntrySession.NewYork, null);
        hlRange.Observe(Q(day.AddSeconds(12), 104.6, 104.7), EntrySession.Closed, null);
        var hlFill = JsonSerializer.SerializeToElement(hlRange.Trades.Single());
        Check(Math.Abs(hlFill.GetProperty("Target").GetDouble() - 104.5) < 1e-8 && hlFill.GetProperty("reason").GetString() == "TP", "range HL target is known departure high, not configured fixed RR");
        var hlDetail = JsonSerializer.SerializeToElement(hlRange.RangeTrades.Single());
        Check(Math.Abs(hlDetail.GetProperty("initialRR").GetDouble() - 2.2 / 4.2) < 1e-8, "range HL reports actual reward/risk");
        var minRR = new BacktestRunner.Simulation(new(50000, 5, .1, true, day.Date, day.Date.AddDays(2), RangeSize: 2, MinimumStop: 3, RangeHighLow: true, MinimumEntryRR: 3), doc.RootElement);
        for (int i = 0; i < prices.Length; i++) minRR.Observe(Q(day.AddSeconds(i), prices[i], prices[i] + .1), EntrySession.NewYork, null);
        minRR.Observe(Q(day.AddSeconds(11), 102.1, 102.2), EntrySession.NewYork, null);
        Check(minRR.SkippedRR == 1 && minRR.TotalCommission == 0 && minRR.Balance == 50000 && JsonSerializer.SerializeToElement(minRR.Result()).GetProperty("openPositions").GetInt32() == 0, "minimum3R rejects low-payoff setup before any fees or position");
        Check(BacktestRunner.MeetsMinimumRR(100, 97, 109, 3) && BacktestRunner.MeetsMinimumRR(100, 103, 91, 3), "exact3R accepted for buy and sell");
        Check(!BacktestRunner.MeetsMinimumRR(100, 97, 108.99, 3) && !BacktestRunner.MeetsMinimumRR(100, 103, 91.01, 3), "below3R rejected on both sides");
        var toolkit = new BacktestRunner.Simulation(new(50000,5,.1,true,day.Date,day.Date.AddDays(2),RangeSize:2,MinimumStop:3,PaToolkit:"swing",MinimumEntryRR:3),doc.RootElement);
        for(int i=0;i<prices.Length;i++)toolkit.Observe(Q(day.AddSeconds(49+i),prices[i],prices[i]+.1),EntrySession.NewYork,null);
        toolkit.Observe(Q(day.AddSeconds(60),102.1,102.2),EntrySession.NewYork,null);
        Check(toolkit.SkippedRR==1&&toolkit.Balance==50000&&toolkit.TotalCommission==0,"toolkit rejects known low-RR swing before fees");
        var strictSpec = JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(doc.RootElement.GetRawText())!;
        strictSpec["minVolume"] = JsonSerializer.SerializeToElement(10000);
        var skipRange = new BacktestRunner.Simulation(new(50000, 2, .1, true, day.Date, day.Date.AddDays(2), RangeSize: 2, MinimumStop: 3), JsonSerializer.SerializeToElement(strictSpec));
        for (int i = 0; i < prices.Length; i++) skipRange.Observe(Q(day.AddSeconds(49 + i), prices[i], prices[i] + .1), EntrySession.NewYork, null);
        for (int i = 60; i <= 63; i++) skipRange.Observe(Q(day.AddSeconds(i), 102.1, 102.2), EntrySession.NewYork, null);
        Check(skipRange.SkippedVolume == 1, "range zone only one sizing/order attempt across minute boundary");
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
        Console.WriteLine("PASS: entry delay, one position, TP limit, SL gap/slippage, commission/sizing, triple swap, stale signals, profile lookahead, DST, closed M5 confirmation and research-only execution guard.");
    }
}

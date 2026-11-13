using System.Text.Json;
using Xauusd;
using static ExecutionFiles;

static class TickHistory
{
    public static async Task<List<(long Time, int Side, long Price)>> Fetch(IExecutionConnection api, long account, long symbol,
        long from, long to, int side, Func<bool>? stopped = null)
    {
        if (from < 1 || to <= from || to - from > 86400000 || side is not (1 or 2)) throw new ArgumentException("Invalid tick history interval.");
        var ticks = new List<(long Time, int Side, long Price)>();
        long ceiling = to - 1;
        while (to >= from)
        {
            if (stopped?.Invoke() == true) throw new OperationCanceledException();
            var response = await api.Request(2145, new { ctidTraderAccountId = account, symbolId = symbol, type = side, fromTimestamp = from - 1, toTimestamp = to }, 2146);
            if (stopped?.Invoke() == true) throw new OperationCanceledException();
            bool more = response.GetProperty("hasMore").GetBoolean();
            var page = new List<(long Time, int Side, long Price)>();
            long time = 0, price = 0, previous = long.MaxValue;
            foreach (var tick in Items(response, "tickData"))
            {
                time = checked(time + Integer(tick, "timestamp"));
                price = checked(price + Integer(tick, "tick"));
                if (time < from - 1 || time > to || time > previous || price <= 0) throw new IOException("Invalid decoded historical tick.");
                previous = time;
                if (time >= from && time <= ceiling) page.Add((time, side, price));
            }
            if (!more) { ticks.AddRange(page); break; }
            if (page.Count == 0 || page[0].Time == page[^1].Time)
                throw new IOException("Tick pagination cannot progress; refusing incomplete history.");
            long boundary = page[^1].Time;
            ticks.AddRange(page.Where(tick => tick.Time > boundary));
            ceiling = boundary;
            to = boundary + 1; // Upper bound is exclusive. Re-fetch every tie at the boundary millisecond.
            if (ticks.Count > 4000000) throw new IOException("Historical tick interval exceeds the safe in-memory limit.");
        }
        return ticks;
    }
    public static async Task<List<BacktestRunner.Quote>> Quotes(IExecutionConnection api, long account, long symbol,
        DateTime from, DateTime to, Func<bool> stopped, BacktestRunner.Quote? seed = null)
    {
        if (to <= from) return new();
        var a = new DateTimeOffset(DateTime.SpecifyKind(from, DateTimeKind.Utc)).ToUnixTimeMilliseconds();
        var b = new DateTimeOffset(DateTime.SpecifyKind(to, DateTimeKind.Utc)).ToUnixTimeMilliseconds();
        if (b <= a) return new();
        var ticks = await Fetch(api, account, symbol, a, b, 1, stopped);
        ticks.AddRange(await Fetch(api, account, symbol, a, b, 2, stopped));
        ticks.Sort((x, y) => x.Time != y.Time ? x.Time.CompareTo(y.Time) : x.Side.CompareTo(y.Side));
        return BacktestRunner.MergeQuotes(ticks, seed?.Bid ?? 0, seed?.Ask ?? 0).ToList();
    }
    public static async Task<long> Warmup(ExecutionBroker broker, ExecutionConfig config, DateTime cutoff,
        Action<BacktestRunner.Quote> observe, Action<string> progress, Func<bool> stopped)
    {
        long count = 0;
        for (int back = 1; back <= 4; back++)
        {
            var day = cutoff.Date.AddDays(-back);
            if (day.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday) continue;
            progress($"Loading Asia bid/ask history for {day:yyyy-MM-dd} UTC.");
            var quotes = await Quotes(broker.Api, broker.Account.Id, broker.SymbolId, day, day.AddHours(8).AddSeconds(5), stopped);
            var candidate = new AsiaSession();
            foreach (var q in quotes) candidate.Observe(q.Time, q.Bid, q.Ask, config.SpreadMultiplier, config.MinimumStop);
            if (candidate.GetProfile(EntrySession.NewYork, day.AddHours(8)) is null) continue;
            foreach (var q in quotes) { observe(q); count++; }
            break;
        }
        progress($"Loading today's Asia bid/ask history through {cutoff:HH:mm:ss} UTC.");
        var end = cutoff < cutoff.Date.AddHours(8).AddSeconds(5) ? cutoff : cutoff.Date.AddHours(8).AddSeconds(5);
        foreach (var q in await Quotes(broker.Api, broker.Account.Id, broker.SymbolId, cutoff.Date, end, stopped))
        { observe(q); count++; }
        if (stopped()) throw new OperationCanceledException();
        return count;
    }
}

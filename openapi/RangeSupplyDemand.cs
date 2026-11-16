using Xauusd;

// Threshold range bars: real quote closes, no interpolated prices or synthetic gap bars.
sealed class RangeBarBook(double size)
{
    internal sealed record Bar(DateTime Start, DateTime End, double Open, double High, double Low, double Close);
    DateTime first, previous;
    double open, high, low;
    bool active;
    public long ClosedBars { get; private set; }
    public long Overshoots { get; private set; }
    public long Resets { get; private set; }
    public long LargeOvershoots { get; private set; }
    public double MaxOvershoot { get; private set; }
    public Bar? Observe(DateTime time, double bid)
    {
        if (!double.IsFinite(size) || size <= 0 || !double.IsFinite(bid) || bid <= 0 || time < previous)
            throw new ArgumentException("Invalid range size, quote or timestamp order.");
        if (previous != default && (time.Date != previous.Date || time - previous > TimeSpan.FromSeconds(60)))
        { active = false; Resets++; }
        previous = time;
        if (!active) { first = time; open = high = low = bid; active = true; return null; }
        high = Math.Max(high, bid); low = Math.Min(low, bid);
        if (high - low < size - 1e-9) return null;
        var bar = new Bar(first, time, open, high, low, bid);
        ClosedBars++; if (high - low > size + 1e-9) Overshoots++;
        if (high - low > size * 1.5 + 1e-9) LargeOvershoots++;
        MaxOvershoot = Math.Max(MaxOvershoot, high - low - size);
        active = false;
        return bar;
    }
}

sealed class RangeSupplyDemand(double size, double minimumStop, bool highLowTarget = false)
{
    internal sealed record ZoneState(bool Long, double Low, double High, DateTime Created, long Index, double Target);
    internal sealed record PaEvent(long ZoneId, string Kind, DateTime Utc, long BarIndex, ZoneState Zone);
    public Action<PaEvent>? OnEvent { get; set; }
    public Action<RangeBarBook.Bar, long>? OnBar { get; set; }
    void Emit(string kind, DateTime time, ZoneState? zone = null)
    { if ((zone ?? Zone) is { } z) OnEvent?.Invoke(new(z.Index, kind, time, index, z)); }
    readonly RangeBarBook book = new(size);
    readonly List<RangeBarBook.Bar> bars = new();
    public ZoneState? Zone { get; private set; }
    public AsiaProfile? Signal { get; private set; }
    public ZoneState? SignalZone { get; private set; }
    public double TargetPrice { get; private set; }
    public DateTime ConfirmedUtc => confirmed;
    DateTime previous, until;
    double signalDistal, signalProximal;
    DateTime confirmed;
    public long SignalVersion { get; private set; }
    long index, touched = -1;
    public long ZonesCreated { get; private set; }
    public long Retests { get; private set; }
    public long Invalidated { get; private set; }
    public long Expired { get; private set; }
    public long Confirmations { get; private set; }
    public object Diagnostics() => new { book.ClosedBars, book.Overshoots, book.LargeOvershoots, book.MaxOvershoot, book.Resets, ZonesCreated, Retests, Invalidated, Expired, Confirmations };
    public void Observe(BacktestRunner.Quote q)
    {
        ObserveQuote(q.Time, q.Bid, q.Ask);
        if (book.Observe(q.Time, q.Bid) is { } bar) { ObserveBar(bar); OnBar?.Invoke(bar, index); }
    }
    public void ObserveQuote(DateTime time, double bid, double ask)
    {
        if (previous != default && (time.Date != previous.Date || time - previous > TimeSpan.FromSeconds(60)))
        { Emit("reset", time); bars.Clear(); Zone = null; Signal = null; touched = -1; }
        previous = time;
        if (Signal is not null && (time > until || (Signal.IsLong ? bid <= signalDistal : ask >= signalDistal) || (Signal.IsLong ? bid > signalProximal + size : bid < signalProximal - size) || (highLowTarget && (Signal.IsLong ? ask >= TargetPrice : bid <= TargetPrice)))) Signal = null;
        if (Zone is not { } zone) return;
        if (time - zone.Created > TimeSpan.FromHours(24)) { Emit("expired", time); Zone = null; Expired++; return; }
        if (zone.Long ? bid < zone.Low : bid > zone.High) { Emit("invalidated", time); Zone = null; Invalidated++; return; }
        if (time > zone.Created && touched < 0 && bid >= zone.Low && bid <= zone.High)
        { touched = index; Retests++; Emit("retest", time); }
    }
    public void ObserveBar(RangeBarBook.Bar bar)
    {
        index++;
        if (Zone is { } zone)
        {
            if (index - zone.Index >= 50 || (touched >= 0 && index - touched > 3))
            { Emit("expired", bar.End); Zone = null; Expired++; }
            else if (touched >= 0 && bar.Start > zone.Created && bar.Low <= zone.High && bar.High >= zone.Low &&
                Math.Abs(bar.Close - bar.Open) >= size * .35 &&
                (zone.Long ? bar.Close > bar.Open && bar.Close > zone.High && bar.Close - zone.High <= size :
                    bar.Close < bar.Open && bar.Close < zone.Low && zone.Low - bar.Close <= size))
            {
                TargetPrice = zone.Target; SignalZone = zone;
                Signal = new(DateOnly.FromDateTime(bar.End), zone.Long, minimumStop, size * .2);
                confirmed = bar.End; until = bar.End.AddSeconds(6); SignalVersion++; signalProximal = zone.Long ? zone.High : zone.Low; signalDistal = zone.Long ? zone.Low : zone.High;
                Emit("confirmed", bar.End); Zone = null; Confirmations++;
            }
        }
        bars.Add(bar); if (bars.Count > 3) bars.RemoveAt(0);
        if (bars.Count != 3 || bars.Any(b => b.High - b.Low > size * 1.5 + 1e-9)) return;
        var a = bars[0]; var b = bars[1]; var c = bars[2];
        if (Math.Abs(a.Close - a.Open) > size * .35) return;
        bool up = b.Close - b.Open >= size * .65 && c.Close - c.Open >= size * .65 && c.Close >= a.High + size;
        bool down = b.Open - b.Close >= size * .65 && c.Open - c.Close >= size * .65 && c.Close <= a.Low - size;
        if (!up && !down) return;
        Emit("replaced", c.End);
        Zone = new(up, a.Low, a.High, c.End, index, up ? Math.Max(b.High, c.High) : Math.Min(b.Low, c.Low)); touched = -1; ZonesCreated++; Emit("created", c.End);
    }
    public AsiaProfile? Profile(DateTime time) => Signal is not null && time >= confirmed && time <= until ? Signal : null;
    public double StopDistance(double bid, double ask, double slippage)
    {
        var signal = Signal ?? throw new InvalidOperationException("No confirmed range signal.");
        double buffer = Math.Max(ask - bid, size * .1);
        return Math.Max(minimumStop, signal.IsLong ? ask + slippage - (signalDistal - buffer) : signalDistal + buffer - (bid - slippage));
    }
}

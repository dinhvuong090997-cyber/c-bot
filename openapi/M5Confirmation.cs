// Research-only: emit the immediately preceding complete bid candle once.
sealed class M5Confirmation
{
    internal sealed record Bar(DateTime Time, double Open, double High, double Low, double Close);
    DateTime bucket, first, last, closed;
    double open, high, low, close, closedOpen, closedClose;
    public Bar? Observe(DateTime time, double bid)
    {
        Bar? completed = null;
        var next = time.AddTicks(-(time.Ticks % TimeSpan.FromMinutes(5).Ticks));
        if (next != bucket)
        {
            closed = next == bucket.AddMinutes(5) && first <= bucket.AddSeconds(5) && last >= bucket.AddMinutes(5).AddSeconds(-5) ? bucket : default;
            closedOpen = open; closedClose = close;
            if (closed != default) completed = new(closed, open, high, low, close);
            bucket = next; first = time; open = high = low = bid;
        }
        high = Math.Max(high, bid); low = Math.Min(low, bid);
        last = time; close = bid;
        return completed;
    }
    public bool HasClosedCandle(DateTime time) => closed != default && time >= closed.AddMinutes(5) && time < closed.AddMinutes(10);
    public bool Allows(DateTime time, bool isLong) => closed != default && time >= closed.AddMinutes(5) && time < closed.AddMinutes(10) &&
        (isLong ? closedClose > closedOpen : closedClose < closedOpen);
}

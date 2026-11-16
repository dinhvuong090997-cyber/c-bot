// Independent research definitions, not a copy of a third-party SMC indicator.
sealed class SmcResearch
{
    readonly List<M5Confirmation.Bar> bars = new();
    public double? SwingHigh { get; private set; }
    public double? SwingLow { get; private set; }
    public int Trend { get; private set; }
    public bool LastChangeOfCharacter { get; private set; }
    bool highBroken, lowBroken;
    int structure, sweep, fvg;
    DateTime eventTime;
    public void Reset()
    {
        bars.Clear(); SwingHigh = SwingLow = null; Trend = structure = sweep = fvg = 0;
        highBroken = lowBroken = LastChangeOfCharacter = false; eventTime = default;
    }
    public void Observe(M5Confirmation.Bar bar)
    {
        if (bars.Count > 0 && bar.Time != bars[^1].Time.AddMinutes(5)) Reset();
        structure = sweep = fvg = 0; LastChangeOfCharacter = false;
        eventTime = bar.Time.AddMinutes(5);
        bool up = SwingHigh is { } h && !highBroken && bar.Close > h;
        bool down = SwingLow is { } l && !lowBroken && bar.Close < l;
        if (up) highBroken = true;
        if (down) lowBroken = true;
        if (up != down)
        {
            structure = up ? 1 : -1;
            LastChangeOfCharacter = Trend != 0 && Trend != structure;
            Trend = structure;
        }
        bool sweepLow = SwingLow is { } sl && !lowBroken && bar.Low < sl && bar.Close > sl;
        bool sweepHigh = SwingHigh is { } sh && !highBroken && bar.High > sh && bar.Close < sh;
        if (sweepLow != sweepHigh) sweep = sweepLow ? 1 : -1;
        if (bars.Count >= 2)
        {
            var first = bars[^2];
            if (bar.Low > first.High) fvg = 1;
            else if (bar.High < first.Low) fvg = -1;
        }
        bars.Add(bar);
        if (bars.Count > 5) bars.RemoveAt(0);
        if (bars.Count == 5)
        {
            var pivot = bars[2];
            if (bars.Where((_, i) => i != 2).All(b => pivot.High > b.High)) { SwingHigh = pivot.High; highBroken = false; }
            if (bars.Where((_, i) => i != 2).All(b => pivot.Low < b.Low)) { SwingLow = pivot.Low; lowBroken = false; }
        }
    }
    public bool Allows(DateTime time, bool isLong, string filter)
    {
        if (eventTime == default || time < eventTime || time >= eventTime.AddMinutes(5)) return false;
        var direction = filter switch { "structure" => structure, "sweep" => sweep, "fvg" => fvg, _ => throw new ArgumentException("Unknown SMC research filter.") };
        return direction == (isLong ? 1 : -1);
    }
}

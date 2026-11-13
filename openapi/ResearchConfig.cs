using System.Text.Json;

sealed record ResearchConfig(
    string Start = "2026-01-01", string End = "2026-05-01", double Capital = 50000,
    double RR = 1.5, double RiskPercent = 0.25, double MaxDrawdownPercent = 5,
    double MinimumStop = 2, double SpreadMultiplier = 1.5, double Slippage = 0.1,
    bool Swap = true, bool Asia = true, bool NewYork = true)
{
    public void Validate()
    {
        if (!DateOnly.TryParseExact(Start, "yyyy-MM-dd", out var start) || !DateOnly.TryParseExact(End, "yyyy-MM-dd", out var end) || end <= start || end.DayNumber - start.DayNumber > 366)
            throw new ArgumentException("Choose a valid date range of up to 366 days. End date is exclusive.");
        var values = new[] { Capital, RR, RiskPercent, MaxDrawdownPercent, MinimumStop, SpreadMultiplier, Slippage };
        if (values.Any(v => !double.IsFinite(v)) || Capital is < 1000 or > 1000000 || RR is < 0.5 or > 5 ||
            RiskPercent is < 0.01 or > 1 || MaxDrawdownPercent is < 1 or > 20 || MinimumStop is < 0.1 or > 100 ||
            SpreadMultiplier is < 0.1 or > 3 || Slippage is < 0 or > 2 || !(Asia || NewYork))
            throw new ArgumentException("Check capital, risk, RR, stop and session settings.");
        for (var day = start; day < end; day = day.AddDays(1))
            if (!File.Exists(Path.Combine("data", "fxpro-v2", $"XAUUSD-{day:yyyy-MM-dd}.csv.gz")))
                throw new ArgumentException("Data is not ready for " + day.ToString("yyyy-MM-dd") + ". Choose completed dates.");
    }
}

using System;
using System.Linq;
using System.Text.Json;
using cAlgo.API;

namespace Xauusd;

[Robot(TimeZone = TimeZones.UTC, AccessRights = AccessRights.None)]
public sealed class FxProGoldMomentum : Robot
{
    [Parameter("Reward to risk", DefaultValue = 1.5, MinValue = 0.5, MaxValue = 5)]
    public double RewardToRisk { get; set; }

    [Parameter("Risk percent", DefaultValue = 0.25, MinValue = 0.01, MaxValue = 1)]
    public double RiskPercent { get; set; }

    [Parameter("Max closed drawdown percent", DefaultValue = 5.0, MinValue = 1, MaxValue = 20)]
    public double MaxDrawdownPercent { get; set; }

    [Parameter("Minimum stop USD per ounce", DefaultValue = 2.0, MinValue = 0.1)]
    public double MinimumStop { get; set; }

    [Parameter("Spread multiplier", DefaultValue = 1.5, MinValue = 0.1)]
    public double SpreadMultiplier { get; set; }

    [Parameter("Sizing cost buffer USD per ounce", DefaultValue = 0.17, MinValue = 0)]
    public double CostBuffer { get; set; }

    [Parameter("Trade Asia", DefaultValue = true)]
    public bool TradeAsia { get; set; }

    [Parameter("Trade New York", DefaultValue = true)]
    public bool TradeNewYork { get; set; }

    private const string Label = "FxProGoldMomentum";
    private readonly AsiaSession _asia = new();
    private double _peak;
    private bool _halted;
    private DateTime? _lastTick;
    private DateTime _lastAttempt = DateTime.MinValue;
    private PendingEntry? _pending;

    private bool Realtime => RunningMode == RunningMode.RealTime;
    private string PeakKey => $"Gold peak {Account.Number} {SymbolName}";
    private string HaltKey => $"Gold halt {Account.Number} {SymbolName}";

    protected override void OnStart()
    {
        if (Realtime && Account.IsLive)
        {
            Print("This build is for backtesting and demo accounts.");
            Stop();
            return;
        }

        if (Account.Asset.Name != "USD" || Symbol.QuoteAsset.Name != "USD" ||
            !new[] { "GOLD", "XAUUSD", "GOLDoz" }.Contains(SymbolName, StringComparer.OrdinalIgnoreCase))
        {
            Print("Select the broker's gold-per-ounce USD symbol and a USD account.");
            Stop();
            return;
        }

        _peak = Account.Balance;
        if (Realtime)
        {
            _peak = Math.Max(_peak, LocalStorage.GetObject<double>(PeakKey, LocalStorageScope.Type));
            _halted = LocalStorage.GetObject<bool>(HaltKey, LocalStorageScope.Type);
            Timer.Start(TimeSpan.FromSeconds(5));
        }
        Print("Started {0} with RR {1}. Waiting for complete Asia quote coverage.", SymbolName, RewardToRisk);
    }

    protected override void OnTimer()
    {
        var now = DateTime.SpecifyKind(Server.TimeInUtc, DateTimeKind.Utc);
        Print("BOT_STATUS {0}", JsonSerializer.Serialize(new
        {
            symbol = SymbolName,
            utc = now,
            lastQuoteUtc = _lastTick,
            session = AsiaSession.GetEntrySession(now, TradeAsia, TradeNewYork).ToString(),
            halted = _halted,
            balance = Account.Balance,
            equity = Account.Equity,
            positionCount = Positions.Count(position => position.SymbolName == SymbolName),
            closedDrawdownPercent = _peak > 0 ? 100 * (1 - Account.Balance / _peak) : 0,
            rewardToRisk = RewardToRisk
        }));
    }

    protected override void OnTick()
    {
        var now = DateTime.SpecifyKind(Server.TimeInUtc, DateTimeKind.Utc);
        var bid = Symbol.Bid;
        var ask = Symbol.Ask;
        if (!double.IsFinite(bid) || bid <= 0 || ask < bid || !double.IsFinite(ask))
            return;

        _lastTick = now;
        _asia.Observe(now, bid, ask, SpreadMultiplier, MinimumStop);
        UpdateDrawdown();
        var session = AsiaSession.GetEntrySession(now, TradeAsia, TradeNewYork);
        var profile = _asia.GetProfile(session, now);
        if (_halted || profile is null || HasExposure())
        {
            _pending = null;
            return;
        }

        if (_pending is { } pending)
        {
            if (now >= pending.Due)
            {
                _pending = null;
                if (now - pending.Due <= TimeSpan.FromSeconds(5) && pending.Session == session &&
                    pending.Profile == profile && ask - bid <= profile.SpreadLimit + 1e-9)
                    Open(profile, bid, ask);
            }
            return;
        }

        var minute = now.AddTicks(-(now.Ticks % TimeSpan.TicksPerMinute));
        if (minute == _lastAttempt || ask - bid > profile.SpreadLimit + 1e-9)
            return;

        _lastAttempt = minute;
        _pending = new(now.AddSeconds(1), session, profile);
    }

    private bool HasExposure() => Positions.Any(position => position.SymbolName == SymbolName) ||
                                  PendingOrders.Any(order => order.SymbolName == SymbolName);

    private void Open(AsiaProfile profile, double bid, double ask)
    {
        var side = profile.IsLong ? TradeType.Buy : TradeType.Sell;
        var price = profile.IsLong ? ask : bid;
        var stop = Math.Ceiling(profile.StopDistance / Symbol.TickSize) * Symbol.TickSize;
        var riskVolume = Account.Balance * RiskPercent / 100 / (stop + CostBuffer);
        var notionalVolume = Account.Balance / (price * 1.01);
        var volume = Symbol.NormalizeVolumeInUnits(
            Math.Min(Symbol.VolumeInUnitsMax, Math.Min(riskVolume, notionalVolume)), RoundingMode.Down);

        if (volume < Symbol.VolumeInUnitsMin || Symbol.GetEstimatedMargin(side, volume) > Account.FreeMargin)
            return;

        var result = ExecuteMarketOrder(side, SymbolName, volume, Label,
            stop / Symbol.PipSize, RewardToRisk * stop / Symbol.PipSize);
        if (!result.IsSuccessful)
        {
            Print("Order rejected: {0}", result.Error);
            return;
        }

        if (result.Position is { } position && (position.StopLoss is null || position.TakeProfit is null))
        {
            Halt();
            var close = ClosePosition(position);
            Print("Missing protection on position {0}. Close result: {1}.", position.Id, close);
        }
    }

    private void UpdateDrawdown()
    {
        if (Account.Balance > _peak)
        {
            _peak = Account.Balance;
            PersistRisk();
        }

        if (!_halted && Account.Balance <= _peak * (1 - MaxDrawdownPercent / 100))
            Halt();
    }

    private void Halt()
    {
        _halted = true;
        PersistRisk();
        Print("Entry halt. Check the account and open positions.");
    }

    private void PersistRisk()
    {
        if (!Realtime)
            return;
        LocalStorage.SetObject(PeakKey, _peak, LocalStorageScope.Type);
        LocalStorage.SetObject(HaltKey, _halted, LocalStorageScope.Type);
        LocalStorage.Flush(LocalStorageScope.Type);
    }

    private sealed record PendingEntry(DateTime Due, EntrySession Session, AsiaProfile Profile);
}

using System;
using System.Collections.Generic;

namespace Xauusd;

internal enum EntrySession { Closed, Asia, NewYork }

internal sealed record AsiaProfile(DateOnly Date, bool IsLong, double StopDistance, double SpreadLimit);

internal sealed class AsiaSession
{
    private static readonly TimeOnly AsiaClose = new(8, 0);
    private static readonly TimeOnly SpreadSampleStart = new(7, 55);
    private static readonly TimeZoneInfo NewYork = TimeZoneInfo.FindSystemTimeZoneById("America/New_York");

    private readonly List<double> _spreads = new();
    private DateOnly? _date;
    private DateTime _firstTime, _lastTime;
    private double _first, _last, _low, _high;
    private int _ticks;
    private AsiaProfile? _today, _previous;

    public void Observe(DateTime time, double bid, double ask, double spreadMultiplier, double minimumStop)
    {
        if (!double.IsFinite(bid) || bid <= 0 || ask < bid || !double.IsFinite(ask))
            return;

        var date = DateOnly.FromDateTime(time);
        var midpoint = (bid + ask) / 2;
        if (date != _date)
        {
            if (_today is not null)
                _previous = _today;

            _today = null;
            _date = date;
            _firstTime = time;
            _first = _low = _high = midpoint;
            _ticks = 0;
            _spreads.Clear();
        }

        var utc = TimeOnly.FromDateTime(time);
        if (utc < AsiaClose)
        {
            _last = midpoint;
            _lastTime = time;
            _low = Math.Min(_low, midpoint);
            _high = Math.Max(_high, midpoint);
            _ticks++;
            if (utc >= SpreadSampleStart)
                _spreads.Add(ask - bid);
            return;
        }

        if (_today is not null || _ticks < 100 || _spreads.Count < 30 ||
            _firstTime.TimeOfDay > TimeSpan.FromMinutes(1) ||
            _lastTime.TimeOfDay < TimeSpan.FromHours(8) - TimeSpan.FromSeconds(5) ||
            _last == _first)
            return;

        _spreads.Sort();
        var median = (_spreads[(_spreads.Count - 1) / 2] + _spreads[_spreads.Count / 2]) / 2;
        _today = new(date, _last > _first, Math.Max(minimumStop, (_high - _low) / 2),
            median * spreadMultiplier);
    }

    public static EntrySession GetEntrySession(DateTime utc, bool asia, bool newYork)
    {
        if (utc.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday)
            return EntrySession.Closed;
        if (asia && TimeOnly.FromDateTime(utc) < AsiaClose)
            return EntrySession.Asia;

        var local = TimeZoneInfo.ConvertTimeFromUtc(DateTime.SpecifyKind(utc, DateTimeKind.Utc), NewYork);
        return newYork && local.Hour is >= 8 and < 17 ? EntrySession.NewYork : EntrySession.Closed;
    }

    public AsiaProfile? GetProfile(EntrySession session, DateTime utc)
    {
        var date = DateOnly.FromDateTime(utc);
        if (session == EntrySession.Asia && _previous is { } previous &&
            date.DayNumber - previous.Date.DayNumber is >= 1 and <= 4)
            return previous;
        return session == EntrySession.NewYork && _today?.Date == date ? _today : null;
    }
}

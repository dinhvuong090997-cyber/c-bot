using System.Text.Json;
using static ExecutionFiles;

sealed record PriceHistory(int PeriodMinutes, DateTime FromUtc, DateTime ToUtc, Candle[] Bars, bool MissingDays);
static class ChartHistory
{
    static readonly SemaphoreSlim gate=new(1,1);
    static readonly Dictionary<string,PriceHistory> cache=new();
    public static async Task<PriceHistory> Load(string key,JsonElement run,JsonElement[] trades,int tradeIndex,int requestedMinutes)
    {
        if(requestedMinutes is not (1 or 5 or 15 or 60))throw new ArgumentException("Unsupported chart timeframe.");
        var start=run.GetProperty("startUtc").GetDateTime().ToUniversalTime();var end=run.GetProperty("endUtcExclusive").GetDateTime().ToUniversalTime();
        if(tradeIndex>=0)
        {
            if(tradeIndex>=trades.Length)throw new ArgumentException("Unknown trade.");
            var t=trades[tradeIndex];var entry=t.GetProperty("entryUtc").GetDateTime().ToUniversalTime();var exit=t.GetProperty("exitUtc").GetDateTime().ToUniversalTime();
            start=entry.AddHours(-1)>start?entry.AddHours(-1):start;end=exit.AddHours(1)<end?exit.AddHours(1):end;
        }
        int actual=new[]{1,5,15,60}.First(p=>p>=requestedMinutes&&(end-start).TotalMinutes/p<=10000);
        string identity=$"{key}:{tradeIndex}:{actual}";
        await gate.WaitAsync();
        try
        {
            if(cache.TryGetValue(identity,out var found))return found;
            var output=await Task.Run(()=>Build(start,end,actual));
            if(cache.Count>=6)cache.Remove(cache.First().Key);
            cache[identity]=output;return output;
        }
        finally{gate.Release();}
    }
    internal static PriceHistory Build(DateTime start,DateTime end,int period)
    {
        var bars=new SortedDictionary<long,Candle>();bool missing=false;
        for(var day=start.Date;day<end;day=day.AddDays(1))
        {
            var file=Path.Combine("data","fxpro-v2",$"XAUUSD-{day:yyyy-MM-dd}.csv.gz");
            if(!File.Exists(file)){missing=true;continue;}
            foreach(var q in BacktestRunner.ReadQuotes(file))
            {
                if(q.Time<start||q.Time>=end||q.Bid<=0||q.Ask<q.Bid)continue;
                long time=q.Milliseconds/(period*60000L)*(period*60L);
                bars[time]=bars.TryGetValue(time,out var b)?b with {High=Math.Max(b.High,q.Bid),Low=Math.Min(b.Low,q.Bid),Close=q.Bid,Volume=b.Volume+1}:new(time,q.Bid,q.Bid,q.Bid,q.Bid,1);
            }
        }
        return new(period,start,end,bars.Values.ToArray(),missing);
    }
}

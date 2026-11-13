using System.Text.Json;
using static ExecutionFiles;

sealed record Candle(long Time, double Open, double High, double Low, double Close, long Volume);
sealed record MonitorPosition(long Id, string Side, double VolumeOz, double Entry, double? StopLoss, double? TakeProfit, DateTime OpenedUtc, double? NetPnl);
sealed record MarketAccount(string Login, double Balance, double Equity, double Unrealized, int Positions, DateTime CapturedUtc);
sealed record MarketEvent(string Id, DateTime Time, string Event, string Detail);
sealed record MarketView(ExecutionAccount? Account, string State, string Message, string HistoryVersion,
    double? Bid, double? Ask, DateTime? QuoteUtc, MarketAccount? Summary, MonitorPosition[] Positions, Candle[] Bars, MarketEvent[] Events);

// This connection deliberately cannot submit, amend, cancel or close an order.
sealed class MonitorConnection(IExecutionConnection inner) : IExecutionConnection
{
    internal static bool Allowed(int type) => type is 2112 or 2114 or 2116 or 2121 or 2124 or 2127 or 2133 or 2137 or 2149 or 2187;
    public Action<int,JsonElement>? Received { get => inner.Received; set => inner.Received = value; }
    public Task Connect(AppCredentials app,TokenSet tokens,long accountId=48463366L,bool live=false)=>inner.Connect(app,tokens,accountId,live);
    public Task<JsonElement> Request(int type,object payload,int expected) => Allowed(type) ? inner.Request(type,payload,expected) : throw new InvalidOperationException("Trading requests are forbidden on the market monitor.");
    public void Dispose()=>inner.Dispose();
}

sealed class CandleBook
{
    readonly SortedDictionary<long,Candle> bars=new();
    public void Load(IEnumerable<Candle> values) { bars.Clear(); foreach(var c in values) bars[c.Time]=c; }
    public static Candle Decode(JsonElement b)
    {
        double low=Number(b,"low")/1e5;
        var c=new Candle(Integer(b,"utcTimestampInMinutes")*60,low+Number(b,"deltaOpen")/1e5,low+Number(b,"deltaHigh")/1e5,low,low+Number(b,"deltaClose")/1e5,Integer(b,"volume"));
        if(c.Time<=0||c.Low<=0||c.High<c.Low||c.Open<c.Low||c.Open>c.High+1e-8||c.Close<c.Low||c.Close>c.High+1e-8)throw new IOException("Invalid broker candle.");
        return c;
    }
    public void Tick(long milliseconds,double bid)
    {
        long time=milliseconds/60000*60;
        if(bid<=0||!double.IsFinite(bid)||(bars.Count>0&&time<bars.Last().Key))return;
        bars[time]=bars.TryGetValue(time,out var c)?c with {High=Math.Max(c.High,bid),Low=Math.Min(c.Low,bid),Close=bid,Volume=c.Volume+1}:new(time,bid,bid,bid,bid,1);
        while(bars.Count>5000)bars.Remove(bars.First().Key);
    }
    public Candle[] All()=>bars.Values.ToArray();
    public Candle[] Tail()=>bars.Values.TakeLast(2).ToArray();
}

sealed class MarketMonitor(string directory,Func<IExecutionConnection>? factory=null) : IDisposable
{
    readonly object gate=new();
    readonly CandleBook book=new();
    ExecutionAccount? selected;
    Task? runner;
    volatile bool disposed;
    public void Dispose()=>disposed=true;
    MarketView view=new(null,"unconfigured","Apply an account in Settings to connect market data.","",null,null,null,null,[],[],[]);
    public MarketView Snapshot(ExecutionAccount? account,bool history=false)
    {
        lock(gate)
        {
            if(selected!=account)
            {
                selected=account;book.Load([]);
                view=new(account,account is null?"unconfigured":"connecting",account is null?"Apply an account in Settings to connect market data.":"Connecting to FxPro market data…","",null,null,null,null,[],[],[]);
            }
            if(!disposed&&account is not null&&(runner is null||runner.IsCompleted))runner=Task.Run(Loop);
            return view with {Bars=history?book.All():book.Tail()};
        }
    }
    bool Current(ExecutionAccount target) {lock(gate)return selected==target;}
    async Task Loop()
    {
        while(!disposed)
        {
            ExecutionAccount? target;lock(gate)target=selected;
            if(target is null){await Task.Delay(500);continue;}
            string stage="authentication";
            try
            {
                using var broker=await ExecutionBroker.Open(directory,target.Id,()=>new MonitorConnection(factory?.Invoke()??new OpenApiConnection()));
                if(broker.Account!=target)throw new ArgumentException("Account changed. Apply the account again.");
                var api=broker.Api;double bid=0,ask=0;DateTime bidAt=DateTime.MinValue,askAt=DateTime.MinValue;
                long cutoff=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
                stage="candles";
                var history=new SortedDictionary<long,Candle>();long end=cutoff,from=cutoff-3*86400000L;
                for(int page=0;page<12;page++)
                {
                    var response=await api.Request(2137,new {ctidTraderAccountId=target.Id,symbolId=broker.SymbolId,period=1,fromTimestamp=from,toTimestamp=end,count=5000},2138);
                    var batch=Items(response,"trendbar").Select(CandleBook.Decode).OrderBy(c=>c.Time).ToArray();
                    foreach(var c in batch.Where(c=>c.Time*1000>=from&&c.Time*1000<=cutoff))history[c.Time]=c;
                    if(!Flag(response,"hasMore")||batch.Length==0||batch[0].Time*1000<=from)break;
                    if(page==11||batch.Length==0||batch[0].Time*1000>=end)throw new IOException("Candle pagination did not complete.");
                    end=batch[0].Time*1000-1;
                }
                lock(gate)
                {
                    if(selected!=target)continue;
                    book.Load(history.Values);
                    view=view with {State="waiting",Message="Waiting for fresh broker quotes.",HistoryVersion=Guid.NewGuid().ToString("N")};
                }
                api.Received=(type,payload)=>
                {
                    if(Integer(payload,"ctidTraderAccountId")!=target.Id)return;
                    lock(gate)
                    {
                        if(selected!=target)return;
                        if(type==2131&&Integer(payload,"symbolId")==broker.SymbolId&&payload.TryGetProperty("timestamp",out _))
                        {
                            long stamp=Integer(payload,"timestamp");var time=DateTimeOffset.FromUnixTimeMilliseconds(stamp).UtcDateTime;
                            if(stamp<cutoff||time>DateTime.UtcNow.AddSeconds(1))return;
                            if(payload.TryGetProperty("bid",out _)&&time>=bidAt){bid=Number(payload,"bid")/1e5;bidAt=time;book.Tick(stamp,bid);}
                            if(payload.TryGetProperty("ask",out _)&&time>=askAt){ask=Number(payload,"ask")/1e5;askAt=time;}
                            if(bid>0&&ask>=bid&&bidAt!=DateTime.MinValue&&askAt!=DateTime.MinValue)
                                view=view with {Bid=bid,Ask=ask,QuoteUtc=bidAt<askAt?bidAt:askAt,State="connected",Message="Broker bid/ask stream. Account P&L sampled every 2 seconds."};
                        }
                        if(type==2126&&payload.TryGetProperty("deal",out var deal)&&Integer(deal,"symbolId")==broker.SymbolId&&Number(deal,"dealStatus") is 2 or 3&&Number(deal,"filledVolume")>0)
                        {
                            var ev=DealEvent(deal);view=view with {Events=view.Events.Where(x=>x.Id!=ev.Id).Append(ev).OrderByDescending(x=>x.Time).Take(100).ToArray()};
                        }
                    }
                };
                stage="subscription";
                await api.Request(2127,new {ctidTraderAccountId=target.Id,symbolId=new[]{broker.SymbolId},subscribeToSpotTimestamp=true},2128);
                stage="deals";
                var deals=await api.Request(2133,new {ctidTraderAccountId=target.Id,fromTimestamp=cutoff-86400000L,toTimestamp=DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),maxRows=100},2134);
                lock(gate)if(selected==target)view=view with {Events=view.Events.Concat(Items(deals,"deal").Where(d=>Integer(d,"symbolId")==broker.SymbolId&&Number(d,"dealStatus") is 2 or 3&&Number(d,"filledVolume")>0).Select(DealEvent)).DistinctBy(e=>e.Id).OrderByDescending(e=>e.Time).Take(100).ToArray()};
                stage="account";
                var nextAccount=DateTime.MinValue;
                while(!disposed&&Current(target))
                {
                    var reconcile=await broker.Reconcile();
                    if(DateTime.UtcNow>=nextAccount)
                    {
                        await broker.RefreshTrader();
                        var pnl=await api.Request(2187,new {ctidTraderAccountId=target.Id},2188);
                        double factor=Math.Pow(10,Number(pnl,"moneyDigits",2));
                        var values=Items(pnl,"positionUnrealizedPnL").ToDictionary(p=>Integer(p,"positionId"),p=>Number(p,"netUnrealizedPnL")/factor);
                        var positions=Items(reconcile,"position").Where(p=>Integer(p.GetProperty("tradeData"),"symbolId")==broker.SymbolId).Select(p=>
                        {
                            var td=p.GetProperty("tradeData");long id=Integer(p,"positionId");
                            return new MonitorPosition(id,Number(td,"tradeSide")==1?"BUY":"SELL",Number(td,"volume")/100,Number(p,"price"),Number(p,"stopLoss")>0?Number(p,"stopLoss"):null,Number(p,"takeProfit")>0?Number(p,"takeProfit"):null,DateTimeOffset.FromUnixTimeMilliseconds(Integer(td,"openTimestamp")).UtcDateTime,values.TryGetValue(id,out var value)?value:null);
                        }).ToArray();
                        double unrealized=values.Values.Sum();var summary=new MarketAccount(target.Login,broker.Balance,broker.Balance+unrealized,unrealized,Items(reconcile,"position").Count(),DateTime.UtcNow);
                        lock(gate)if(selected==target)view=view with {Summary=summary,Positions=positions};
                        nextAccount=DateTime.UtcNow.AddSeconds(2);
                    }
                    await Task.Delay(350);
                }
            }
            catch(Exception ex)
            {
                lock(gate)if(selected==target)view=view with {State="reconnecting",Message=ex is ArgumentException?ex.Message:"Market connection interrupted. Reconnecting read-only feed…"};
                Console.Error.WriteLine(JsonSerializer.Serialize(new {eventType="market_feed_error",utc=DateTimeOffset.UtcNow,account=target.Id,error=ex.GetType().Name,stage,location=ex.StackTrace?.Split('\n').FirstOrDefault()}));
                await Task.Delay(3000);
            }
        }
    }
    static MarketEvent DealEvent(JsonElement d)
    {
        string status=Number(d,"dealStatus") is 2 or 3?"Fill":"Deal update";
        return new(Integer(d,"dealId").ToString(),DateTimeOffset.FromUnixTimeMilliseconds(Integer(d,"executionTimestamp")).UtcDateTime,status,$"{(Number(d,"tradeSide")==1?"BUY":"SELL")} {Number(d,"filledVolume")/100:0.##} oz @ {Number(d,"executionPrice"):0.00}");
    }
}

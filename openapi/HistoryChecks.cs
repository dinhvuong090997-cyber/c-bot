using System.Text.Json;
using static ExecutionFiles;

static class HistoryChecks
{
    static void Check(bool condition, string message) { if (!condition) throw new Exception("History check failed: " + message); }
    static long Ms(DateTime time) => new DateTimeOffset(time).ToUnixTimeMilliseconds();
    public static async Task Run()
    {
        var api = new HistoryConnection { PageSize = 3 };
        api.Ticks.AddRange(new[] { (1000L,1,300000000L), (1500L,1,300001000L), (1500L,1,299999000L), (1800L,1,300002000L), (2500L,1,300003000L), (3000L,1,300004000L) });
        var fetched = await TickHistory.Fetch(api,123,41,1000,3000,1);
        Check(fetched.OrderBy(t=>t.Time).ThenBy(t=>t.Price).SequenceEqual(api.Ticks.Where(t=>t.Time<3000).OrderBy(t=>t.Time).ThenBy(t=>t.Price)),"pagination preserves duplicate-ms boundaries, first tick and exclusive end");
        api.BadOrder=true;bool rejected=false;try{await TickHistory.Fetch(api,123,41,1000,3000,1);}catch(IOException){rejected=true;}
        Check(rejected,"out-of-order delta responses rejected");api.BadOrder=false;
        var count=api.Requests;bool cancelled=false;try{await TickHistory.Fetch(api,123,41,1000,3000,1,()=>true);}catch(OperationCanceledException){cancelled=true;}
        Check(cancelled&&api.Requests==count,"Stop cancels before another historical request");
        var ties=new[]{(1000L,1,300000000L),(1000L,1,299999000L),(1000L,2,300020000L),(1000L,2,300021000L)};
        var merged=BacktestRunner.MergeQuotes(ties).Single();
        Check(merged.Bid==2999.99&&merged.Ask==3000.21,"same conservative tie merge as replay");
        var bridge=BacktestRunner.MergeQuotes(new[]{(2000L,1,300001000L)},3000,3000.2).Single();
        Check(bridge.Ask==3000.2&&bridge.Bid==3000.01,"bridge carries prior opposite-side price");
        var history=new HistoryConnection();DateTime day=new(2026,1,5,0,0,0,DateTimeKind.Utc);
        void Add(DateTime time,long price){history.Ticks.Add((Ms(time),1,price));history.Ticks.Add((Ms(time),2,price+20000));}
        for(int i=0;i<480;i++)Add(day.AddMinutes(i),300000000+i*1000);
        for(int i=0;i<31;i++)Add(day.AddHours(7).AddMinutes(59).AddSeconds(i),300500000);
        Add(day.AddHours(7).AddMinutes(59).AddSeconds(59),300500000);Add(day.AddHours(8),300500000);
        Add(day.AddDays(1),300600000);Add(day.AddDays(1).AddHours(3),300700000);
        var account=new ExecutionAccount(123,"456","FxPro",false);
        var config=new ExecutionConfig("test","report","run",account,5,1,20,3,1.5,true,true);
        var broker=new ExecutionBroker{Api=history,Account=account,Symbol=JsonSerializer.SerializeToElement(new{symbolId=41}),Trader=JsonSerializer.SerializeToElement(new{})};
        var signal=new ExecutionSignal(config);
        var cutoff=day.AddDays(1).AddHours(4);
        long loaded=await TickHistory.Warmup(broker,config,cutoff,q=>signal.Observe(q.Time,q.Bid,q.Ask),_=>{},()=>false);
        Check(loaded>500&&signal.Profile(cutoff)?.Date==DateOnly.FromDateTime(day),"mid-session startup recovers previous Asia profile");
        Check(signal.Profile(cutoff)!.IsLong,"delta price reconstruction retains momentum direction");
        var todaySignal=new ExecutionSignal(config);
        await TickHistory.Warmup(broker,config,day.AddHours(14),q=>todaySignal.Observe(q.Time,q.Bid,q.Ask),_=>{},()=>false);
        Check(todaySignal.Profile(day.AddHours(14))?.Date==DateOnly.FromDateTime(day),"NY startup recovers completed same-day Asia");
        var empty=new HistoryConnection();broker.Api=empty;var emptySignal=new ExecutionSignal(config);
        await TickHistory.Warmup(broker,config,cutoff,q=>emptySignal.Observe(q.Time,q.Bid,q.Ask),_=>{},()=>false);
        Check(emptySignal.Profile(cutoff) is null,"empty history never invents a profile");
        var blocked=new HistoryConnection {PageSize=1};blocked.Ticks.AddRange(new[]{(1000L,1,300000000L),(1000L,1,300000001L)});
        rejected=false;try{await TickHistory.Fetch(blocked,123,41,1000,2000,1);}catch(IOException){rejected=true;}
        Check(rejected,"non-progressing pagination fails closed");
        Console.WriteLine("History checks PASS: delta decoding, tied pagination, cancellation, shared quote merge, bridge seed, mid-Asia/NY startup and empty history. Historical API only; no order requests.");
    }
    sealed class HistoryConnection:IExecutionConnection
    {
        public Action<int,JsonElement>? Received{get;set;}
        public List<(long Time,int Side,long Price)> Ticks=new();
        public int Requests,PageSize=10000;public bool BadOrder;
        public Task Connect(AppCredentials app,TokenSet tokens,long accountId=48463366L,bool live=false)=>Task.CompletedTask;
        public Task<JsonElement> Request(int type,object payload,int expected)
        {
            if(type!=2145||expected!=2146)throw new Exception("Historical loader attempted a non-historical request.");
            var p=JsonSerializer.SerializeToElement(payload);Check(Integer(p,"ctidTraderAccountId")==123&&Integer(p,"symbolId")==41,"selected account and symbol");
            Requests++;
            if(BadOrder)return Task.FromResult(JsonSerializer.SerializeToElement(new{hasMore=false,tickData=new[]{new{timestamp=2000L,tick=300000000L},new{timestamp=1L,tick=1L}}}));
            var candidates=Ticks.Where(t=>t.Side==Integer(p,"type")&&t.Time>Integer(p,"fromTimestamp")&&t.Time<Integer(p,"toTimestamp")).OrderByDescending(t=>t.Time).ToArray();
            var page=candidates.Take(PageSize);var encoded=new List<object>();long time=0,price=0;
            foreach(var tick in page){encoded.Add(new{timestamp=tick.Time-time,tick=tick.Price-price});time=tick.Time;price=tick.Price;}
            return Task.FromResult(JsonSerializer.SerializeToElement(new{hasMore=candidates.Length>PageSize,tickData=encoded}));
        }
        public void Dispose(){}
    }
}

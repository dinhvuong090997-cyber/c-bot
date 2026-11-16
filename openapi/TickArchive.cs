using System.Globalization;
using System.Runtime.InteropServices;
using System.Text.Json;
using static ExecutionFiles;

// Background archive: fill current-year gaps first, then inspect every older UTC week.
static class TickArchive
{
    sealed record State(long AccountId,bool Live,DateTime EndUtc,DateTime RecentNextUtc,DateTime OlderEndUtc,DateTime FloorUtc,
        long DownloadedDays=0,long CachedDays=0,long Rows=0,long EmptyWeeks=0,bool Completed=false);
    public static async Task<bool> HasTicks(IExecutionConnection api,long account,long symbol,DateTime from,DateTime to)
    {
        if(to<=from||to-from>TimeSpan.FromDays(6))throw new ArgumentException("Invalid archive probe.");
        foreach(int side in new[]{1,2})
        {
            var p=await api.Request(2145,new{ctidTraderAccountId=account,symbolId=symbol,type=side,
                fromTimestamp=Math.Max(0,new DateTimeOffset(from).ToUnixTimeMilliseconds()-1),toTimestamp=new DateTimeOffset(to).ToUnixTimeMilliseconds()},2146);
            int count=Items(p,"tickData").Count();
            if(count>0)return true;
            if(Flag(p,"hasMore"))throw new IOException("Empty truncated probe cannot certify an empty week.");
        }
        return false;
    }
    public static async Task<long> Day(IExecutionConnection api,long account,long symbol,DateTime day,string path,Func<bool>? stopped=null)
    {
        if(File.Exists(path))return -1;
        long a=Math.Max(1,new DateTimeOffset(day).ToUnixTimeMilliseconds()),b=new DateTimeOffset(day.AddDays(1)).ToUnixTimeMilliseconds();
        var ticks=await TickHistory.Fetch(api,account,symbol,a,b,1,stopped);ticks.AddRange(await TickHistory.Fetch(api,account,symbol,a,b,2,stopped));
        if(stopped?.Invoke()==true)throw new OperationCanceledException();
        ticks.Sort((x,y)=>x.Time!=y.Time?x.Time.CompareTo(y.Time):x.Side.CompareTo(y.Side));
        RecorderStore.WriteTicks(path,ticks,replace:false);return ticks.Count;
    }
    public static async Task Run(string directory)
    {
        var config=JsonSerializer.Deserialize<ExecutionConfig>(File.ReadAllText(Path.Combine(directory,"execution-config.json")),Json)??throw new ArgumentException("Saved demo account required.");
        config.Validate();if(config.Account.Live)throw new ArgumentException("Archive source is demo XAUUSD.");
        string root=Path.Combine("data","archive-xauusd"),cache=Path.Combine("data","fxpro-v2");Directory.CreateDirectory(root);Directory.CreateDirectory(cache);
        using var lease=new FileStream(Path.Combine(root,"archive.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);
        string checkpoint=Path.Combine(root,"checkpoint.json"),statusFile=Path.Combine(root,"status.json");
        var end=DateTime.UtcNow.Date;var year=new DateTime(end.Year,1,1,0,0,0,DateTimeKind.Utc);
        var state=File.Exists(checkpoint)?JsonSerializer.Deserialize<State>(File.ReadAllText(checkpoint),Json)!:new(config.Account.Id,false,end,year,year,DateTime.UnixEpoch);
        if(state is null||state.AccountId!=config.Account.Id||state.Live||state.FloorUtc!=DateTime.UnixEpoch||state.RecentNextUtc<new DateTime(state.EndUtc.Year,1,1,0,0,0,DateTimeKind.Utc)||state.RecentNextUtc>state.EndUtc||state.EndUtc>DateTime.UtcNow.Date||state.OlderEndUtc<state.FloorUtc)
            throw new IOException("Invalid archive checkpoint or changed source identity.");
        // Persist origin before issuing requests. End is a fixed snapshot; recorder handles future dates.
        RecorderStore.AtomicJson(checkpoint,state);
        using var stop=new CancellationTokenSource();using var term=PosixSignalRegistration.Create(PosixSignal.SIGTERM,c=>{c.Cancel=true;stop.Cancel();});
        Console.CancelKeyPress+=(s,e)=>{e.Cancel=true;stop.Cancel();};
        string stage="starting";DateTime? current=null;string? error=null;int failures=0;
        void Status()=>RecorderStore.AtomicJson(statusFile,new{stage,heartbeatUtc=DateTime.UtcNow,source="FxPro demo XAUUSD",readOnly=true,state.EndUtc,state.RecentNextUtc,state.OlderEndUtc,state.FloorUtc,state.DownloadedDays,state.CachedDays,state.Rows,state.EmptyWeeks,state.Completed,currentUtc=current,error,failures,message="Empty weeks mean both API sides returned empty; no fixed retention boundary is assumed."});
        void Save(){RecorderStore.AtomicJson(checkpoint,state);Status();}
        void Disk(){if(new DriveInfo(Path.GetPathRoot(Path.GetFullPath(root))!).AvailableFreeSpace<10L*1024*1024*1024)throw new IOException("Archive requires10GB free reserve.");}
        async Task Download(ExecutionBroker broker,DateTime day)
        {
            current=day;stage="downloading-day";Status();Disk();
            string path=Path.Combine(cache,$"XAUUSD-{day:yyyy-MM-dd}.csv.gz");long rows=await Day(broker.Api,broker.Account.Id,broker.SymbolId,day,path,()=>stop.IsCancellationRequested);
            state=rows<0?state with{CachedDays=state.CachedDays+1}:state with{DownloadedDays=state.DownloadedDays+1,Rows=state.Rows+rows};
            Console.WriteLine(JsonSerializer.Serialize(new{eventType="archive_day",utc=DateTime.UtcNow,day=day.ToString("yyyy-MM-dd"),rows,cached=rows<0}));
        }
        Status();
        try
        {
            while(!state.Completed&&!stop.IsCancellationRequested)
            {
                try
                {
                    stage="connecting";Status();using var broker=await ExecutionBroker.Open(directory,config.Account.Id,()=>new RecorderConnection(new OpenApiConnection()));
                    if(broker.Account!=config.Account)throw new ArgumentException("Pinned archive source changed.");error=null;
                    while(!stop.IsCancellationRequested&&state.RecentNextUtc<state.EndUtc)
                    {var day=state.RecentNextUtc;await Download(broker,day);state=state with{RecentNextUtc=day.AddDays(1)};Save();failures=0;}
                    while(!stop.IsCancellationRequested&&state.OlderEndUtc>state.FloorUtc)
                    {
                        Disk();var to=state.OlderEndUtc;var from=to.AddDays(-6);if(from<state.FloorUtc)from=state.FloorUtc;
                        current=from;stage="checking-older-week";Status();
                        if(await HasTicks(broker.Api,broker.Account.Id,broker.SymbolId,from,to))
                        {for(var d=from;d<to&&!stop.IsCancellationRequested;d=d.AddDays(1))await Download(broker,d);}
                        else
                        {
                            string proof=Path.Combine(root,"empty-weeks");Directory.CreateDirectory(proof);
                            RecorderStore.AtomicJson(Path.Combine(proof,$"{from:yyyy-MM-dd}.json"),new{fromUtc=from,toUtcExclusive=to,queriedUtc=DateTime.UtcNow,bidEmpty=true,askEmpty=true});
                            state=state with{EmptyWeeks=state.EmptyWeeks+1};
                        }
                        if(stop.IsCancellationRequested)break;
                        state=state with{OlderEndUtc=from};Save();failures=0;
                    }
                    if(!stop.IsCancellationRequested){state=state with{Completed=true};stage="completed";current=null;Save();}
                }
                catch(OperationCanceledException)when(stop.IsCancellationRequested){break;}
                catch(Exception ex)
                {failures++;error=ex.GetType().Name;stage="retrying";Status();Console.Error.WriteLine(JsonSerializer.Serialize(new{eventType="archive_retry",utc=DateTime.UtcNow,error,failures}));await Task.Delay(TimeSpan.FromSeconds(Math.Min(60,Math.Pow(2,Math.Min(failures,6)))),stop.Token);}
            }
        }
        catch(OperationCanceledException)when(stop.IsCancellationRequested){}
        finally{if(!state.Completed)stage="stopped";Status();}
    }
}

static class TickArchiveChecks
{
    public static async Task Run()
    {
        var root=Path.Combine(Path.GetTempPath(),"archive-check-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(root);
        try
        {
            var day=new DateTime(2026,1,5,0,0,0,DateTimeKind.Utc);var api=new Fake();
            if(await TickArchive.HasTicks(api,123,41,day,day.AddDays(6))||api.Calls!=2)throw new Exception("Empty probe must check both sides.");
            api.Truncated=true;bool rejected=false;try{await TickArchive.HasTicks(api,123,41,day,day.AddDays(6));}catch(IOException){rejected=true;}
            if(!rejected)throw new Exception("Truncated empty probe must fail closed.");api.Truncated=false;api.Empty=false;
            string path=Path.Combine(root,"day.csv.gz");long count=await TickArchive.Day(api,123,41,day,path);
            if(count!=2||BacktestRunner.ReadQuotes(path).Count()!=1)throw new Exception("Daily archive must preserve both sides in compatible cache.");
            int calls=api.Calls;if(await TickArchive.Day(api,123,41,day,path)!=-1||api.Calls!=calls)throw new Exception("Cached day must not be downloaded twice.");
            api.FailAsk=true;path=Path.Combine(root,"failed.csv.gz");rejected=false;try{await TickArchive.Day(api,123,41,day,path);}catch(IOException){rejected=true;}
            if(!rejected||File.Exists(path))throw new Exception("Failed side must not publish partial day.");
            Console.WriteLine("Tick archive PASS: both-side empty proof, truncated probe rejection, compatible atomic daily cache, resume and side-failure safety. Fake broker only.");
        }
        finally{Directory.Delete(root,true);}
    }
    sealed class Fake:IExecutionConnection
    {
        public Action<int,JsonElement>? Received{get;set;}public bool Empty=true,Truncated,FailAsk;public int Calls;
        public Task Connect(AppCredentials a,TokenSet b,long accountId=48463366L,bool live=false)=>Task.CompletedTask;
        public Task<JsonElement> Request(int type,object payload,int expected)
        {
            if(type!=2145)throw new Exception("Archive attempted non-history request.");Calls++;var p=JsonSerializer.SerializeToElement(payload);int side=(int)Integer(p,"type");
            if(side==2&&FailAsk)throw new IOException("test");
            return Task.FromResult(JsonSerializer.SerializeToElement(new{hasMore=Truncated,tickData=Empty?Array.Empty<object>():new object[]{new{timestamp=Integer(p,"fromTimestamp")+1,tick=side==1?300000000L:300020000L}}}));
        }
        public void Dispose(){}
    }
}

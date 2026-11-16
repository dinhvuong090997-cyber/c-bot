using System.Globalization;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using static ExecutionFiles;

// Separate connection with a deny-by-default request list; cannot submit/modify/close orders.
sealed class RecorderConnection(IExecutionConnection inner) : IExecutionConnection
{
    public Action<int,JsonElement>? Received {get=>inner.Received;set=>inner.Received=value;}
    public Task Connect(AppCredentials app,TokenSet tokens,long accountId=48463366L,bool live=false)=>inner.Connect(app,tokens,accountId,live);
    public Task<JsonElement> Request(int type,object payload,int expected)
    {
        if(type is not (2112 or 2114 or 2116 or 2121 or 2127 or 2145 or 2149))throw new InvalidOperationException("Recorder rejected non-read-only request.");
        return inner.Request(type,payload,expected);
    }
    public void Dispose()=>inner.Dispose();
}

sealed class TickJournal(string directory) : IDisposable
{
    FileStream? file;StreamWriter? writer;string? day;DateTime flushed=DateTime.UtcNow;
    string session=Guid.NewGuid().ToString("N");
    public long Rows {get;private set;}public long Rejected {get;private set;}
    public DateTime? LastSpotUtc {get;private set;}public DateTime? LastReceivedUtc {get;private set;}
    public void BeginSession()=>session=Guid.NewGuid().ToString("N");
    public bool Record(JsonElement p,long account,long symbol,DateTime received)
    {
        if(Integer(p,"ctidTraderAccountId")!=account||Integer(p,"symbolId")!=symbol)return false;
        long stamp=Integer(p,"timestamp"),bid=Integer(p,"bid"),ask=Integer(p,"ask");
        if(stamp<1||stamp>new DateTimeOffset(received.AddSeconds(5)).ToUnixTimeMilliseconds()||
            (!p.TryGetProperty("bid",out _)&&!p.TryGetProperty("ask",out _))||
            (p.TryGetProperty("bid",out _)&&bid<=0)||(p.TryGetProperty("ask",out _)&&ask<=0))
        {Rejected++;return false;}
        var time=DateTimeOffset.FromUnixTimeMilliseconds(stamp).UtcDateTime;var date=time.ToString("yyyy-MM-dd");
        if(day!=date)
        {
            Close();Directory.CreateDirectory(directory);var path=Path.Combine(directory,$"XAUUSD-{date}.csv");
            file=new FileStream(path,FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.Read);
            // A killed process can leave a partial final row; retain every complete row.
            long end=file.Length;
            while(end>0){file.Position=end-1;if(file.ReadByte()=='\n')break;end--;}
            file.SetLength(end);file.Position=end;
            writer=new StreamWriter(file,new UTF8Encoding(false),65536,leaveOpen:true);day=date;
            if(end==0)writer.WriteLine("received_utc,timestamp_ms,side,price_1e5,connection");
        }
        void Write(int side,long price){writer!.WriteLine($"{received:O},{stamp},{side},{price},{session}");Rows++;}
        if(bid>0)Write(1,bid);if(ask>0)Write(2,ask);
        LastSpotUtc=time;LastReceivedUtc=received;
        if(received-flushed>=TimeSpan.FromSeconds(1))Flush();
        return true;
    }
    public void Flush(){writer?.Flush();file?.Flush(true);flushed=DateTime.UtcNow;}
    void Close(){try{Flush();}finally{writer?.Dispose();file?.Dispose();writer=null;file=null;day=null;}}
    public void Dispose()=>Close();
}

sealed class RecorderStore
{
    sealed record Coverage(int SchemaVersion,long AccountId,bool Live,DateTime StartUtc,DateTime CoveredUntilUtc);
    readonly string root,cache,checkpoint;readonly ExecutionAccount account;
    public DateTime StartUtc {get;private set;}public DateTime CoveredUntil {get;private set;}
    public long HistoryRows {get;private set;}public long EmptyHours {get;private set;}
    public RecorderStore(string root,string cache,ExecutionAccount account,DateTime start)
    {
        this.root=root;this.cache=cache;this.account=account;checkpoint=Path.Combine(root,"coverage.json");Directory.CreateDirectory(root);
        if(account.Live)throw new ArgumentException("Recorder currently targets the saved demo data source only.");
        StartUtc=start;CoveredUntil=start;
        if(File.Exists(checkpoint))
        {
            var c=JsonSerializer.Deserialize<Coverage>(File.ReadAllText(checkpoint),Json)??throw new IOException("Invalid recorder coverage.");
            if(c.SchemaVersion!=1||c.AccountId!=account.Id||c.Live!=account.Live||c.StartUtc.TimeOfDay!=TimeSpan.Zero||c.CoveredUntilUtc<c.StartUtc||c.CoveredUntilUtc.Ticks%TimeSpan.TicksPerHour!=0||c.CoveredUntilUtc>DateTime.UtcNow)
                throw new IOException("Recorder coverage identity or interval is invalid.");
            StartUtc=c.StartUtc;CoveredUntil=c.CoveredUntilUtc;
        }
        for(var hour=StartUtc;hour<CoveredUntil;hour=hour.AddHours(1))
            if(!File.Exists(HourPath(hour))){CoveredUntil=hour;break;}
        SaveCoverage();
    }
    public string HourPath(DateTime hour)=>Path.Combine(root,"history",$"XAUUSD-{hour:yyyy-MM-dd-HH}.csv.gz");
    public static void AtomicJson(string path,object value)
    {
        var temp=path+".tmp";using(var file=new FileStream(temp,FileMode.Create,FileAccess.Write,FileShare.None))
        {JsonSerializer.Serialize(file,value,Json);file.Flush(true);}File.Move(temp,path,true);
    }
    void SaveCoverage()=>AtomicJson(checkpoint,new Coverage(1,account.Id,account.Live,StartUtc,CoveredUntil));
    public static IEnumerable<(long Time,int Side,long Price)> ReadTicks(string path)
    {
        using var file=File.OpenRead(path);using var gzip=new GZipStream(file,CompressionMode.Decompress);using var reader=new StreamReader(gzip);
        if(reader.ReadLine()!="timestamp_ms,side,price_1e5")throw new IOException("Invalid recorded tick schema.");
        long last=-1;
        while(reader.ReadLine() is {} line)
        {
            var fields=line.Split(',');if(fields.Length!=3)throw new IOException("Invalid tick row.");
            long stamp=long.Parse(fields[0],CultureInfo.InvariantCulture),price=long.Parse(fields[2],CultureInfo.InvariantCulture);int side=int.Parse(fields[1],CultureInfo.InvariantCulture);
            if(stamp<last||price<=0||side is not (1 or 2))throw new IOException("Invalid recorded tick order/value.");last=stamp;
            yield return(stamp,side,price);
        }
    }
    internal static void WriteTicks(string path,IEnumerable<(long Time,int Side,long Price)> ticks,bool replace=true)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);var temp=path+".tmp";
        using(var file=new FileStream(temp,FileMode.Create,FileAccess.Write,FileShare.None))
        {
            using(var gzip=new GZipStream(file,CompressionLevel.Fastest,leaveOpen:true))
            using(var writer=new StreamWriter(gzip,new UTF8Encoding(false)))
            {writer.WriteLine("timestamp_ms,side,price_1e5");foreach(var t in ticks)writer.WriteLine($"{t.Time},{t.Side},{t.Price}");}
            file.Flush(true);
        }
        File.Move(temp,path,replace);
    }
    void PublishDay(DateTime day)
    {
        var target=Path.Combine(cache,$"XAUUSD-{day:yyyy-MM-dd}.csv.gz");if(File.Exists(target))return;
        IEnumerable<(long Time,int Side,long Price)> DayTicks()
        {
            for(int h=0;h<24;h++)
            {
                var hour=day.AddHours(h);long a=new DateTimeOffset(hour).ToUnixTimeMilliseconds(),b=a+3600000;
                foreach(var t in ReadTicks(HourPath(hour))){if(t.Time<a||t.Time>=b)throw new IOException("Tick outside recorded hour.");yield return t;}
            }
        }
        WriteTicks(target,DayTicks(),replace:false);
    }
    public async Task<bool> BackfillHour(IExecutionConnection api,long accountId,long symbol,DateTime now,Func<bool>? stopped=null)
    {
        if(accountId!=account.Id)throw new InvalidOperationException("Recorder account mismatch.");
        var from=CoveredUntil;var to=from.AddHours(1);if(to>now.AddSeconds(-60))return false;
        long a=new DateTimeOffset(from).ToUnixTimeMilliseconds(),b=new DateTimeOffset(to).ToUnixTimeMilliseconds();
        var ticks=await TickHistory.Fetch(api,accountId,symbol,a,b,1,stopped);
        ticks.AddRange(await TickHistory.Fetch(api,accountId,symbol,a,b,2,stopped));
        if(stopped?.Invoke()==true)throw new OperationCanceledException();
        ticks.Sort((x,y)=>x.Time!=y.Time?x.Time.CompareTo(y.Time):x.Side.CompareTo(y.Side));
        WriteTicks(HourPath(from),ticks);
        if(to.TimeOfDay==TimeSpan.Zero)PublishDay(from.Date);
        var old=CoveredUntil;CoveredUntil=to;
        try{SaveCoverage();}catch{CoveredUntil=old;throw;}
        HistoryRows+=ticks.Count;if(ticks.Count==0)EmptyHours++;
        return true;
    }
}

static class DataRecorder
{
    public static async Task Run(string directory,string[] args)
    {
        if(args.Length is not (1 or 3)||args.Length==3&&args[1]!="--from")throw new ArgumentException("record-data [--from YYYY-MM-DD] (initial coverage start only)");
        var start=args.Length==3?DateTime.ParseExact(args[2],"yyyy-MM-dd",CultureInfo.InvariantCulture,DateTimeStyles.AssumeUniversal|DateTimeStyles.AdjustToUniversal):DateTime.UtcNow.Date.AddDays(-1);
        if(start>DateTime.UtcNow.Date||start<new DateTime(2000,1,1))throw new ArgumentException("Invalid recorder start date.");
        var selected=JsonSerializer.Deserialize<ExecutionConfig>(File.ReadAllText(Path.Combine(directory,"execution-config.json")),Json)??throw new ArgumentException("Saved demo config required.");
        selected.Validate();if(selected.Account.Live)throw new ArgumentException("Select the existing demo data source.");
        var root=Path.Combine("data","recorder-xauusd");Directory.CreateDirectory(root);
        using var lease=new FileStream(Path.Combine(root,"recorder.lock"),FileMode.OpenOrCreate,FileAccess.ReadWrite,FileShare.None);
        var store=new RecorderStore(root,Path.Combine("data","fxpro-v2"),selected.Account,start);
        if(args.Length==3&&start!=store.StartUtc)throw new ArgumentException("Existing coverage start is pinned; use a separate data directory for a different origin.");
        using var journal=new TickJournal(Path.Combine(root,"live"));using var stop=new CancellationTokenSource();
        using var term=PosixSignalRegistration.Create(PosixSignal.SIGTERM,c=>{c.Cancel=true;stop.Cancel();});
        Console.CancelKeyPress+=(s,e)=>{e.Cancel=true;stop.Cancel();};
        int failures=0;DateTime? connected=null;string state="starting";string? error=null;
        void Status()=>RecorderStore.AtomicJson(Path.Combine(root,"status.json"),new{schemaVersion=1,state,heartbeatUtc=DateTime.UtcNow,connectedUtc=connected,source="FxPro demo XAUUSD",readOnly=true,counterScope="process",unverifiedTailSeconds=Math.Max(0,(DateTime.UtcNow-store.CoveredUntil).TotalSeconds),freshQuote=journal.LastSpotUtc is {} last&&DateTime.UtcNow-last<=TimeSpan.FromSeconds(5),journal.Rows,journal.Rejected,journal.LastSpotUtc,journal.LastReceivedUtc,store.StartUtc,coveredUntilUtc=store.CoveredUntil,pendingHours=Math.Max(0,(int)Math.Floor((DateTime.UtcNow.AddSeconds(-60)-store.CoveredUntil).TotalHours)),store.HistoryRows,store.EmptyHours,failures,error,message="Live journal is provisional; coverage is broker-queried hours, not proof of tick completeness."});
        Status();
        try
        {
            while(!stop.IsCancellationRequested)
            {
                try
                {
                    state="connecting";Status();
                    using var broker=await ExecutionBroker.Open(directory,selected.Account.Id,()=>new RecorderConnection(new OpenApiConnection()));
                    if(broker.Account!=selected.Account)throw new ArgumentException("Pinned recorder account changed.");
                    journal.BeginSession();broker.Api.Received=(type,p)=>{if(type==2131)journal.Record(p,broker.Account.Id,broker.SymbolId,DateTime.UtcNow);};
                    await broker.Api.Request(2127,new{ctidTraderAccountId=broker.Account.Id,symbolId=new[]{broker.SymbolId},subscribeToSpotTimestamp=true},2128);
                    connected=DateTime.UtcNow;error=null;state="recording";Status();
                    Console.WriteLine(JsonSerializer.Serialize(new{eventType="recorder_connected",utc=connected,readOnly=true}));
                    while(!stop.IsCancellationRequested)
                    {
                        bool backfill=await store.BackfillHour(broker.Api,broker.Account.Id,broker.SymbolId,DateTime.UtcNow,()=>stop.IsCancellationRequested);
                        // Requests continuously drain unsolicited spot events and the transport emits heartbeats.
                        if(!backfill)await broker.RefreshTrader();
                        journal.Flush();state=backfill?"backfilling":"recording";Status();failures=0;
                        if(!backfill)await Task.Delay(TimeSpan.FromSeconds(2),stop.Token);
                    }
                }
                catch(OperationCanceledException)when(stop.IsCancellationRequested){break;}
                catch(Exception ex)
                {
                    journal.Flush();failures++;error=ex.GetType().Name;state="reconnecting";connected=null;Status();
                    Console.Error.WriteLine(JsonSerializer.Serialize(new{eventType="recorder_retry",utc=DateTime.UtcNow,error,failures}));
                    await Task.Delay(TimeSpan.FromSeconds(Math.Min(60,Math.Pow(2,Math.Min(failures,6)))),stop.Token);
                }
            }
        }
        catch(OperationCanceledException)when(stop.IsCancellationRequested){}
        finally{journal.Flush();state="stopped";Status();}
    }
}

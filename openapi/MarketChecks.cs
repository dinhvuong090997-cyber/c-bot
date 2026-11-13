using System.Text.Json;
using System.IO.Compression;
using static ExecutionFiles;

static class MarketChecks
{
    static void Check(bool condition,string message){if(!condition)throw new Exception("Market check failed: "+message);}
    public static async Task Run()
    {
        JsonElement E(object value)=>JsonSerializer.SerializeToElement(value);
        foreach(var type in new[]{2106,2108,2109,2110,2111})Check(!MonitorConnection.Allowed(type),"monitor must prohibit trading request "+type);
        foreach(var type in new[]{2121,2124,2127,2133,2137,2187})Check(MonitorConnection.Allowed(type),"required read-only request "+type);
        var b=CandleBook.Decode(E(new {utcTimestampInMinutes=100,low=300000000,deltaOpen=10000,deltaHigh=50000,deltaClose=20000,volume=42}));
        Check(b.Time==6000&&b.Open==3000.1&&b.Close==3000.2&&b.High==3000.5&&b.Volume==42,"broker candle deltas, seconds and ticks");
        var book=new CandleBook();book.Load(new[]{b});book.Tick(6030000,3000.8);book.Tick(6040000,3000.05);book.Tick(6060000,3000.3);book.Tick(6010000,2500);
        var bars=book.All();Check(bars.Length==2&&bars[0].High==3000.8&&bars[0].Low==3000&&bars[0].Close==3000.05&&bars[1].Open==3000.3,"live OHLC aggregation ignores old minutes and preserves order");
        var dir=Path.Combine(Path.GetTempPath(),"aurum-market-check-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(dir);
        try
        {
            Save(Path.Combine(dir,"app.json"),new AppCredentials("test","test"));Save(Path.Combine(dir,"tokens.json"),new TokenSet("test","test",DateTimeOffset.UtcNow.AddHours(1)));
            var wire=new ExecutionChecks.FakeConnection();using var monitor=new MarketMonitor(dir,()=>wire);
            var account=new ExecutionAccount(123,"456","FxPro",false);
            Check(monitor.Snapshot(account).Summary is null,"new account cannot inherit a previous snapshot");
            for(int i=0;i<150&&monitor.Snapshot(account).Summary is null;i++)await Task.Delay(10);
            Check(monitor.Snapshot(account).Summary?.Balance==50000&&wire.Orders==0&&wire.Closes==0,"monitor loads actual fake account without orders");
            var changed=monitor.Snapshot(account with {Id=999});Check(changed.Summary is null&&changed.Positions.Length==0&&changed.Bars.Length==0,"account switch clears price, positions and balance immediately");
            monitor.Dispose();
        }
        finally{Directory.Delete(dir,true);}
        var previous=Directory.GetCurrentDirectory();var historyDir=Path.Combine(Path.GetTempPath(),"aurum-chart-check-"+Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(Path.Combine(historyDir,"data","fxpro-v2"));Directory.SetCurrentDirectory(historyDir);
            var day=new DateTime(2026,1,1,0,0,0,DateTimeKind.Utc);long t=new DateTimeOffset(day).ToUnixTimeMilliseconds();
            using(var gzip=new GZipStream(File.Create("data/fxpro-v2/XAUUSD-2026-01-01.csv.gz"),CompressionMode.Compress))
            using(var writer=new StreamWriter(gzip))writer.Write($"timestamp,side,price\n{t},1,10000000\n{t},2,10010000\n{t+1000},1,10100000\n{t+1000},2,10110000\n{t+60000},1,9900000\n{t+60000},2,9910000\n");
            var history=ChartHistory.Build(day,day.AddDays(2),5);
            Check(history.MissingDays&&history.Bars.Length==1&&history.Bars[0].Open==100&&history.Bars[0].High==101&&history.Bars[0].Low==99&&history.Bars[0].Close==99&&history.Bars[0].Volume==3,"cached bid candles preserve OHLC, activity and missing days");
        }
        finally{Directory.SetCurrentDirectory(previous);Directory.Delete(historyDir,true);}
        Console.WriteLine("Market checks PASS: trading API prohibition, OHLC decoding/aggregation, chronological updates, live account isolation and no orders.");
    }
}

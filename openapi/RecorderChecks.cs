using System.Text.Json;
using static ExecutionFiles;

static class RecorderChecks
{
    static void Check(bool value,string message){if(!value)throw new Exception("Recorder check failed: "+message);}
    public static async Task Run()
    {
        var dir=Path.Combine(Path.GetTempPath(),"aurum-recorder-"+Guid.NewGuid().ToString("N"));Directory.CreateDirectory(dir);
        try
        {
            var start=new DateTime(2026,1,5,0,0,0,DateTimeKind.Utc);long a=new DateTimeOffset(start).ToUnixTimeMilliseconds();
            using(var journal=new TickJournal(Path.Combine(dir,"live")))
            {
                Check(journal.Record(JsonSerializer.SerializeToElement(new{ctidTraderAccountId=123,symbolId=41,timestamp=a,bid=300000000L}),123,41,start),"bid-only tick accepted");
                journal.Record(JsonSerializer.SerializeToElement(new{ctidTraderAccountId=123,symbolId=41,timestamp=a,ask=300020000L}),123,41,start);
                Check(!journal.Record(JsonSerializer.SerializeToElement(new{ctidTraderAccountId=123,symbolId=41,bid=1}),123,41,start),"untimestamped rejected");
                Check(!journal.Record(JsonSerializer.SerializeToElement(new{ctidTraderAccountId=123,symbolId=42,timestamp=a,bid=1}),123,41,start),"foreign symbol rejected");
                journal.Record(JsonSerializer.SerializeToElement(new{ctidTraderAccountId=123,symbolId=41,timestamp=a+86400000,bid=301000000L,ask=301020000L}),123,41,start.AddDays(1));journal.Flush();
                Check(journal.Rows==4,"partial sides not fabricated");
            }
            var live=Path.Combine(dir,"live","XAUUSD-2026-01-05.csv");File.AppendAllText(live,"torn-tail");
            using(var journal=new TickJournal(Path.Combine(dir,"live"))){journal.Record(JsonSerializer.SerializeToElement(new{ctidTraderAccountId=123,symbolId=41,timestamp=a,bid=300000000L}),123,41,start);}
            Check(!File.ReadAllText(live).Contains("torn-tail"),"restart truncates only incomplete trailing line");
            var selected=new ExecutionAccount(123,"456","FxPro",false);
            var store=new RecorderStore(Path.Combine(dir,"capture"),Path.Combine(dir,"cache"),selected,start);
            var api=new Fake {FailAsk=true,Stamp=a};bool failed=false;
            try{await store.BackfillHour(api,123,41,start.AddHours(2));}catch(IOException){failed=true;}
            Check(failed&&store.CoveredUntil==start,"failed second side cannot advance coverage");
            api.FailAsk=false;Check(await store.BackfillHour(api,123,41,start.AddHours(2)),"settled hour downloaded");
            Check(store.CoveredUntil==start.AddHours(1),"checkpoint advanced exactly one hour");
            Check(!await store.BackfillHour(api,123,41,start.AddHours(1).AddSeconds(30)),"unsettled hour stays pending");
            Check(RecorderStore.ReadTicks(store.HourPath(start)).Count()==3,"duplicate-ms distinct bid prices preserved");
            Check(!File.Exists(Path.Combine(dir,"cache","XAUUSD-2026-01-05.csv.gz")),"no incomplete day published");
            for(int h=1;h<24;h++){api.Stamp=a+h*3600000L;await store.BackfillHour(api,123,41,start.AddDays(1).AddMinutes(2));}
            var daily=Path.Combine(dir,"cache","XAUUSD-2026-01-05.csv.gz");Check(File.Exists(daily),"24hours publish compatible daily cache");
            Check(BacktestRunner.ReadQuotes(daily).Count()==24,"existing conservative quote reader accepts daily cache");
            var original=File.ReadAllBytes(daily);File.Delete(store.HourPath(start.AddHours(3)));
            var resumed=new RecorderStore(Path.Combine(dir,"capture"),Path.Combine(dir,"cache"),selected,start);Check(resumed.CoveredUntil==start.AddHours(3),"missing chunk rewinds coverage");
            api.Stamp=a+3*3600000L;await resumed.BackfillHour(api,123,41,start.AddDays(1).AddMinutes(2));Check(original.SequenceEqual(File.ReadAllBytes(daily)),"recovery never overwrites old daily cache");
            foreach(var type in new[]{2106,2109,2110,2111,2120})
            {
                bool denied=false;using(var readOnly=new RecorderConnection(api)){try{await readOnly.Request(type,new{},2126);}catch(InvalidOperationException){denied=true;}}
                Check(denied,"order mutation rejected before transport");
            }
            bool wrongAccount=false;try{await resumed.BackfillHour(api,999,41,start.AddDays(1));}catch(InvalidOperationException){wrongAccount=true;}
            Check(wrongAccount,"foreign account fails before history requests");
            var coverage=Path.Combine(dir,"capture","coverage.json");File.WriteAllText(coverage,"invalid-json");
            bool corrupt=false;try{_ = new RecorderStore(Path.Combine(dir,"capture"),Path.Combine(dir,"cache"),selected,start);}catch(JsonException){corrupt=true;}
            Check(corrupt&&File.ReadAllText(coverage)=="invalid-json","corrupt coverage fails closed without resetting origin");
            Console.WriteLine("Recorder PASS: journal durability/rotation/partial sides, read-only allowlist, failed-hour recovery, settlement, tied ticks, full-day cache and missing-chunk rewind. Fake broker only.");
        }
        finally{Directory.Delete(dir,true);}
    }
    sealed class Fake:IExecutionConnection
    {
        public Action<int,JsonElement>? Received{get;set;}public bool FailAsk;public long Stamp;
        public Task Connect(AppCredentials app,TokenSet token,long accountId=48463366L,bool live=false)=>Task.CompletedTask;
        public Task<JsonElement> Request(int type,object payload,int expected)
        {
            if(type!=2145)throw new Exception("Unexpected recorder request");
            int side=(int)Integer(JsonSerializer.SerializeToElement(payload),"type");if(side==2&&FailAsk)throw new IOException("test disconnect");
            return Task.FromResult(JsonSerializer.SerializeToElement(new{hasMore=false,tickData=side==1?new[]{new{timestamp=Stamp,tick=300000000L},new{timestamp=0L,tick=-1000L}}:new[]{new{timestamp=Stamp,tick=300020000L}}}));
        }
        public void Dispose(){}
    }
}

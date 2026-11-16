static class SwingTrailing
{
    public static bool TryMove(BacktestRunner.Position position,BacktestRunner.Quote quote,RangePaStructure.Pivot pivot,double size,out double oldStop)
    {
        oldStop=position.Stop;double executable=position.Long?quote.Bid:quote.Ask;
        if(pivot.Index<=position.LastTrailedPivotIndex)return false;
        if(pivot.High==position.Long||pivot.PivotUtc<=position.EntryTime||pivot.KnownUtc>=quote.Time||pivot.KnownUtc<=position.EntryTime)return false;
        if(position.Long?executable<=position.Stop||executable>=position.Target:executable>=position.Stop||executable<=position.Target)return false;
        double buffer=Math.Max(quote.Ask-quote.Bid,size*.1),raw=pivot.Price+(position.Long?-buffer:buffer);
        double next=position.Long?Math.Floor(raw*100+1e-9)/100:Math.Ceiling(raw*100-1e-9)/100;
        next=Math.Round(next,2);
        if(position.Long?next<=oldStop+1e-9||next>=executable:next>=oldStop-1e-9||next<=executable)return false;
        position.Stop=next;position.TrailingUpdates++;position.LastTrailedPivotIndex=pivot.Index;return true;
    }
    public static void Checks()
    {
        var day=new DateTime(2026,1,5,0,0,0,DateTimeKind.Utc);
        BacktestRunner.Position P(bool buy)=>new(){EntryTime=day,Long=buy,Entry=100,Stop=buy?95:105,InitialStop=buy?95:105,Target=buy?120:80,Volume=1,EntryCommission=0,Session="NewYork",NextRollover=day.AddDays(1)};
        var q=new BacktestRunner.Quote(new DateTimeOffset(day.AddSeconds(10)).ToUnixTimeMilliseconds(),110,110.123);
        var low=new RangePaStructure.Pivot(false,103.017,3,5,day.AddSeconds(8),day.AddSeconds(5));var buy=P(true);
        if(!TryMove(buy,q,low,2,out _)||buy.Stop!=102.81||buy.InitialStop!=95)throw new Exception("BUY trail/rounding/initial-risk failed");
        if(TryMove(buy,q,low with{Price=101,Index=4},2,out _))throw new Exception("Trailing stop loosened");
        if(TryMove(P(true),q,low with{KnownUtc=q.Time},2,out _))throw new Exception("Same-tick confirmation applied retroactively");
        if(TryMove(P(true),q,low with{PivotUtc=day.AddSeconds(-1)},2,out _))throw new Exception("Old pre-entry pivot used");
        if(TryMove(P(true),q,low with{Price=112},2,out _))throw new Exception("BUY stop crossed executable price");
        var once=P(true);TryMove(once,new BacktestRunner.Quote(q.Milliseconds,110,110.5),low,2,out _);
        if(TryMove(once,new BacktestRunner.Quote(q.Milliseconds+1000,110,110.1),low,2,out _))throw new Exception("Same swing retriggered after spread narrowing");
        var high=low with{High=true,Price=97.017};var sell=P(false);var sq=new BacktestRunner.Quote(q.Milliseconds,89.8,90);
        if(!TryMove(sell,sq,high,2,out _)||sell.Stop!=97.22)throw new Exception("SELL trail/rounding failed");
        if(TryMove(P(true),new BacktestRunner.Quote(q.Milliseconds,94,94.1),low,2,out _))throw new Exception("Old stop loss ignored");
        Console.WriteLine("Swing trailing PASS: mirrored/outward prices, causal post-entry pivots, no loosening/backdating and old protection first.");
    }
}

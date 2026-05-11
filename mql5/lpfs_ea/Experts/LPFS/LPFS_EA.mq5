//+------------------------------------------------------------------+
//| LPFS_EA.mq5                                                     |
//| Native MQL5 tester-only port scaffold for LP + Force Strike.     |
//| Python remains canonical until fixture parity and tester checks   |
//| pass. Do not attach this v1 EA to production live charts.         |
//+------------------------------------------------------------------+
#property strict
#property version   "1.00"
#property description "LPFS native MQL5 EA migration scaffold. Tester-only v1."

#include <Trade/Trade.mqh>

enum ENUM_LPFS_RISK_PROFILE
{
   LPFS_RISK_CONSERVATIVE = 0,
   LPFS_RISK_STANDARD     = 1,
   LPFS_RISK_GROWTH       = 2
};

input ENUM_LPFS_RISK_PROFILE InpRiskProfile        = LPFS_RISK_STANDARD;
input double                 InpMaxOpenRiskPct     = 0.0;  // 0 uses profile default
input int                    InpMaxConcurrentTrades = 0;   // 0 uses profile default
input int                    InpMaxSameSymbolTrades = 0;   // 0 uses profile default
input long                   InpMagicNumber        = 331500;
input string                 InpCommentPrefix      = "LPFSEA";
input bool                   InpTesterOnly         = true;
input bool                   InpAllowLiveTrading   = false;
input bool                   InpEnablePrintLog     = true;
input int                    InpHistoryBars        = 300;

static const int    LPFS_PIVOT_STRENGTH = 3;
static const int    LPFS_MAX_BARS_FROM_LP_BREAK = 6;
static const int    LPFS_MAX_ENTRY_WAIT_BARS = 6;
static const double LPFS_SIGNAL_ZONE = 0.5;
static const double LPFS_TARGET_R = 1.0;
static const double LPFS_MAX_SPREAD_RISK_FRACTION = 0.10;
static const bool   LPFS_REQUIRE_LP_PIVOT_BEFORE_FS_MOTHER = true;

string LPFS_SYMBOLS[] = {
   "AUDCAD","AUDCHF","AUDJPY","AUDNZD","AUDUSD",
   "CADCHF","CADJPY","CHFJPY","EURAUD","EURCAD",
   "EURCHF","EURGBP","EURJPY","EURNZD","EURUSD",
   "GBPAUD","GBPCAD","GBPCHF","GBPJPY","GBPNZD",
   "GBPUSD","NZDCAD","NZDCHF","NZDJPY","NZDUSD",
   "USDCAD","USDCHF","USDJPY"
};

ENUM_TIMEFRAMES LPFS_TIMEFRAMES[] = {PERIOD_H4, PERIOD_H8, PERIOD_H12, PERIOD_D1, PERIOD_W1};

struct LpfsRiskSchedule
{
   double h4h8;
   double h12d1;
   double w1;
   double max_open_risk_pct;
   int    max_concurrent_trades;
   int    max_same_symbol_trades;
};

struct LpfsLevel
{
   int side;               // 1 resistance, -1 support
   double price;
   int pivot_index;
   datetime pivot_time;
   int confirmed_index;
   datetime confirmed_time;
};

struct LpfsBreakEvent
{
   int side;               // 1 resistance, -1 support
   double price;
   int pivot_index;
   datetime pivot_time;
   int confirmed_index;
   datetime confirmed_time;
   int break_index;
   datetime break_time;
};

struct LpfsTrapWindow
{
   int signal_side;        // 1 bullish, -1 bearish
   string scenario;
   LpfsBreakEvent event;
};

struct LpfsForceStrikePattern
{
   int side;               // 1 bullish, -1 bearish
   int mother_index;
   int signal_index;
   datetime mother_time;
   datetime signal_time;
   double mother_high;
   double mother_low;
   double structure_high;
   double structure_low;
   int total_bars;
};

struct LpfsSignal
{
   int side;               // 1 long/bullish, -1 short/bearish
   string scenario;
   double lp_price;
   int lp_break_index;
   int lp_pivot_index;
   int fs_mother_index;
   int fs_signal_index;
   datetime fs_signal_time;
   int bars_from_lp_break;
   int fs_total_bars;
};

CTrade trade;

int OnInit()
{
   if(InpTesterOnly && !MQLInfoInteger(MQL_TESTER))
   {
      Print("LPFS EA refused to initialize: tester-only v1 requires MT5 Strategy Tester.");
      return INIT_FAILED;
   }
   if(!InpAllowLiveTrading && !MQLInfoInteger(MQL_TESTER))
   {
      Print("LPFS EA refused to initialize: live trading is disabled for v1.");
      return INIT_FAILED;
   }
   if(InpMagicNumber <= 0)
   {
      Print("LPFS EA refused to initialize: MagicNumber must be positive.");
      return INIT_FAILED;
   }
   if(StringLen(InpCommentPrefix) < 3)
   {
      Print("LPFS EA refused to initialize: CommentPrefix must contain at least three characters.");
      return INIT_FAILED;
   }
   trade.SetExpertMagicNumber(InpMagicNumber);
   PrintBacktestDisclosure();
   return INIT_SUCCEEDED;
}

void OnTick()
{
   if(!MQLInfoInteger(MQL_TESTER) && !InpAllowLiveTrading)
      return;

   for(int symbol_index = 0; symbol_index < ArraySize(LPFS_SYMBOLS); symbol_index++)
   {
      string symbol = LPFS_SYMBOLS[symbol_index];
      if(!SymbolSelect(symbol, true))
         continue;
      for(int tf_index = 0; tf_index < ArraySize(LPFS_TIMEFRAMES); tf_index++)
         ScanSymbolTimeframe(symbol, LPFS_TIMEFRAMES[tf_index]);
   }
}

void ScanSymbolTimeframe(const string symbol, const ENUM_TIMEFRAMES timeframe)
{
   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(symbol, timeframe, 1, InpHistoryBars, rates);
   if(copied < 20)
      return;

   LpfsSignal signal;
   if(!DetectLatestLpfsSignal(rates, copied, timeframe, signal))
      return;
   if(signal.fs_signal_index != copied - 1)
      return;

   BuildAndPlaceTesterOrder(symbol, timeframe, rates, copied, signal);
}

bool DetectLatestLpfsSignal(MqlRates &rates[], const int count, const ENUM_TIMEFRAMES timeframe, LpfsSignal &out_signal)
{
   out_signal.fs_signal_index = -1;
   LpfsLevel active[];
   LpfsTrapWindow windows[];

   for(int current = 0; current < count; current++)
   {
      datetime cutoff = rates[current].time - LookbackDaysForTimeframe(timeframe) * 86400;
      LpfsBreakEvent current_breaks[];
      LpfsLevel still_active[];

      for(int i = 0; i < ArraySize(active); i++)
      {
         if(active[i].pivot_time < cutoff)
            continue;
         bool breached = (active[i].side == 1 && rates[current].high >= active[i].price)
                      || (active[i].side == -1 && rates[current].low <= active[i].price);
         if(breached)
         {
            LpfsBreakEvent event;
            event.side = active[i].side;
            event.price = active[i].price;
            event.pivot_index = active[i].pivot_index;
            event.pivot_time = active[i].pivot_time;
            event.confirmed_index = active[i].confirmed_index;
            event.confirmed_time = active[i].confirmed_time;
            event.break_index = current;
            event.break_time = rates[current].time;
            PushBreak(current_breaks, event);
         }
         else
         {
            PushLevel(still_active, active[i]);
         }
      }
      ArrayCopy(active, still_active);

      AddTrapWindows(current_breaks, windows);
      PruneTrapWindows(windows, current);

      int pivot_index = current - LPFS_PIVOT_STRENGTH;
      if(pivot_index >= LPFS_PIVOT_STRENGTH && rates[pivot_index].time >= cutoff)
      {
         if(IsStrictPivotHigh(rates, pivot_index, LPFS_PIVOT_STRENGTH))
         {
            LpfsLevel level;
            level.side = 1;
            level.price = rates[pivot_index].high;
            level.pivot_index = pivot_index;
            level.pivot_time = rates[pivot_index].time;
            level.confirmed_index = current;
            level.confirmed_time = rates[current].time;
            PushLevel(active, level);
         }
         if(IsStrictPivotLow(rates, pivot_index, LPFS_PIVOT_STRENGTH))
         {
            LpfsLevel level;
            level.side = -1;
            level.price = rates[pivot_index].low;
            level.pivot_index = pivot_index;
            level.pivot_time = rates[pivot_index].time;
            level.confirmed_index = current;
            level.confirmed_time = rates[current].time;
            PushLevel(active, level);
         }
      }

      LpfsForceStrikePattern pattern;
      if(!DetectForceStrikePatternEndingAt(rates, count, current, pattern))
         continue;

      int selected_index = SelectMatchingWindow(windows, pattern, rates[current].close);
      if(selected_index < 0)
         continue;

      LpfsTrapWindow selected = windows[selected_index];
      out_signal.side = selected.signal_side;
      out_signal.scenario = selected.scenario;
      out_signal.lp_price = selected.event.price;
      out_signal.lp_break_index = selected.event.break_index;
      out_signal.lp_pivot_index = selected.event.pivot_index;
      out_signal.fs_mother_index = pattern.mother_index;
      out_signal.fs_signal_index = pattern.signal_index;
      out_signal.fs_signal_time = pattern.signal_time;
      out_signal.bars_from_lp_break = pattern.signal_index - selected.event.break_index + 1;
      out_signal.fs_total_bars = pattern.total_bars;
      RemoveTrapWindow(windows, selected_index);
   }

   return out_signal.fs_signal_index > 0;
}

bool DetectForceStrikePatternEndingAt(MqlRates &rates[], const int count, const int signal_index, LpfsForceStrikePattern &pattern)
{
   if(signal_index < 2 || signal_index >= count)
      return false;

   int first_mother = MathMax(0, signal_index - 5);
   int last_mother = signal_index - 2;
   for(int mother = first_mother; mother <= last_mother; mother++)
   {
      if(!InsideMother(rates[mother + 1], rates[mother].high, rates[mother].low))
         continue;

      double mother_high = rates[mother].high;
      double mother_low = rates[mother].low;
      bool broke_low = false;
      bool broke_high = false;
      double structure_high = rates[mother].high;
      double structure_low = rates[mother].low;

      for(int i = mother + 1; i <= signal_index; i++)
      {
         if(rates[i].low < mother_low)
            broke_low = true;
         if(rates[i].high > mother_high)
            broke_high = true;
         structure_high = MathMax(structure_high, rates[i].high);
         structure_low = MathMin(structure_low, rates[i].low);
      }
      if(broke_low && broke_high)
         continue;
      if(rates[signal_index].close < mother_low || rates[signal_index].close > mother_high)
         continue;

      int side = 0;
      if(broke_low && IsBullishSignalBar(rates[signal_index]))
         side = 1;
      if(broke_high && IsBearishSignalBar(rates[signal_index]))
         side = -1;
      if(side == 0)
         continue;

      pattern.side = side;
      pattern.mother_index = mother;
      pattern.signal_index = signal_index;
      pattern.mother_time = rates[mother].time;
      pattern.signal_time = rates[signal_index].time;
      pattern.mother_high = mother_high;
      pattern.mother_low = mother_low;
      pattern.structure_high = structure_high;
      pattern.structure_low = structure_low;
      pattern.total_bars = signal_index - mother + 1;
      return true;
   }
   return false;
}

void BuildAndPlaceTesterOrder(const string symbol, const ENUM_TIMEFRAMES timeframe, MqlRates &rates[], const int count, const LpfsSignal &signal)
{
   double signal_high = rates[signal.fs_signal_index].high;
   double signal_low = rates[signal.fs_signal_index].low;
   if(signal_high <= signal_low)
      return;

   double structure_low = rates[signal.fs_mother_index].low;
   double structure_high = rates[signal.fs_mother_index].high;
   for(int i = signal.fs_mother_index; i <= signal.fs_signal_index; i++)
   {
      structure_low = MathMin(structure_low, rates[i].low);
      structure_high = MathMax(structure_high, rates[i].high);
   }

   bool is_long = signal.side == 1;
   double entry = is_long
                ? signal_low + (signal_high - signal_low) * LPFS_SIGNAL_ZONE
                : signal_high - (signal_high - signal_low) * LPFS_SIGNAL_ZONE;
   double stop = is_long ? structure_low : structure_high;
   double risk = is_long ? entry - stop : stop - entry;
   if(risk <= 0.0)
      return;
   double target = is_long ? entry + risk * LPFS_TARGET_R : entry - risk * LPFS_TARGET_R;

   double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0 || bid > ask)
      return;

   if(!DynamicSpreadGatePass(ask - bid, risk))
   {
      Log(StringFormat("LPFS spread gate WAITING %s %s spread=%.8f risk=%.8f max_fraction=%.2f",
                       symbol, TfLabel(timeframe), ask - bid, risk, LPFS_MAX_SPREAD_RISK_FRACTION));
      return;
   }

   if(is_long && entry >= ask)
      return;
   if(!is_long && entry <= bid)
      return;
   if(!BrokerDistancePass(symbol, is_long, entry, stop, target, bid, ask))
      return;

   string comment = BuildOrderComment(symbol, timeframe, signal);
   if(HasDuplicateStrategyOrder(symbol, comment))
      return;

   double risk_pct = RiskPctForTimeframe(timeframe);
   double volume = VolumeForRisk(symbol, is_long, entry, stop, risk_pct);
   if(volume <= 0.0)
      return;
   double actual_risk_pct = ActualRiskPctForVolume(symbol, is_long, entry, stop, volume);
   if(actual_risk_pct <= 0.0)
      return;
   if(!ExposureGatePass(symbol, actual_risk_pct))
      return;

   datetime expiration = rates[signal.fs_signal_index].time + PeriodSeconds(timeframe) * (LPFS_MAX_ENTRY_WAIT_BARS + 1);
   trade.SetExpertMagicNumber(InpMagicNumber);
   bool sent = false;
   if(is_long)
      sent = trade.BuyLimit(volume, entry, symbol, stop, target, ORDER_TIME_SPECIFIED, expiration, comment);
   else
      sent = trade.SellLimit(volume, entry, symbol, stop, target, ORDER_TIME_SPECIFIED, expiration, comment);

   if(sent)
      Log(StringFormat("LPFS tester order placed %s %s %s volume=%.2f entry=%.5f stop=%.5f target=%.5f risk_pct=%.2f",
                       symbol, TfLabel(timeframe), is_long ? "LONG" : "SHORT", volume, entry, stop, target, actual_risk_pct));
   else
      Log(StringFormat("LPFS tester order failed %s %s retcode=%d", symbol, TfLabel(timeframe), trade.ResultRetcode()));
}

bool DynamicSpreadGatePass(const double spread_price, const double risk_price)
{
   if(spread_price < 0.0 || risk_price <= 0.0)
      return false;
   return (spread_price / risk_price) <= LPFS_MAX_SPREAD_RISK_FRACTION;
}

bool BrokerDistancePass(const string symbol, const bool is_long, const double entry, const double stop, const double target, const double bid, const double ask)
{
   double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
   int stops = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
   int freeze = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double min_distance = MathMax(stops, freeze) * point;
   if(min_distance <= 0.0)
      return true;
   double pending_distance = is_long ? ask - entry : entry - bid;
   if(pending_distance < min_distance)
      return false;
   if(MathAbs(entry - stop) < min_distance)
      return false;
   if(MathAbs(target - entry) < min_distance)
      return false;
   return true;
}

double VolumeForRisk(const string symbol, const bool is_long, const double entry, const double stop, const double risk_pct)
{
   ENUM_ORDER_TYPE type = is_long ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double profit = 0.0;
   if(!OrderCalcProfit(type, symbol, 1.0, entry, stop, profit))
      return 0.0;
   double risk_per_lot = MathAbs(profit);
   if(risk_per_lot <= 0.0)
      return 0.0;

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double target_money = equity * risk_pct / 100.0;
   double raw_volume = target_money / risk_per_lot;
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double min_volume = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double max_volume = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0.0 || min_volume <= 0.0 || max_volume <= 0.0)
      return 0.0;

   double volume = MathFloor(raw_volume / step) * step;
   volume = MathMin(volume, max_volume);
   if(volume < min_volume)
      return 0.0;
   return NormalizeDouble(volume, 2);
}

double ActualRiskPctForVolume(const string symbol, const bool is_long, const double entry, const double stop, const double volume)
{
   ENUM_ORDER_TYPE type = is_long ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   double profit = 0.0;
   if(!OrderCalcProfit(type, symbol, volume, entry, stop, profit))
      return 0.0;
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity <= 0.0)
      return 0.0;
   return MathAbs(profit) / equity * 100.0;
}

bool ExposureGatePass(const string symbol, const double new_risk_pct)
{
   int total_count = 0;
   int same_symbol_count = 0;
   double open_risk_pct = 0.0;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if(OrderGetInteger(ORDER_MAGIC) != InpMagicNumber)
         continue;
      if(StringFind(OrderGetString(ORDER_COMMENT), InpCommentPrefix) != 0)
         continue;
      total_count++;
      if(OrderGetString(ORDER_SYMBOL) == symbol)
         same_symbol_count++;
      open_risk_pct += OrderRiskPct(ticket);
   }

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagicNumber)
         continue;
      if(StringFind(PositionGetString(POSITION_COMMENT), InpCommentPrefix) != 0)
         continue;
      total_count++;
      if(PositionGetString(POSITION_SYMBOL) == symbol)
         same_symbol_count++;
      open_risk_pct += PositionRiskPct(ticket);
   }

   if(total_count >= ActiveMaxConcurrentTrades())
   {
      Log(StringFormat("LPFS exposure gate blocked: total_count=%d max=%d", total_count, ActiveMaxConcurrentTrades()));
      return false;
   }
   if(same_symbol_count >= ActiveMaxSameSymbolTrades())
   {
      Log(StringFormat("LPFS exposure gate blocked: symbol=%s same_symbol_count=%d max=%d",
                       symbol, same_symbol_count, ActiveMaxSameSymbolTrades()));
      return false;
   }
   if(open_risk_pct + new_risk_pct > ActiveMaxOpenRiskPct() + 0.0000001)
   {
      Log(StringFormat("LPFS exposure gate blocked: open_risk=%.4f new=%.4f max=%.4f",
                       open_risk_pct, new_risk_pct, ActiveMaxOpenRiskPct()));
      return false;
   }
   return true;
}

double OrderRiskPct(const ulong ticket)
{
   string symbol = OrderGetString(ORDER_SYMBOL);
   double entry = OrderGetDouble(ORDER_PRICE_OPEN);
   double stop = OrderGetDouble(ORDER_SL);
   double volume = OrderGetDouble(ORDER_VOLUME_CURRENT);
   if(stop <= 0.0 || volume <= 0.0)
      return 0.0;

   ENUM_ORDER_TYPE order_type = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
   bool is_buy_side = order_type == ORDER_TYPE_BUY || order_type == ORDER_TYPE_BUY_LIMIT
                   || order_type == ORDER_TYPE_BUY_STOP || order_type == ORDER_TYPE_BUY_STOP_LIMIT;
   return ActualRiskPctForVolume(symbol, is_buy_side, entry, stop, volume);
}

double PositionRiskPct(const ulong ticket)
{
   string symbol = PositionGetString(POSITION_SYMBOL);
   double entry = PositionGetDouble(POSITION_PRICE_OPEN);
   double stop = PositionGetDouble(POSITION_SL);
   double volume = PositionGetDouble(POSITION_VOLUME);
   if(stop <= 0.0 || volume <= 0.0)
      return 0.0;

   bool is_buy_side = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY;
   return ActualRiskPctForVolume(symbol, is_buy_side, entry, stop, volume);
}

bool HasDuplicateStrategyOrder(const string symbol, const string comment)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0)
         continue;
      if(OrderGetString(ORDER_SYMBOL) == symbol
         && OrderGetInteger(ORDER_MAGIC) == InpMagicNumber
         && OrderGetString(ORDER_COMMENT) == comment)
         return true;
   }
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == symbol
         && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber
         && StringFind(PositionGetString(POSITION_COMMENT), InpCommentPrefix) == 0)
         return true;
   }
   return false;
}

int SelectMatchingWindow(LpfsTrapWindow &windows[], const LpfsForceStrikePattern &pattern, const double signal_close)
{
   int selected = -1;
   for(int i = 0; i < ArraySize(windows); i++)
   {
      if(windows[i].signal_side != pattern.side)
         continue;
      if(LPFS_REQUIRE_LP_PIVOT_BEFORE_FS_MOTHER && windows[i].event.pivot_index >= pattern.mother_index)
         continue;
      int bars_from_break = pattern.signal_index - windows[i].event.break_index + 1;
      if(bars_from_break < 1 || bars_from_break > LPFS_MAX_BARS_FROM_LP_BREAK)
         continue;
      if(pattern.side == 1 && signal_close < windows[i].event.price)
         continue;
      if(pattern.side == -1 && signal_close > windows[i].event.price)
         continue;

      if(selected < 0)
      {
         selected = i;
         continue;
      }
      if(pattern.side == 1)
      {
         if(windows[i].event.price < windows[selected].event.price
            || (windows[i].event.price == windows[selected].event.price && windows[i].event.break_index > windows[selected].event.break_index))
            selected = i;
      }
      else
      {
         if(windows[i].event.price > windows[selected].event.price
            || (windows[i].event.price == windows[selected].event.price && windows[i].event.break_index > windows[selected].event.break_index))
            selected = i;
      }
   }
   return selected;
}

void AddTrapWindows(LpfsBreakEvent &events[], LpfsTrapWindow &windows[])
{
   int support_index = -1;
   int resistance_index = -1;
   for(int i = 0; i < ArraySize(events); i++)
   {
      if(events[i].side == -1)
      {
         if(support_index < 0 || events[i].price < events[support_index].price)
            support_index = i;
      }
      if(events[i].side == 1)
      {
         if(resistance_index < 0 || events[i].price > events[resistance_index].price)
            resistance_index = i;
      }
   }
   if(support_index >= 0)
   {
      LpfsTrapWindow window;
      window.signal_side = 1;
      window.scenario = "force_bottom";
      window.event = events[support_index];
      PushTrapWindow(windows, window);
   }
   if(resistance_index >= 0)
   {
      LpfsTrapWindow window;
      window.signal_side = -1;
      window.scenario = "force_top";
      window.event = events[resistance_index];
      PushTrapWindow(windows, window);
   }
}

void PruneTrapWindows(LpfsTrapWindow &windows[], const int current_index)
{
   LpfsTrapWindow kept[];
   for(int i = 0; i < ArraySize(windows); i++)
   {
      if(current_index - windows[i].event.break_index + 1 <= LPFS_MAX_BARS_FROM_LP_BREAK)
         PushTrapWindow(kept, windows[i]);
   }
   ReplaceTrapWindows(windows, kept);
}

void RemoveTrapWindow(LpfsTrapWindow &windows[], const int index)
{
   LpfsTrapWindow kept[];
   for(int i = 0; i < ArraySize(windows); i++)
   {
      if(i != index)
         PushTrapWindow(kept, windows[i]);
   }
   ReplaceTrapWindows(windows, kept);
}

void ReplaceTrapWindows(LpfsTrapWindow &target[], LpfsTrapWindow &source[])
{
   ArrayResize(target, 0);
   for(int i = 0; i < ArraySize(source); i++)
      PushTrapWindow(target, source[i]);
}

void PushLevel(LpfsLevel &items[], const LpfsLevel &item)
{
   int size = ArraySize(items);
   ArrayResize(items, size + 1);
   items[size] = item;
}

void PushBreak(LpfsBreakEvent &items[], const LpfsBreakEvent &item)
{
   int size = ArraySize(items);
   ArrayResize(items, size + 1);
   items[size] = item;
}

void PushTrapWindow(LpfsTrapWindow &items[], const LpfsTrapWindow &item)
{
   int size = ArraySize(items);
   ArrayResize(items, size + 1);
   items[size] = item;
}

bool IsStrictPivotHigh(MqlRates &rates[], const int pivot, const int strength)
{
   for(int distance = 1; distance <= strength; distance++)
   {
      if(rates[pivot].high <= rates[pivot - distance].high || rates[pivot].high <= rates[pivot + distance].high)
         return false;
   }
   return true;
}

bool IsStrictPivotLow(MqlRates &rates[], const int pivot, const int strength)
{
   for(int distance = 1; distance <= strength; distance++)
   {
      if(rates[pivot].low >= rates[pivot - distance].low || rates[pivot].low >= rates[pivot + distance].low)
         return false;
   }
   return true;
}

bool InsideMother(const MqlRates &bar, const double mother_high, const double mother_low)
{
   return bar.high <= mother_high && bar.low >= mother_low;
}

double CloseLocation(const MqlRates &bar)
{
   double range = bar.high - bar.low;
   if(range <= 0.0)
      return 0.5;
   return (bar.close - bar.low) / range;
}

bool IsBullishSignalBar(const MqlRates &bar)
{
   return bar.high > bar.low && CloseLocation(bar) >= (2.0 / 3.0);
}

bool IsBearishSignalBar(const MqlRates &bar)
{
   return bar.high > bar.low && CloseLocation(bar) <= (1.0 / 3.0);
}

int LookbackDaysForTimeframe(const ENUM_TIMEFRAMES timeframe)
{
   if(timeframe == PERIOD_H8)
      return 60;
   if(timeframe == PERIOD_H12)
      return 180;
   if(timeframe == PERIOD_H4 || timeframe == PERIOD_D1)
      return 365;
   if(timeframe == PERIOD_W1)
      return 1460;
   return 365;
}

double RiskPctForTimeframe(const ENUM_TIMEFRAMES timeframe)
{
   LpfsRiskSchedule schedule;
   GetRiskSchedule(schedule);
   if(timeframe == PERIOD_H4 || timeframe == PERIOD_H8)
      return schedule.h4h8;
   if(timeframe == PERIOD_H12 || timeframe == PERIOD_D1)
      return schedule.h12d1;
   if(timeframe == PERIOD_W1)
      return schedule.w1;
   return 0.0;
}

double ActiveMaxOpenRiskPct()
{
   LpfsRiskSchedule schedule;
   GetRiskSchedule(schedule);
   if(InpMaxOpenRiskPct > 0.0)
      return InpMaxOpenRiskPct;
   return schedule.max_open_risk_pct;
}

int ActiveMaxConcurrentTrades()
{
   LpfsRiskSchedule schedule;
   GetRiskSchedule(schedule);
   if(InpMaxConcurrentTrades > 0)
      return InpMaxConcurrentTrades;
   return schedule.max_concurrent_trades;
}

int ActiveMaxSameSymbolTrades()
{
   LpfsRiskSchedule schedule;
   GetRiskSchedule(schedule);
   if(InpMaxSameSymbolTrades > 0)
      return InpMaxSameSymbolTrades;
   return schedule.max_same_symbol_trades;
}

void GetRiskSchedule(LpfsRiskSchedule &schedule)
{
   if(InpRiskProfile == LPFS_RISK_CONSERVATIVE)
   {
      schedule.h4h8 = 0.10;
      schedule.h12d1 = 0.15;
      schedule.w1 = 0.30;
      schedule.max_open_risk_pct = 3.0;
      schedule.max_concurrent_trades = 8;
      schedule.max_same_symbol_trades = 2;
      return;
   }
   if(InpRiskProfile == LPFS_RISK_GROWTH)
   {
      schedule.h4h8 = 0.25;
      schedule.h12d1 = 0.30;
      schedule.w1 = 0.75;
      schedule.max_open_risk_pct = 9.0;
      schedule.max_concurrent_trades = 17;
      schedule.max_same_symbol_trades = 4;
      return;
   }
   schedule.h4h8 = 0.20;
   schedule.h12d1 = 0.30;
   schedule.w1 = 0.75;
   schedule.max_open_risk_pct = 6.0;
   schedule.max_concurrent_trades = 17;
   schedule.max_same_symbol_trades = 4;
}

string RiskProfileLabel()
{
   if(InpRiskProfile == LPFS_RISK_CONSERVATIVE)
      return "Conservative";
   if(InpRiskProfile == LPFS_RISK_GROWTH)
      return "Growth";
   return "Standard";
}

string TfLabel(const ENUM_TIMEFRAMES timeframe)
{
   if(timeframe == PERIOD_H4) return "H4";
   if(timeframe == PERIOD_H8) return "H8";
   if(timeframe == PERIOD_H12) return "H12";
   if(timeframe == PERIOD_D1) return "D1";
   if(timeframe == PERIOD_W1) return "W1";
   return EnumToString(timeframe);
}

string BuildOrderComment(const string symbol, const ENUM_TIMEFRAMES timeframe, const LpfsSignal &signal)
{
   string side = signal.side == 1 ? "L" : "S";
   string raw = StringFormat("%s %s %s %d", InpCommentPrefix, TfLabel(timeframe), side, signal.fs_signal_index);
   return StringSubstr(raw, 0, 31);
}

string ApprovedSymbolList()
{
   string value = "";
   for(int i = 0; i < ArraySize(LPFS_SYMBOLS); i++)
   {
      if(i > 0)
         value += ",";
      value += LPFS_SYMBOLS[i];
   }
   return value;
}

void PrintBacktestDisclosure()
{
   LpfsRiskSchedule schedule;
   GetRiskSchedule(schedule);
   Log("LPFS EA Backtest Configuration");
   Log(StringFormat("Risk Profile: %s", RiskProfileLabel()));
   Log(StringFormat("Effective Risk Schedule: H4/H8 %.2f%%, H12/D1 %.2f%%, W1 %.2f%%",
                    schedule.h4h8, schedule.h12d1, schedule.w1));
   Log(StringFormat("Max Single Trade Risk: %.2f%%", MathMax(MathMax(schedule.h4h8, schedule.h12d1), schedule.w1)));
   Log(StringFormat("Max Open Strategy Risk active/profile: %.2f%% / %.2f%%", ActiveMaxOpenRiskPct(), schedule.max_open_risk_pct));
   Log(StringFormat("Max Concurrent Trades active/profile: %d / %d", ActiveMaxConcurrentTrades(), schedule.max_concurrent_trades));
   Log(StringFormat("Max Same Symbol Trades active/profile: %d / %d", ActiveMaxSameSymbolTrades(), schedule.max_same_symbol_trades));
   Log(StringFormat("MagicNumber: %d CommentPrefix: %s", InpMagicNumber, InpCommentPrefix));
   Log(StringFormat("Spread Gate: internal dynamic spread/risk protection enabled at %.2f", LPFS_MAX_SPREAD_RISK_FRACTION));
   Log("Symbols: " + ApprovedSymbolList());
   Log("Timeframes: H4,H8,H12,D1,W1");
   Log("Mode: TesterOnly=true; AllowLiveTrading=false for v1 unless explicitly changed by a later approved plan.");
}

void Log(const string message)
{
   if(InpEnablePrintLog)
      Print(message);
}

// Attach one copy to the EURUSD M1 chart and one to the EURUSD M5 chart.
// Each copy exports a fresh screenshot into MQL5/Files.
#property strict
input int CaptureEverySeconds = 5;
input int ImageWidth = 1600;
input int ImageHeight = 900;

int OnInit()
{
   EventSetTimer(MathMax(1, CaptureEverySeconds));
   CaptureChart();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
}

void OnTimer()
{
   CaptureChart();
}

void CaptureChart()
{
   string tf = EnumToString((ENUM_TIMEFRAMES)Period());
   StringReplace(tf, "PERIOD_", "");
   string filename = _Symbol + "_" + tf + ".png";
   ResetLastError();
   if(!ChartScreenShot(0, filename, ImageWidth, ImageHeight, ALIGN_RIGHT))
      Print("ChartScreenShot failed. Error=", GetLastError(), " file=", filename);
}

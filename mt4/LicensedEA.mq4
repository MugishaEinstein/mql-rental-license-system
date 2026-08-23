#property strict
#property version   "1.00"

#include "LicenseClient.mqh"

input string ApiUrl="https://license.example.com/v1/validate";
input string Product="my-ea";
input string LicenseKey="PASTE_CUSTOMER_LICENSE_KEY";
input int    RequestTimeoutMs=5000;
input int    RecheckMinutes=30;
input string MachineId="";

bool g_license_ok=false;

int OnInit()
  {
   if(StringLen(LicenseKey)<10)
     {
      Print("A valid rental license key is required.");
      return(INIT_FAILED);
     }

   g_license_ok=CheckLicenseMT4(ApiUrl,LicenseKey,Product,RequestTimeoutMs,MachineId);
   if(!g_license_ok)
     {
      Print("EA stopped because the license is not valid.");
      return(INIT_FAILED);
     }

   EventSetTimer(MathMax(1,RecheckMinutes)*60);
   Print("License accepted; EA initialized.");
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
  }

void OnTimer()
  {
   g_license_ok=CheckLicenseMT4(ApiUrl,LicenseKey,Product,RequestTimeoutMs,MachineId);
   if(!g_license_ok)
     {
      Print("License validation failed; removing EA from the chart.");
      ExpertRemove();
     }
  }

void OnTick()
  {
   if(!g_license_ok)
      return;

   // Insert the EA's trading strategy here.
   // The licensing check is deliberately kept separate from trading logic.
  }

#property strict

// Licensing client for MT4. Add the API URL to MT4:
// Tools -> Options -> Expert Advisors -> Allow WebRequest for listed URL.

bool LicenseJsonValid(const string json)
  {
   string compact=json;
   StringReplace(compact," ","");
   StringReplace(compact,"\r","");
   StringReplace(compact,"\n","");
   return(StringFind(compact,"\"valid\":true")>=0);
  }

string LicenseJsonReason(const string json)
  {
   string compact=json;
   StringReplace(compact," ","");
   StringReplace(compact,"\r","");
   StringReplace(compact,"\n","");
   string marker="\"reason\":\"";
   int start=StringFind(compact,marker);
   if(start<0) return("unknown");
   start+=StringLen(marker);
   int finish=StringFind(compact,"\"",start);
   if(finish<0) return("unknown");
   return(StringSubstr(compact,start,finish-start));
  }

string LicenseJsonEscape(string value)
  {
   StringReplace(value,"\\","\\\\");
   StringReplace(value,"\"","\\\"");
   StringReplace(value,"\r","\\r");
   StringReplace(value,"\n","\\n");
   return(value);
  }

bool CheckLicenseMT4(const string api_url,
                     const string license_key,
                     const string product,
                     const int timeout_ms,
                     const string machine_id="")
  {
   string login=IntegerToString(AccountNumber());
   string broker=AccountServer();
   string body="{\"license_key\":\""+LicenseJsonEscape(license_key)+
              "\",\"product\":\""+LicenseJsonEscape(product)+
              "\",\"platform\":\"mt4\""+
              ",\"account_login\":\""+LicenseJsonEscape(login)+
              "\",\"broker_server\":\""+LicenseJsonEscape(broker)+"\"";
   if(StringLen(machine_id)>0)
      body+=",\"machine_id\":\""+LicenseJsonEscape(machine_id)+"\"";
   body+="}";

   char payload[];
   int payload_size=StringToCharArray(body,payload,0,WHOLE_ARRAY,CP_UTF8)-1;
   char response[];
   string response_headers="";
   string headers="Content-Type: application/json\r\nAccept: application/json\r\n";
   ResetLastError();
   int http_code=WebRequest("POST",api_url,headers,timeout_ms,payload,payload_size,response,response_headers);
   if(http_code!=200)
     {
      PrintFormat("License request failed. HTTP=%d, error=%d",http_code,GetLastError());
      return(false);
     }

   string json=CharArrayToString(response,0,-1,CP_UTF8);
   bool valid=LicenseJsonValid(json);
   if(!valid)
      PrintFormat("License rejected: %s",LicenseJsonReason(json));
   return(valid);
  }

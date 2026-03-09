# Power Automate + SharePoint Integration

This guide describes the two flows needed to connect the Lead Enrichment API with Power Automate and SharePoint.

## Prerequisites

- API server must be running (public URL or on-premises data gateway)
- `ENRICHMENT_API_KEY` must be set in the `.env` file
- Two SharePoint folders must exist:
  - `lead-enrichment-input` — users upload Excel files here
  - `lead-enrichment-output` — enriched files are written here

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Power Automate                        │
│                                                         │
│  FLOW 1: Trigger                                        │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐  │
│  │ SharePoint  │───▶│ POST /api/   │───▶│ Passes     │  │
│  │ file        │    │ enrich       │    │ Flow 2 URL │  │
│  │ uploaded    │    │ (file +      │    │ as callback│  │
│  │             │    │ callback)    │    │            │  │
│  └─────────────┘    └──────────────┘    └────────────┘  │
│                                                         │
│  FLOW 2: Callback (triggered when processing completes) │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐  │
│  │ HTTP POST   │───▶│ Download     │───▶│ Teams      │  │
│  │ received    │    │ file +       │    │ notify     │  │
│  │ (from API)  │    │ upload to    │    │ user       │  │
│  └─────────────┘    │ SharePoint   │    └────────────┘  │
│                     └──────────────┘                    │
└─────────────────────────────────────────────────────────┘
```

---

## Flow 1: SharePoint → Send to API

### Step 1: Trigger
- **Trigger**: "When a file is created in a folder" (SharePoint)
- **Site Address**: Your company SharePoint site
- **Folder Id**: `/lead-enrichment-input`

### Step 2: Get file content
- **Action**: "Get file content" (SharePoint)
- **Site Address**: Same site
- **File Identifier**: `triggerOutputs()?['body/{Identifier}']`

### Step 3: HTTP — Send file to API
- **Action**: "HTTP" (Premium connector)
- **Method**: POST
- **URI**: `https://YOUR-API-URL/api/enrich`
- **Headers**:
  ```
  X-API-Key: YOUR_ENRICHMENT_API_KEY
  ```
- **Body**: Send as form-data:
  - `file`: File content from SharePoint (binary)
  - `callback_url`: Flow 2's HTTP trigger URL
  - `user_email`: Uploader's email for Teams notification

> **Sending HTTP multipart/form-data in Power Automate:**
>
> Configure the body as follows:
> ```json
> {
>   "$content-type": "multipart/form-data",
>   "$multipart": [
>     {
>       "headers": {
>         "Content-Disposition": "form-data; name=\"file\"; filename=\"@{triggerOutputs()?['body/{FilenameWithExtension}']}\""
>       },
>       "body": @{body('Get_file_content')}
>     },
>     {
>       "headers": {
>         "Content-Disposition": "form-data; name=\"callback_url\""
>       },
>       "body": "FLOW_2_HTTP_TRIGGER_URL_HERE"
>     },
>     {
>       "headers": {
>         "Content-Disposition": "form-data; name=\"user_email\""
>       },
>       "body": "@{triggerOutputs()?['body/{Author}/Email']}"
>     }
>   ]
> }
> ```

### Step 4 (Optional): Parse response
- **Action**: "Parse JSON"
- **Content**: HTTP response body
- **Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "run_id": { "type": "string" },
      "status": { "type": "string" },
      "message": { "type": "string" }
    }
  }
  ```

---

## Flow 2: Callback → SharePoint + Teams Notification

### Step 1: Trigger
- **Trigger**: "When an HTTP request is received" (Premium)
- **Method**: POST
- **Request Body JSON Schema**:
  ```json
  {
    "type": "object",
    "properties": {
      "run_id": { "type": "string" },
      "status": { "type": "string" },
      "input_file": { "type": "string" },
      "total_rows": { "type": "integer" },
      "error_message": { "type": "string" },
      "download_url": { "type": "string" },
      "user_email": { "type": "string" },
      "started_at": { "type": "string" },
      "completed_at": { "type": "string" },
      "lusha": {
        "type": "object",
        "properties": {
          "complete": { "type": "integer" },
          "error": { "type": "integer" },
          "pending": { "type": "integer" }
        }
      },
      "apollo": {
        "type": "object",
        "properties": {
          "complete": { "type": "integer" },
          "error": { "type": "integer" },
          "pending": { "type": "integer" },
          "awaiting_webhook": { "type": "integer" },
          "timeout": { "type": "integer" }
        }
      }
    }
  }
  ```

### Step 2: Condition — Success or failure?
- **Condition**: `triggerBody()?['status']` is equal to `completed`

### If Yes (Success):

#### Step 2a: HTTP — Download enriched file
- **Method**: GET
- **URI**: `https://YOUR-API-URL@{triggerBody()?['download_url']}`
- **Headers**:
  ```
  X-API-Key: YOUR_ENRICHMENT_API_KEY
  ```

#### Step 2b: Create file (SharePoint)
- **Action**: "Create file" (SharePoint)
- **Site Address**: Your company SharePoint site
- **Folder Path**: `/lead-enrichment-output`
- **File Name**: `concat('enriched_', triggerBody()?['input_file'])`
- **File Content**: HTTP response body (binary)

#### Step 2c: Teams notification — Success
- **Action**: "Post message in a chat or channel" (Teams)
- **Post as**: Flow bot
- **Post in**: Chat with Flow bot
- **Recipient**: `triggerBody()?['user_email']`
- **Message**:
  ```
  Lead Enrichment abgeschlossen!
  Datei: @{triggerBody()?['input_file']}
  Gesamtzeilen: @{triggerBody()?['total_rows']}
  Ergebnis liegt im Ordner: lead-enrichment-output
  ```

### If No (Error):

#### Step 2d: Teams notification — Error
- **Action**: "Post message in a chat or channel" (Teams)
- **Post as**: Flow bot
- **Post in**: Chat with Flow bot
- **Recipient**: `triggerBody()?['user_email']`
- **Message**:
  ```
  Lead Enrichment fehlgeschlagen!
  Datei: @{triggerBody()?['input_file']}
  Fehler: @{triggerBody()?['error_message']}
  Bitte die Datei ueberpruefen und erneut versuchen.
  ```

---

## Setup Order

1. **Create Flow 2 first** — the "When an HTTP request is received" trigger generates a URL
2. Copy Flow 2's trigger URL
3. **Create Flow 1** — paste Flow 2's URL into the `callback_url` field
4. Test: Upload a test Excel file to the SharePoint input folder

## Security Notes

- Choose a strong, random `ENRICHMENT_API_KEY` (at least 32 characters)
- Store the API key as an Environment Variable in Power Automate flows
- Flow 2's HTTP trigger URL is unguessable, so no additional auth is needed
- Ensure the API server is accessible over HTTPS

## Troubleshooting

| Issue | Solution |
|-------|----------|
| 401 Unauthorized | Check the `X-API-Key` header and the `ENRICHMENT_API_KEY` value in `.env` |
| Callback not arriving | Ensure Flow 2 is active and the URL is correct |
| Empty file received | Check that the SharePoint "Get file content" step is fetching the correct file |
| Teams message not sent | Check that the Teams connector is properly connected and the channel exists |

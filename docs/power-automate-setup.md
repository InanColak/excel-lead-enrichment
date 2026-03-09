# Power Automate + SharePoint Entegrasyonu

Bu rehber, Lead Enrichment API'yi Power Automate ile SharePoint'e bağlamak için gereken iki flow'u açıklar.

## Gereksinimler

- API sunucusunun çalışıyor olması (public URL veya on-premises data gateway)
- `.env` dosyasında `ENRICHMENT_API_KEY` tanımlı olmalı
- SharePoint'te iki klasör oluşturulmuş olmalı:
  - `Lead Enrichment/Input` — kullanıcılar Excel dosyalarını buraya yükler
  - `Lead Enrichment/Output` — zenginleştirilmiş dosyalar buraya yazılır

## Mimari

```
┌─────────────────────────────────────────────────────────┐
│                    Power Automate                        │
│                                                         │
│  FLOW 1: Tetikleme                                      │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐  │
│  │ SharePoint  │───▶│ POST /api/   │───▶│ Callback   │  │
│  │ Input'a     │    │ enrich       │    │ URL olarak │  │
│  │ dosya       │    │ (dosya +     │    │ Flow 2'nin │  │
│  │ yüklendi    │    │ callback)    │    │ URL'i      │  │
│  └─────────────┘    └──────────────┘    └────────────┘  │
│                                                         │
│  FLOW 2: Callback (İşlem bitince tetiklenir)            │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────┐  │
│  │ HTTP POST   │───▶│ Dosyayı      │───▶│ Teams      │  │
│  │ geldi       │    │ indir +      │    │ bildirimi  │  │
│  │ (API'den)   │    │ SharePoint'e │    │ gönder     │  │
│  └─────────────┘    │ yükle        │    └────────────┘  │
│                     └──────────────┘                    │
└─────────────────────────────────────────────────────────┘
```

---

## Flow 1: SharePoint → API'ye Gönder

### Adım 1: Trigger
- **Trigger**: "When a file is created in a folder" (SharePoint)
- **Site Address**: Şirket SharePoint sitesi
- **Folder Id**: `/Lead Enrichment/Input`

### Adım 2: Get file content
- **Action**: "Get file content" (SharePoint)
- **Site Address**: Aynı site
- **File Identifier**: `triggerOutputs()?['body/{Identifier}']`

### Adım 3: HTTP — API'ye dosya gönder
- **Action**: "HTTP" (Premium connector)
- **Method**: POST
- **URI**: `https://YOUR-API-URL/api/enrich`
- **Headers**:
  ```
  X-API-Key: YOUR_ENRICHMENT_API_KEY
  ```
- **Body**: Form-data olarak gönder:
  - `file`: SharePoint'ten alınan dosya içeriği (binary)
  - `callback_url`: Flow 2'nin HTTP trigger URL'i

> **Power Automate'te HTTP multipart/form-data gönderme:**
>
> Body kısmını şu şekilde ayarlayın:
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
>       "body": "FLOW_2_HTTP_TRIGGER_URL_BURAYA"
>     }
>   ]
> }
> ```

### Adım 4 (Opsiyonel): Parse response
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

## Flow 2: Callback → SharePoint + Teams Bildirimi

### Adım 1: Trigger
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

### Adım 2: Condition — Başarılı mı?
- **Condition**: `triggerBody()?['status']` is equal to `completed`

### ✅ If Yes (Başarılı):

#### Adım 2a: HTTP — Zenginleştirilmiş dosyayı indir
- **Method**: GET
- **URI**: `https://YOUR-API-URL@{triggerBody()?['download_url']}`
- **Headers**:
  ```
  X-API-Key: YOUR_ENRICHMENT_API_KEY
  ```

#### Adım 2b: Create file (SharePoint)
- **Action**: "Create file" (SharePoint)
- **Site Address**: Şirket SharePoint sitesi
- **Folder Path**: `/Lead Enrichment/Output`
- **File Name**: `enriched_@{triggerBody()?['input_file']}`
- **File Content**: HTTP response body (binary)

#### Adım 2c: Teams bildirimi — Başarı
- **Action**: "Post message in a chat or channel" (Teams)
- **Team**: İlgili ekip
- **Channel**: İlgili kanal
- **Message**:
  ```
  ✅ Lead Enrichment Tamamlandı!

  📄 Dosya: @{triggerBody()?['input_file']}
  📊 Toplam satır: @{triggerBody()?['total_rows']}

  Lusha: @{triggerBody()?['lusha']?['complete']} başarılı, @{triggerBody()?['lusha']?['error']} hata
  Apollo: @{triggerBody()?['apollo']?['complete']} başarılı, @{triggerBody()?['apollo']?['error']} hata, @{triggerBody()?['apollo']?['timeout']} timeout

  📁 Sonuç: Lead Enrichment/Output/enriched_@{triggerBody()?['input_file']}
  ```

### ❌ If No (Hata):

#### Adım 2d: Teams bildirimi — Hata
- **Action**: "Post message in a chat or channel" (Teams)
- **Team**: İlgili ekip
- **Channel**: İlgili kanal
- **Message**:
  ```
  ❌ Lead Enrichment Başarısız!

  📄 Dosya: @{triggerBody()?['input_file']}
  🚨 Hata: @{triggerBody()?['error_message']}

  Lütfen dosyayı kontrol edip tekrar deneyin.
  ```

---

## Kurulum Sırası

1. **Önce Flow 2'yi oluşturun** — "When an HTTP request is received" trigger'ı bir URL üretecek
2. Flow 2'nin trigger URL'ini kopyalayın
3. **Flow 1'i oluşturun** — `callback_url` alanına Flow 2'nin URL'ini yapıştırın
4. Test edin: SharePoint Input klasörüne bir test Excel dosyası yükleyin

## Güvenlik Notları

- `ENRICHMENT_API_KEY` değerini güçlü ve rastgele seçin (en az 32 karakter)
- Power Automate flow'larında API key'i bir Environment Variable olarak saklayın
- Flow 2'nin HTTP trigger URL'i tahmin edilemez olduğu için ek auth gerekmez
- API sunucusunun HTTPS üzerinden erişilebilir olduğundan emin olun

## Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| 401 Unauthorized | `X-API-Key` header'ını ve `.env` dosyasındaki `ENRICHMENT_API_KEY` değerini kontrol edin |
| Callback gelmiyor | Flow 2'nin aktif olduğundan ve URL'in doğru olduğundan emin olun |
| Dosya boş geliyor | SharePoint "Get file content" adımının doğru dosyayı aldığını kontrol edin |
| Teams mesajı gitmiyor | Teams connector'ının doğru bağlandığını ve kanalın mevcut olduğunu kontrol edin |

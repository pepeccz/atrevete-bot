# External Services Setup Guide

## Introduction

This guide walks you through setting up all external service accounts required for the Atrévete Bot application. These services are essential for the bot's core functionality:

- **Google Calendar API** - Manage stylist appointments and availability
- **Stripe** - Process payments and handle refunds
- **Chatwoot** - Send and receive WhatsApp messages
- **Anthropic Claude API** - Power natural language conversations

**Total estimated time:** ~60 minutes

**Prerequisites:**
- Access to a Google Workspace account (for Calendar API)
- Business email address (for Stripe)
- Meta Business Manager account (for WhatsApp via Chatwoot)
- Credit card for Anthropic billing setup

**Security Notice:** All API keys and credentials obtained in this guide are sensitive. Never commit them to version control. Use the provided `.env.example` template and store actual credentials in a secure password manager.

---

## 1. Google Calendar API Setup

**Estimated time:** 15 minutes

### 1.1 Create Google Cloud Project

1. Navigate to [Google Cloud Console](https://console.cloud.google.com)
2. Click the project dropdown at the top of the page
3. Click "New Project"
4. Enter project name: `atrevete-bot-production`
5. Click "Create"
6. Wait for project creation to complete (you'll see a notification)

### 1.2 Enable Google Calendar API

1. In your new project, navigate to **APIs & Services → Library**
2. Search for "Google Calendar API"
3. Click on "Google Calendar API" in the results
4. Click "Enable"
5. Wait for API to be enabled (~30 seconds)

### 1.3 Create Service Account

1. Navigate to **IAM & Admin → Service Accounts**
2. Click "Create Service Account" at the top
3. Fill in details:
   - **Service account name:** `atrevete-bot-calendar-service`
   - **Service account ID:** (auto-generated, leave as is)
   - **Description:** `Calendar access for Atrévete Bot`
4. Click "Create and Continue"
5. **Grant this service account access to project:**
   - Select role: "Service Account User"
   - Click "Continue"
6. Skip "Grant users access to this service account" (click "Done")

### 1.4 Create and Download JSON Key

1. In the Service Accounts list, click on your newly created service account
2. Navigate to the "Keys" tab
3. Click "Add Key" → "Create new key"
4. Select "JSON" format
5. Click "Create"
6. **IMPORTANT:** The JSON key file will download automatically. Store it securely:
   - Move it to a secure location (e.g., `~/.credentials/atrevete-bot/`)
   - **NEVER** commit this file to git
   - Note the full file path for later use in `.env`

### 1.5 Configure Domain-Wide Delegation

1. In the service account details, copy the **service account email** (format: `atrevete-bot-calendar-service@PROJECT_ID.iam.gserviceaccount.com`)
2. Navigate to each of your 5 stylist Google Calendars:
   - Open Google Calendar (calendar.google.com)
   - Find the calendar in the left sidebar
   - Click the three dots next to the calendar name → "Settings and sharing"
   - Scroll to "Share with specific people or groups"
   - Click "Add people and groups"
   - Paste the service account email
   - Set permissions: "Make changes to events"
   - Click "Send"
3. Repeat for all 5 stylist calendars

### 1.6 Get Calendar IDs

For each stylist calendar:
1. Open calendar settings (as above)
2. Scroll to "Integrate calendar"
3. Copy the "Calendar ID" (format: `xyz123@group.calendar.google.com`)
4. Save all 5 calendar IDs - you'll need them for `.env` configuration

### 1.7 Test Calendar Access

Run this Python test script to verify access:

```bash
pip install google-auth google-auth-oauthlib google-api-python-client

python3 << 'EOF'
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Replace with your actual path
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = '/path/to/your/service-account-key.json'

creds = service_account.Credentials.from_service_account_file(
    SERVICE_ACCOUNT_FILE, scopes=SCOPES)

service = build('calendar', 'v3', credentials=creds)

# List accessible calendars
calendar_list = service.calendarList().list().execute()
print("Accessible calendars:")
for calendar in calendar_list.get('items', []):
    print(f"  - {calendar['summary']}: {calendar['id']}")
EOF
```

**Expected output:** List of your 5 stylist calendars

### Troubleshooting

| Issue | Solution |
|-------|----------|
| **403 Forbidden Error** | Ensure service account email is shared with calendar (step 1.5) and has "Make changes to events" permission |
| **Service account not found** | Wait 2-3 minutes after creating service account for propagation |
| **No calendars listed** | Verify you've shared calendars with the correct service account email |
| **Invalid credentials** | Re-download JSON key file, ensure file path is correct |

**Official Documentation:** [Google Calendar API Python Quickstart](https://developers.google.com/calendar/api/quickstart/python)

---

## 2. Stripe Account Setup

**Estimated time:** 10 minutes

### 2.1 Create Stripe Account

1. Navigate to [stripe.com](https://stripe.com)
2. Click "Sign up" (use your business email)
3. Complete account registration
4. Verify your email address
5. Fill in basic business information (can be completed later)

### 2.2 Get Test API Keys

1. Log in to [Stripe Dashboard](https://dashboard.stripe.com)
2. Ensure you're in **Test mode** (toggle in upper-right corner should show "Test mode")
3. Navigate to **Developers → API keys**
4. You'll see two keys:
   - **Publishable key** (starts with `pk_test_...`) - Copy this
   - **Secret key** (starts with `sk_test_...`) - Click "Reveal test key" and copy
5. Store both keys securely (password manager or `.env` file)

### 2.3 Get Production API Keys

1. Switch to **Live mode** using toggle in upper-right
2. **IMPORTANT:** You may need to activate your account first:
   - Complete business verification
   - Add bank account details
   - This can take 1-2 business days for approval
3. Once activated, navigate to **Developers → API keys**
4. Copy production keys:
   - **Publishable key** (starts with `pk_live_...`)
   - **Secret key** (starts with `sk_live_...`)
5. **Store production keys separately** from test keys

### 2.4 Configure Webhook Endpoint (Temporary)

**Note:** The actual production webhook URL will be configured in Story 7.5. For now, we'll set up a test webhook.

1. Navigate to **Developers → Webhooks**
2. Click "Add endpoint"
3. For testing, use a temporary endpoint:
   - Use [webhook.site](https://webhook.site) to get a temporary URL
   - Or use [ngrok](https://ngrok.com) for local testing: `ngrok http 8000`
4. Enter the endpoint URL (e.g., `https://webhook.site/your-unique-id`)
5. Click "Select events"
6. Select these event types:
   - `checkout.session.completed`
   - `charge.refunded`
7. Click "Add events"
8. Click "Add endpoint"
9. **Copy the webhook signing secret** (starts with `whsec_...`) - this will be revealed after creation
10. Store the signing secret securely

### 2.5 Document Stripe API Version

1. Navigate to **Developers → API version**
2. Note the current version (e.g., `2024-11-20.acacia`)
3. Document this version in your `.env` file (`STRIPE_API_VERSION`)

### 2.6 Test Stripe API

Test your API keys with curl:

```bash
# Replace sk_test_... with your actual secret key
curl https://api.stripe.com/v1/customers \
  -u sk_test_your_secret_key: \
  -d "email=test@example.com" \
  -d "description=Test customer from setup"
```

**Expected output:** JSON response with customer object

Delete the test customer after verification:
```bash
# Use customer ID from previous response (e.g., cus_...)
curl https://api.stripe.com/v1/customers/cus_xxxxx \
  -u sk_test_your_secret_key: \
  -X DELETE
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| **API key not working** | Ensure you're using test keys in test mode, live keys in live mode |
| **Account activation pending** | Production keys only work after account verification (1-2 days) |
| **Webhook signing secret not visible** | Click on the webhook endpoint to view signing secret |
| **Test mode vs live mode confusion** | Check toggle in upper-right corner, test keys start with `_test_`, live with `_live_` |

**Official Documentation:** [Stripe API Keys](https://stripe.com/docs/keys)

---

## 3. Chatwoot Setup

**Estimated time:** 30 minutes

### 3.1 Choose Deployment Method

You have two options:

**Option A: Chatwoot Cloud** (Recommended for MVP)
- Hosted by Chatwoot
- Faster setup (~15 minutes)
- Monthly fee based on usage
- Navigate to [app.chatwoot.com](https://app.chatwoot.com) and create account

**Option B: Self-Hosted** (More control, requires server)
- Deploy on your own infrastructure
- Free (except server costs)
- More setup time (~30-45 minutes)
- Follow [Chatwoot Docker Installation](https://www.chatwoot.com/docs/self-hosted/deployment/docker)

### 3.2 Create Chatwoot Account (Cloud Option)

1. Navigate to [app.chatwoot.com](https://app.chatwoot.com)
2. Click "Sign up"
3. Enter your email and create password
4. Verify email address
5. Complete onboarding wizard (company name, etc.)

### 3.3 Configure WhatsApp Channel

**Prerequisites:** WhatsApp Business API access via Meta Business Manager

1. In Chatwoot dashboard, navigate to **Settings → Inboxes**
2. Click "Add Inbox"
3. Select "WhatsApp" from channel types
4. Follow the WhatsApp integration wizard:
   - Connect to Meta Business Manager
   - Select your WhatsApp Business Account
   - Authorize Chatwoot to access your WhatsApp number
   - Complete phone number verification
5. **Note:** WhatsApp Business API approval can take 1-7 days depending on Meta's review process
6. Once approved, your WhatsApp inbox will appear in the inbox list

### 3.4 Configure Webhook URL (Placeholder)

**Note:** Actual webhook URL will be configured in Story 1.4 with real endpoint.

1. In your WhatsApp inbox settings, find "Webhook URL" field
2. Enter a placeholder: `https://api.atrevete.com/webhook/chatwoot` (or use webhook.site for testing)
3. Save settings
4. **Important:** You'll update this URL once the API server is deployed

### 3.5 Generate API Access Token

1. Click your profile icon in the upper-right corner
2. Navigate to **Profile Settings**
3. Scroll to "Access Token" section
4. Click "Generate new token"
5. Enter token description: "Atrévete Bot API Access"
6. Copy the generated token (you won't be able to see it again!)
7. Store token securely

### 3.6 Document Account and Inbox IDs

**Account ID:**
1. Look at your browser URL: `https://app.chatwoot.com/app/accounts/{ACCOUNT_ID}/`
2. The number after `/accounts/` is your Account ID (e.g., `12345`)
3. Document this ID

**Inbox ID:**
1. Navigate to **Settings → Inboxes**
2. Click on your WhatsApp inbox
3. Look at the URL: `/app/accounts/{ACCOUNT_ID}/settings/inboxes/{INBOX_ID}`
4. The number after `/inboxes/` is your Inbox ID (e.g., `67890`)
5. Document this ID

### 3.7 Create Team WhatsApp Group

1. On your phone, create a new WhatsApp group
2. Name it: "Atrévete Team Escalations"
3. Add all staff members who should receive escalations
4. Send a test message to the group
5. In Chatwoot, this group will appear as a conversation once connected
6. **Get Conversation ID:**
   - Open the group conversation in Chatwoot
   - Look at URL: `/app/accounts/{ACCOUNT_ID}/conversations/{CONVERSATION_ID}`
   - Document the conversation ID

### 3.8 Test Chatwoot API

Test your API access with curl:

```bash
# Replace with your actual values
CHATWOOT_API_URL="https://app.chatwoot.com"
CHATWOOT_API_TOKEN="your_api_token_here"
CHATWOOT_ACCOUNT_ID="12345"

curl "${CHATWOOT_API_URL}/api/v1/accounts/${CHATWOOT_ACCOUNT_ID}/conversations" \
  -H "api_access_token: ${CHATWOOT_API_TOKEN}" \
  -H "Content-Type: application/json"
```

**Expected output:** JSON array of conversations

### 3.9 Test Webhook (Optional)

Send a test WhatsApp message to your business number and verify:
1. Message appears in Chatwoot inbox
2. If webhook is configured (even to webhook.site), check that webhook payload is received

### Troubleshooting

| Issue | Solution |
|-------|----------|
| **WhatsApp Business API approval pending** | Meta review can take 1-7 days; ensure business verification is complete |
| **API token not working** | Regenerate token, ensure you're using correct account ID |
| **Inbox ID not visible** | Check inbox settings URL, or use API endpoint `/api/v1/accounts/{ACCOUNT_ID}/inboxes` |
| **Group conversation ID not found** | Ensure group has sent/received at least one message, then check conversations list |
| **Self-hosted webhook errors** | Verify firewall allows incoming HTTPS traffic, check Chatwoot logs |

**Official Documentation:** [Chatwoot Documentation](https://www.chatwoot.com/docs/)

---

## 4. Anthropic Claude API Setup

**Estimated time:** 5 minutes

### 4.1 Create Anthropic Account

1. Navigate to [console.anthropic.com](https://console.anthropic.com)
2. Click "Sign Up"
3. Enter email and create password (or use Google/GitHub SSO)
4. Verify your email address
5. Complete account setup

### 4.2 Configure Billing

1. Navigate to **Billing** in the left sidebar
2. Click "Add payment method"
3. Enter credit card details
4. Choose plan:
   - **Free tier:** Limited credits (~$5 worth), suitable for testing only
   - **Pay-as-you-go:** Recommended for production (only pay for what you use)
5. Set up usage limits (optional but recommended):
   - Navigate to **Settings → Usage limits**
   - Set monthly budget (e.g., $100/month)
   - Enable email alerts at 50%, 75%, 90% of budget

### 4.3 Generate API Key

1. Navigate to **API Keys** in the left sidebar
2. Click "Create Key"
3. Enter key description: `atrevete-bot-production`
4. Click "Create Key"
5. **Copy the API key immediately** (starts with `sk-ant-...`)
6. **Important:** You cannot view the key again after closing the dialog
7. Store the key securely

### 4.4 Document API Key Tier

In your setup notes, document:
- **Tier:** Free or Pay-as-you-go
- **Usage limits:** Monthly budget set (if any)
- **Rate limits:** Depends on tier (check [Anthropic docs](https://docs.anthropic.com/en/api/rate-limits))

### 4.5 Test Claude API

Test your API key with curl:

```bash
# Replace with your actual API key
ANTHROPIC_API_KEY="sk-ant-your_key_here"

curl https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{
    "model": "claude-sonnet-4-20250514",
    "max_tokens": 100,
    "messages": [
      {"role": "user", "content": "Hello, Claude! This is a test from Atrévete Bot setup."}
    ]
  }'
```

**Expected output:** JSON response with Claude's greeting

Example:
```json
{
  "id": "msg_...",
  "type": "message",
  "role": "assistant",
  "content": [
    {
      "type": "text",
      "text": "Hello! I'm Claude, and I'm working correctly. How can I help you with the Atrévete Bot?"
    }
  ],
  "model": "claude-sonnet-4-20250514",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 15,
    "output_tokens": 25
  }
}
```

### Troubleshooting

| Issue | Solution |
|-------|----------|
| **API key invalid** | Regenerate key, ensure you copied it correctly (starts with `sk-ant-`) |
| **Rate limit exceeded** | Free tier has strict limits; upgrade to pay-as-you-go or wait for quota reset |
| **Model not found** | Verify model name: `claude-sonnet-4-20250514` (check latest model names in docs) |
| **Billing not configured** | Some API access requires payment method even on free tier |

**Official Documentation:** [Anthropic API Getting Started](https://docs.anthropic.com/en/api/getting-started)

---

## 5. Configure Environment Variables

Now that you have all API credentials, configure your `.env` file:

### 5.1 Copy Template

```bash
cp .env.example .env
```

### 5.2 Fill in Credentials

Edit `.env` and replace all placeholders with your actual credentials:

```bash
# Google Calendar API
GOOGLE_SERVICE_ACCOUNT_JSON=/home/user/.credentials/atrevete-bot/service-account-key.json
GOOGLE_CALENDAR_IDS=stylist1@group.calendar.google.com,stylist2@group.calendar.google.com,stylist3@group.calendar.google.com,stylist4@group.calendar.google.com,stylist5@group.calendar.google.com

# Stripe Payment API
STRIPE_SECRET_KEY=sk_test_51Abc123...
STRIPE_PUBLISHABLE_KEY=pk_test_51Abc123...
STRIPE_WEBHOOK_SECRET=whsec_abc123...
STRIPE_API_VERSION=2024-11-20.acacia

# Chatwoot API
CHATWOOT_API_URL=https://app.chatwoot.com
CHATWOOT_API_TOKEN=abc123def456...
CHATWOOT_ACCOUNT_ID=12345
CHATWOOT_INBOX_ID=67890
CHATWOOT_TEAM_GROUP_ID=54321

# Anthropic Claude API
ANTHROPIC_API_KEY=sk-ant-abc123...

# Database (leave as is for now, configured in Story 1.2)
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/atrevete_bot

# Redis (leave as is for now, configured in Story 1.2)
REDIS_URL=redis://localhost:6379/0

# Application Settings
TIMEZONE=Europe/Madrid
LOG_LEVEL=INFO
```

### 5.3 Verify File Permissions

Ensure `.env` is not world-readable:

```bash
chmod 600 .env
```

### 5.4 Verify .gitignore

Ensure `.gitignore` includes:

```
.env
.env.production
.env.local
*service-account*.json
*credentials*.json
```

**Double-check:** Never commit `.env` to git!

```bash
git status  # .env should NOT appear in untracked files if .gitignore is correct
```

---

## 6. Security Best Practices

### 6.1 Credential Storage

**Development Environment:**
- Store credentials in `.env` file (already gitignored)
- Keep Google service account JSON in `~/.credentials/` directory
- Use a password manager (1Password, LastPass, Bitwarden) to share credentials with team

**Production Environment:**
- Use environment variables set by hosting platform (Docker secrets, Kubernetes secrets)
- **Never** store production credentials in files committed to git
- Rotate API keys every 90 days
- Use separate API keys for production vs staging

### 6.2 Access Control

**Test API Keys:**
- Share with all developers
- Document in shared password manager
- Use only for development/testing

**Production API Keys:**
- Limit access to operations/deployment team only
- Document in separate secure vault
- Enable audit logging where available (Stripe, Google Cloud)

### 6.3 API Key Rotation

Schedule regular key rotation:
- **Google Service Account:** Rotate every 90 days
- **Stripe:** Rotate every 90 days (Stripe allows multiple keys for zero-downtime rotation)
- **Chatwoot:** Rotate every 90 days
- **Anthropic:** Rotate every 90 days

### 6.4 Monitoring

Set up alerts for:
- Unusual API usage spikes (billing alerts)
- Failed authentication attempts (security alerts)
- Rate limit warnings (operational alerts)

---

## 7. General Troubleshooting

### Common Issues Across All Services

| Issue | Solution |
|-------|----------|
| **API key not working immediately** | Wait 2-3 minutes for key propagation across distributed systems |
| **CORS errors in browser** | API keys should only be used server-side, never in frontend JavaScript |
| **403 Forbidden errors** | Check API key has correct permissions/scopes |
| **Rate limiting** | Implement exponential backoff (already in architecture via `tenacity` library) |
| **Webhook not receiving events** | Verify endpoint URL is publicly accessible (not localhost), check firewall rules |

### Verification Checklist

Before proceeding to development, verify:

- [ ] Google Calendar API: Can list events from all 5 stylist calendars
- [ ] Stripe: Test charge created successfully, webhook test event received
- [ ] Chatwoot: Test WhatsApp message sent and received successfully
- [ ] Anthropic Claude: Test completion generated successfully
- [ ] All credentials documented in `.env` file
- [ ] `.env` file NOT committed to git (check `.gitignore`)
- [ ] Team has access to credentials via secure password manager
- [ ] Billing configured for all paid services (Stripe, Anthropic, Chatwoot Cloud if used)

---

## 8. Next Steps

Once all external services are configured:

1. Proceed to **Story 1.1: Project Structure & Dependency Setup**
2. The `.env` file you created will be used to configure the application
3. Integration tests in future stories will validate these API credentials

**Estimated completion time for this entire guide:** 60 minutes

**Need help?** Check the official documentation links in each section, or consult the troubleshooting tables.

---

**Document version:** 1.0
**Last updated:** 2025-10-24
**Maintained by:** Atrévete Bot Development Team

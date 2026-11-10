# Resilient Stripe Sandbox AI Payment Agent (Python + AWS)

**Learning lab: check one Stripe sandbox PaymentIntent and keep the agent working when the MCP server is unavailable.** No real payments or writes; only Stripe's `GET /v1/payment_intents/{id}` endpoint.

## Architecture

![AWS Resilient AI Payment Agent diagram](design/AWS%20Resilient%20AI%20Payment%20Agent%20Diagram.png)

```text
                            AWS API Gateway (IAM auth)
                                     |
                                POST /chat
                                     |
                         Agent Lambda + Bedrock Converse
                                     |
                          get_payment_status tool
                                     |
                      PaymentRouter + CircuitBreaker
                         /                       \
             primary MCP adapter          fallback HTTP adapter
                         |                       |
                API Gateway /mcp                  |
                         |                       |
                     MCP Lambda                  |
                         |                       |
                         +-----------+-----------+
                                     |
                           Stripe Sandbox REST API

  Both Lambda functions obtain a sandbox-only Stripe key via Secrets Manager.
  The business data stays in Stripe; the MCP server is only a tool interface.
```

**Patterns:** Adapter (two interfaces), Strategy (router chooses path), Circuit Breaker (stop repeated MCP calls), Fallback (direct HTTPS GET). Payment status and validation are represented by a single shared contract. The MCP server and agent remain separate Lambda applications.

**Important limitations:** This is a **sandbox-only educational reference**, not a payment processing system, production-ready MCP SDK, SLA guarantee, or PCI-certified deployment. Its MCP layer implements a small **MCP 2025-06-18 Streamable HTTP / JSON-RPC subset** (`initialize`, `notifications/initialized`, `tools/list`, `tools/call`) for straightforward learning. It does not implement SSE, OAuth discovery, full protocol negotiation, user session management, or every MCP feature. For production, replace it with the officially maintained MCP Python SDK and a production-reviewed transport/auth stack. A newer 2026-07-28 MCP revision has changed some wire semantics; the project intentionally pins 2025-06-18 so the client and server agree. The breaker state is per warm Lambda process, *not* globally shared. Lambda/API Gateway provide managed regional availability; they do **not** guarantee 100% uptime.

## 0. Requirements

- **Python 3.12** (matching Lambda runtime), Windows PowerShell or other terminal.
- A Stripe account with **sandbox** and a PaymentIntent created earlier (ID starts `pi_`).
- For AWS phase: AWS CLI v2, AWS SAM CLI, suitable AWS IAM permissions, and Bedrock model access in the chosen Region.
- Expected cost is **not necessarily zero**: API Gateway requests, Lambda compute, CloudWatch logs, Secrets Manager storage, and Bedrock tokens incur charges. Set an AWS Budget alert; alerts do not automatically cap usage.
- **Never** paste Stripe secrets into chat, Git, test files, or API Gateway events. Do not use a live Stripe `sk_live_` key.

## 1. Install and test locally (PowerShell)

Extract ZIP, open PowerShell in the project folder (the directory containing `README.md`). Run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

If `py -3.12` isn't available, install Python 3.12 or use `python -m venv .venv` with a compatible Python.

In this PowerShell window, set local environment variables:

```powershell
$env:STRIPE_TEST_KEY = Read-Host 'Enter your Stripe SANDBOX secret key'
$env:ALLOWED_PAYMENT_INTENT_IDS = 'pi_REPLACE_WITH_YOUR_OWN_ID'
$env:AWS_DEFAULT_REGION = 'us-east-1'
$env:MCP_URL = 'http://127.0.0.1:8765/mcp'
$env:MCP_AWS_IAM = '0'
```

These environment variables are local to the PowerShell session. Use only the test ID you created earlier. Don't place the key in a source file.

### First prove direct API integration (no AI, no MCP)

```powershell
python -m app.cli $env:ALLOWED_PAYMENT_INTENT_IDS --no-ai --mode direct
```

Expected: the response contains `"path": "direct_api"` and a Stripe status such as `requires_payment_method`.

### Then prove MCP integration

Open **a second PowerShell window** in the same folder. Activate the venv and set both environment variables in that window (PowerShell environment variables don't automatically carry into a new window):

```powershell
.\.venv\Scripts\Activate.ps1
$env:STRIPE_TEST_KEY = Read-Host 'Enter sandbox secret key'
$env:ALLOWED_PAYMENT_INTENT_IDS = 'pi_REPLACE_WITH_YOUR_OWN_ID'
python -m app.local_mcp_server
```

Back in the first PowerShell window, run:

```powershell
python -m app.cli $env:ALLOWED_PAYMENT_INTENT_IDS --no-ai
```

Expected: `"path": "mcp"`. Internally, the Python MCP client discovers the tool and the MCP server retrieves the status from Stripe.

### Now simulate an MCP outage

In the first PowerShell window, create `outage.flag` (the local MCP server checks for this file):

```powershell
New-Item -ItemType File outage.flag
python -m app.cli $env:ALLOWED_PAYMENT_INTENT_IDS --no-ai
```

Expected: **same valid payment status**, but `"path": "direct_api"`.

Recover:

```powershell
Remove-Item outage.flag
python -m app.cli $env:ALLOWED_PAYMENT_INTENT_IDS --no-ai
```

Expected: `"path": "mcp"`. This uses a new CLI process each time, so its circuit-breaker state resets on each command. The unit tests demonstrate a sustained failure opening the breaker within one running process.

## 2. Add Amazon Bedrock (optional local stage)

Configure AWS credentials with `aws configure` or your organization's SSO process. Ensure your AWS account can invoke a model that supports Converse tool use (by default `amazon.nova-lite-v1:0` in `us-east-1`).

```powershell
$env:BEDROCK_MODEL_ID = 'amazon.nova-lite-v1:0'
python -m app.cli $env:ALLOWED_PAYMENT_INTENT_IDS
```

Expected: Bedrock selects `get_payment_status`, our application executes the tool using MCP/fallback, and Bedrock summarizes the verified result. The application **rejects** attempts by the model to request a different payment ID. `--no-ai` avoids Bedrock usage and cost during the resilience exercises.

## 3. Deploy on AWS with SAM

1. Open AWS Secrets Manager in the AWS Region you will use (e.g., `us-east-1`). Choose **Store a new secret** → **Other type of secret** → **Plaintext**, and enter **only the sandbox `sk_test_...` secret key**. Name it, for example, `resilient-stripe-lab/test-key`. Copy its **full ARN**. You can use a key/value JSON object instead: `{"STRIPE_TEST_KEY":"sk_test_..."}`.
2. Make sure your AWS identity can create Lambda functions, CloudFormation stacks, IAM roles, API Gateway APIs, read Secrets Manager configuration, and invoke the chosen Bedrock model.
3. In the extracted project folder, run:

```powershell
sam build
sam deploy --guided
```

At prompts, provide:

- Stack name: `resilient-stripe-sandbox`
- AWS Region: `us-east-1` (or another where your chosen Bedrock model is available)
- `StripeSecretArn`: paste the Secrets Manager ARN, **not** the key
- `AllowedPaymentIntentIds`: paste your `pi_...` ID (comma-separated multiple IDs supported)
- `BedrockModelId`: `amazon.nova-lite-v1:0` or a supported model/inference-profile ID
- `SimulateMcpOutage`: `0`
- Allow the IAM resources to be created and deploy (supply deployment capabilities if requested)

After deployment, note the `ChatUrl` and `McpUrl` CloudFormation outputs. The API Gateway endpoints use **AWS IAM authentication**. They cannot be called anonymously with an ordinary `curl` command.

### Invoke the deployed agent from PowerShell

This signed request script uses the AWS credentials configured on your computer. Your local identity must have `execute-api:Invoke` permission for the `/chat` endpoint.

```powershell
python scripts/aws_chat.py --url 'https://REPLACE.execute-api.us-east-1.amazonaws.com/Prod/chat' --payment-id 'pi_REPLACE' --no-ai
```

Then call with Bedrock enabled (requires your model access and IAM permissions):

```powershell
python scripts/aws_chat.py --url 'https://REPLACE.execute-api.us-east-1.amazonaws.com/Prod/chat' --payment-id 'pi_REPLACE'
```

### Simulate an AWS MCP outage

Use the AWS Lambda console to temporarily change the `SIMULATE_MCP_OUTAGE` environment variable of **McpServerFunction** to `1` (you can find the function name in CloudFormation stack outputs). This makes the MCP endpoint respond with HTTP 503. Run the signed `/chat` script again: the response should still succeed, with `"path": "direct_api"`. Restore the variable to `0`; after a few requests or cooldown, the primary MCP path should be used again.

Alternatively, use `sam deploy` with `SimulateMcpOutage=1`; restore it to `0` afterward. Allow a short time for Lambda configuration changes to take effect.

**Important:** do not simulate outage by disabling API Gateway IAM or altering permissions. Those are *security failures* and deliberately do **not** trigger fallback.

## 4. Governance, resilience, and limits

- **Authorization:** `/chat` and `/mcp` use API Gateway IAM. Both adapters validate the explicit `ALLOWED_PAYMENT_INTENT_IDS` allowlist. The Stripe key must start with `sk_test_`; live responses are rejected if `livemode` isn't `false`.
- **Least privilege:** Lambda IAM roles can read the specified secret; the agent may invoke `/mcp` and its configured Bedrock model. Stripe is *read only* in application code. For a real product, use a **restricted sandbox Stripe key with only necessary read privileges**.
- **Fallback:** only MCP connectivity/5xx/malformed-response failures trigger fallback. Unauthorized IDs, credential failures, and known Stripe API outages are rejected; the direct adapter must **not bypass authorization**.
- **Testing:** `pytest` uses fake HTTP transports and service implementations. There are **no real Stripe calls in the tests**. Test scripts do not create payments.
- **Governance:** there is one read-only business contract and both adapters return identical fields. Changes to business semantics should be tested against both paths.
- **Operational observability:** Lambda sends logs to CloudWatch. Look for log messages `payment_status path=mcp`, `payment_status path=direct_api`, and `mcp_transport_unavailable`. Add alarms for fallback rate and latency in a production version. Never log secret keys.
- **Cost:** redundant integrations add maintenance and test coverage, but **do not require duplicate payment business logic**. Because this uses serverless functions rather than always-on EC2, most compute charges scale with requests. Additional API Gateway calls are made for MCP initialize, tool discovery, and calls in this learning implementation.
- **Not protected:** If Stripe itself is down, both paths fail. If Bedrock is down, the AI summary fails (you can still run CLI `--no-ai` or supply a deterministic non-AI app mode). This is not a fully independent business continuity platform.
- **Scale:** the current breaker is process-local. In a larger service, consider centralized health signals, rate limits, retries with jitter, and per-dependency SLOs. Each Lambda instance can have different breaker state.
- **Data safety:** This sample is not for handling real cardholder data. It uses PaymentIntent IDs and minimal response fields only; do not collect card numbers or payment methods in the agent.
- **MCP protocol:** See `app/mcp_protocol.py` for the intentionally minimal MCP transport; it is not a substitute for full SDK-based conformance testing or an enterprise MCP security implementation.

## 5. Tear down AWS resources

When finished:

```powershell
sam delete --stack-name resilient-stripe-sandbox --region us-east-1
```

Then delete your *learning-only* Secrets Manager secret if no other application uses it (AWS may schedule deletion with a recovery window). Check for remaining CloudWatch log groups and costs. Set AWS Budgets before your lab.

## Layout

```text
resilient-payment-agent-mcp/
  app/
    agent.py             # Bedrock Converse tool use, model boundaries
    agent_lambda.py      # AWS /chat endpoint
    cli.py               # local command-line interface
    contract.py          # shared DTO + allowlist
    errors.py            # safe error categories
    local_mcp_server.py  # localhost-only simulation
    mcp_client.py        # MCP adapter + IAM SigV4 signing
    mcp_protocol.py      # minimal MCP server + AWS /mcp endpoint
    resilience.py        # router, circuit breaker, fallback
    stripe_api.py        # direct read-only Stripe API adapter
  scripts/aws_chat.py    # signed AWS API Gateway /chat caller
  tests/                 # unit and failure injection tests
  template.yaml          # AWS SAM deployment, IAM, API Gateway
  requirements.txt
  requirements-dev.txt
  .env.example
  README.md
```

## Official documentation

- Stripe PaymentIntents API: https://docs.stripe.com/api/payment_intents/retrieve
- Stripe testing: https://docs.stripe.com/testing
- Amazon Bedrock tool use: https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html
- AWS SAM: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html
- AWS SAM API IAM auth: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-controlling-access-to-apis-permissions.html
- MCP spec: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- Official MCP Python SDK (production replacement): https://github.com/modelcontextprotocol/python-sdk

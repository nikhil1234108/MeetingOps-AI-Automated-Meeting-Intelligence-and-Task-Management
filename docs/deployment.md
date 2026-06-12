# Origin Medical - Workflow Automation Engine
## Deployment Guide (Local, Docker, and Cloud)

This guide describes the options for deploying the Workflow Automation Engine. Selecting the appropriate option depends on security policies, hosting costs, and operations.

---

## 1. Local Deployment (Development & Testing)

Ideal for initial developer environments, testing offline configurations in Mock Mode, or staging local review gates.

### Instructions:
1. Ensure Python 3.11+ is installed.
2. Clone this repository locally.
3. Configure your local `.env` variables.
4. Run the master script:
   ```bash
   python workflows/run_pipeline.py
   ```
5. Access the review UI at `http://127.0.0.1:8000`.

### Pros:
- Zero hosting costs.
- Instant feedback loop for editing files locally.
- Zero network latency for local file parsing.

### Cons:
- Only accessible on the local loopback interface (`127.0.0.1`).
- Server stops running if the terminal or host machine goes to sleep.

---

## 2. Docker Container Deployment (On-Premises / VM)

Recommended for team environments where multiple coordinators need to access the dashboard on a shared local network or Virtual Private Cloud (VPC).

### Setup:
1. Create a `Dockerfile` in the root:
   ```dockerfile
   FROM python:3.11-slim
   
   WORKDIR /app
   
   # Set compilation bypass flag for pydantic-core
   ENV PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
   
   # Install build dependencies
   RUN apt-get update && apt-get install -y --no-install-recommends \
       build-essential \
       gcc \
       && rm -rf /var/lib/apt/lists/*
       
   COPY requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   
   COPY . .
   
   EXPOSE 8000
   
   CMD ["python", "workflows/run_pipeline.py", "--serve"]
   ```

2. Build and run the container:
   ```bash
   docker build -t origin-automation .
   docker run -d -p 8000:8000 --env-file .env --name origin-automation-running origin-automation
   ```

### Pros:
- Isolates dependencies completely, preventing "works on my machine" version conflicts.
- Easy to scale, deploy, and monitor on standard platforms (AWS ECS, Google Cloud Run, DigitalOcean, local VMs).
- Can be configured behind an Nginx reverse proxy with SSL/HTTPS certificates.

### Cons:
- Requires installing Docker on the target host.
- Larger storage footprint (image size is around 400MB).

---

## 3. Cloud Serverless Deployment (Google Cloud Run / AWS Fargate)

Ideal for fully managed, production-grade deployments that automatically scale down to zero when idle, saving costs.

### Instructions (Google Cloud Run Example):
1. Authenticate with Google Cloud SDK:
   ```bash
   gcloud auth login
   ```
2. Build the container image using Cloud Build:
   ```bash
   gcloud builds submit --tag gcr.io/your-project-id/origin-automation
   ```
3. Deploy to Cloud Run:
   ```bash
   gcloud run deploy origin-automation \
       --image gcr.io/your-project-id/origin-automation \
       --platform managed \
       --region us-central1 \
       --allow-unauthenticated \
       --set-env-vars="GEMINI_API_KEY=your_key,JIRA_DOMAIN=your_domain,JIRA_EMAIL=your_email,JIRA_API_TOKEN=your_token,SLACK_BOT_TOKEN=your_slack_token"
   ```

### Pros:
- **Scale-to-Zero**: You only pay for CPU cycles while a coordinator is actually reviewing transcripts. Free when idle.
- Managed SSL certificates and HTTPS endpoints generated automatically.
- Integrates seamlessly with cloud identity providers (IAM) for authentication.

### Cons:
- First-request "Cold Start" latency of 2–4 seconds if the container is scaled down.
- Requires cloud account configuration and IAM credential management.
